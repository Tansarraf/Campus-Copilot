"""
Thin SQLite data layer.

Deliberately raw sqlite3 + hand-written SQL rather than an ORM: for an MVP
whose whole point is to be explainable in a viva, a visible schema and
plain SQL statements are easier to walk someone through than ORM model
magic, and there's no impedance mismatch when storing embeddings as BLOBs.
"""
import json
import sqlite3
import numpy as np
from contextlib import contextmanager
from datetime import datetime, timezone

from app.config import DATABASE_PATH

# Base schema for fresh installs. Existing databases are upgraded via
# migrate_schema() with non-destructive ALTER TABLE / CREATE IF NOT EXISTS.
SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    full_name TEXT NOT NULL,
    first_name TEXT,
    last_name TEXT,
    email TEXT,
    email_verified INTEGER NOT NULL DEFAULT 0,
    account_status TEXT NOT NULL DEFAULT 'active'
        CHECK (account_status IN ('active', 'pending_activation', 'disabled')),
    role TEXT NOT NULL CHECK (role IN ('student', 'admin')),
    department TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS student_profiles (
    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    enrollment_number TEXT NOT NULL UNIQUE
        CHECK (
            length(enrollment_number) = 11
            AND enrollment_number GLOB '[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]'
        ),
    course TEXT NOT NULL,
    academic_year TEXT NOT NULL,
    current_semester INTEGER NOT NULL CHECK (current_semester >= 1 AND current_semester <= 12),
    is_demo INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL,
    title TEXT NOT NULL,
    category TEXT NOT NULL,
    department TEXT,
    academic_year TEXT,
    file_type TEXT NOT NULL,
    uploaded_by INTEGER REFERENCES users(id),
    uploaded_at TEXT NOT NULL,
    storage_path TEXT
);

CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    section_label TEXT,
    page_number INTEGER,
    text TEXT NOT NULL,
    embedding BLOB NOT NULL,
    embedding_dim INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS query_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER REFERENCES users(id),
    query_text TEXT NOT NULL,
    answer_text TEXT NOT NULL,
    top_similarity REAL,
    retrieved_chunk_ids TEXT,
    latency_ms REAL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query_log_id INTEGER NOT NULL REFERENCES query_logs(id) ON DELETE CASCADE,
    rating INTEGER NOT NULL CHECK (rating IN (-1, 1)),
    comment TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conversation_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    citations_json TEXT,
    query_log_id INTEGER REFERENCES query_logs(id),
    confident INTEGER,
    created_at TEXT NOT NULL
);

-- Single-row registry describing the embedding space currently stored in chunks.
-- Updated only by full-corpus re-embedding (or first ingest into an empty index).
CREATE TABLE IF NOT EXISTS embedding_index_meta (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    provider TEXT NOT NULL,
    model_name TEXT NOT NULL,
    vector_dim INTEGER NOT NULL,
    mode TEXT NOT NULL CHECK (mode IN ('mock', 'real')),
    last_indexed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS evaluation_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    benchmark_pack TEXT NOT NULL,
    benchmark_version TEXT NOT NULL,
    corpus_identity TEXT NOT NULL,
    corpus_fingerprint TEXT NOT NULL,
    document_count INTEGER NOT NULL,
    chunk_count INTEGER NOT NULL,
    mock_mode INTEGER NOT NULL,
    embedding_provider TEXT,
    embedding_model TEXT,
    embedding_dim INTEGER,
    generation_provider TEXT,
    generation_model TEXT,
    top_k INTEGER NOT NULL,
    confidence_threshold REAL,
    retrieval_only INTEGER NOT NULL DEFAULT 0,
    summary_json TEXT NOT NULL,
    status TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS evaluation_question_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES evaluation_runs(run_id) ON DELETE CASCADE,
    question_id TEXT NOT NULL,
    result_json TEXT NOT NULL
);

-- Global academic calendar events (shared by all students; admin-managed).
CREATE TABLE IF NOT EXISTS academic_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT,
    category TEXT NOT NULL,
    start_datetime TEXT NOT NULL,
    end_datetime TEXT,
    location TEXT,
    is_official INTEGER NOT NULL DEFAULT 0,
    publication_status TEXT NOT NULL DEFAULT 'published'
        CHECK (publication_status IN ('draft', 'published', 'archived')),
    source_document_id INTEGER REFERENCES documents(id) ON DELETE SET NULL,
    created_by INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    seed_key TEXT UNIQUE
);

CREATE INDEX IF NOT EXISTS idx_chunks_document ON chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_query_logs_user ON query_logs(user_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_student_enrollment ON student_profiles(enrollment_number);
CREATE INDEX IF NOT EXISTS idx_conversations_user ON conversations(user_id);
CREATE INDEX IF NOT EXISTS idx_conversation_messages_conv ON conversation_messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_eval_runs_created ON evaluation_runs(created_at);
CREATE INDEX IF NOT EXISTS idx_eval_q_run ON evaluation_question_results(run_id);
CREATE INDEX IF NOT EXISTS idx_academic_events_start ON academic_events(start_datetime);
CREATE INDEX IF NOT EXISTS idx_academic_events_status ON academic_events(publication_status);
"""

# Created after column migrations so legacy DBs (pre-email column) upgrade safely.
_POST_MIGRATION_INDEXES = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON users(email) WHERE email IS NOT NULL;
"""

# Columns added to legacy `users` tables (pre-portal schema).
_USER_COLUMN_MIGRATIONS = (
    ("first_name", "TEXT"),
    ("last_name", "TEXT"),
    ("email", "TEXT"),
    ("email_verified", "INTEGER NOT NULL DEFAULT 0"),
    ("account_status", "TEXT NOT NULL DEFAULT 'active'"),
)

# Document intelligence columns (nullable; non-destructive).
_DOCUMENT_COLUMN_MIGRATIONS = (
    ("document_type", "TEXT"),
    ("publication_date", "TEXT"),
    ("effective_date", "TEXT"),
    ("expiry_date", "TEXT"),
    ("extraction_method", "TEXT"),
    ("processing_status", "TEXT"),
    ("document_status", "TEXT NOT NULL DEFAULT 'active'"),
    ("supersedes_document_id", "INTEGER"),
    ("updated_at", "TEXT"),
    ("storage_path", "TEXT"),
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def get_conn():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _existing_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _split_full_name(full_name: str | None) -> tuple[str, str]:
    parts = (full_name or "").strip().split(None, 1)
    if not parts:
        return ("", "")
    if len(parts) == 1:
        return (parts[0], "")
    return (parts[0], parts[1])


def migrate_schema(conn: sqlite3.Connection) -> None:
    """Repeatable, non-destructive upgrades for existing SQLite files."""
    # 1) Ensure tables exist (CREATE IF NOT EXISTS is a no-op for legacy users).
    conn.executescript(SCHEMA)

    # 2) Add new columns to legacy users tables before indexes that reference them.
    if "users" in {
        r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }:
        cols = _existing_columns(conn, "users")
        for name, decl in _USER_COLUMN_MIGRATIONS:
            if name not in cols:
                conn.execute(f"ALTER TABLE users ADD COLUMN {name} {decl}")

        # Backfill name parts from legacy full_name without overwriting set values.
        rows = conn.execute(
            """SELECT id, full_name, first_name, last_name FROM users
               WHERE (first_name IS NULL OR first_name = '')
                  OR (last_name IS NULL OR last_name = '')"""
        ).fetchall()
        for row in rows:
            first, last = _split_full_name(row["full_name"])
            conn.execute(
                """UPDATE users
                   SET first_name = COALESCE(NULLIF(first_name, ''), ?),
                       last_name = COALESCE(NULLIF(last_name, ''), ?)
                   WHERE id = ?""",
                (first, last, row["id"]),
            )

        conn.execute(
            """UPDATE users SET account_status = 'active'
               WHERE account_status IS NULL OR account_status = ''"""
        )
        conn.execute(
            """UPDATE users SET email_verified = 0
               WHERE email_verified IS NULL"""
        )

    # 3) Indexes that depend on migrated columns.
    conn.executescript(_POST_MIGRATION_INDEXES)

    # 4) embedding_index_meta.provider for DBs created before provider existed.
    if "embedding_index_meta" in {
        r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }:
        meta_cols = _existing_columns(conn, "embedding_index_meta")
        if "provider" not in meta_cols:
            conn.execute(
                "ALTER TABLE embedding_index_meta ADD COLUMN provider TEXT NOT NULL DEFAULT 'unknown'"
            )

    # 5) Document intelligence columns on legacy documents tables.
    if "documents" in {
        r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }:
        doc_cols = _existing_columns(conn, "documents")
        for name, decl in _DOCUMENT_COLUMN_MIGRATIONS:
            if name not in doc_cols:
                conn.execute(f"ALTER TABLE documents ADD COLUMN {name} {decl}")
        conn.execute(
            """UPDATE documents SET document_status = 'active'
               WHERE document_status IS NULL OR document_status = ''"""
        )


def init_db():
    with get_conn() as conn:
        migrate_schema(conn)
        from app.calendar_seed import seed_demo_november_events
        seed_demo_november_events(conn)


def embedding_to_blob(vec: np.ndarray) -> bytes:
    return np.asarray(vec, dtype=np.float32).tobytes()


def blob_to_embedding(blob: bytes, dim: int) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32, count=dim)


def upsert_embedding_index_meta(
    conn: sqlite3.Connection,
    *,
    provider: str,
    model_name: str,
    vector_dim: int,
    mode: str,
    indexed_at: str | None = None,
) -> None:
    """Upsert the single-row embedding_index_meta registry."""
    if mode not in ("mock", "real"):
        raise ValueError("mode must be 'mock' or 'real'")
    if not (provider or "").strip() or not (model_name or "").strip():
        raise ValueError("provider and model_name are required")
    ts = indexed_at or now_iso()
    conn.execute(
        """INSERT INTO embedding_index_meta
           (id, provider, model_name, vector_dim, mode, last_indexed_at)
           VALUES (1, ?, ?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET
             provider = excluded.provider,
             model_name = excluded.model_name,
             vector_dim = excluded.vector_dim,
             mode = excluded.mode,
             last_indexed_at = excluded.last_indexed_at""",
        (provider.strip(), model_name.strip(), int(vector_dim), mode, ts),
    )


def get_embedding_index_meta(conn: sqlite3.Connection) -> dict | None:
    row = conn.execute("SELECT * FROM embedding_index_meta WHERE id = 1").fetchone()
    return dict(row) if row else None


def dumps(obj) -> str:
    return json.dumps(obj)


def loads(s: str):
    return json.loads(s) if s else None
