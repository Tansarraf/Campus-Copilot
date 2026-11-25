"""
SQLite FTS5 keyword index over chunk text.

Uses a standalone FTS5 table keyed by chunk rowid (== chunks.id), kept in sync
via triggers. No Gemini calls. Missing/unusable FTS fails soft so vector
retrieval can continue alone.
"""
from __future__ import annotations

import logging
import re
import sqlite3

logger = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]*")


def fts_available(conn: sqlite3.Connection) -> bool:
    try:
        conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS _fts5_probe USING fts5(x)")
        conn.execute("DROP TABLE IF EXISTS _fts5_probe")
        return True
    except sqlite3.Error as exc:
        logger.warning("SQLite FTS5 unavailable: %s", exc)
        return False


def ensure_chunks_fts(conn: sqlite3.Connection) -> bool:
    """
    Create FTS5 table + sync triggers and backfill if empty.
    Returns True when the index is ready for MATCH queries.
    """
    if not fts_available(conn):
        return False

    conn.execute(
        """CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
               text,
               tokenize = 'unicode61 remove_diacritics 2'
           )"""
    )

    # Idempotent triggers: drop/recreate so upgrades stay consistent.
    conn.executescript(
        """
        DROP TRIGGER IF EXISTS chunks_fts_ai;
        DROP TRIGGER IF EXISTS chunks_fts_ad;
        DROP TRIGGER IF EXISTS chunks_fts_au;

        CREATE TRIGGER chunks_fts_ai AFTER INSERT ON chunks BEGIN
          INSERT INTO chunks_fts(rowid, text) VALUES (new.id, new.text);
        END;

        -- Plain DELETE works on contentful FTS5; the 'delete' command can raise SQL logic error.
        CREATE TRIGGER chunks_fts_ad AFTER DELETE ON chunks BEGIN
          DELETE FROM chunks_fts WHERE rowid = old.id;
        END;

        CREATE TRIGGER chunks_fts_au AFTER UPDATE OF text ON chunks BEGIN
          DELETE FROM chunks_fts WHERE rowid = old.id;
          INSERT INTO chunks_fts(rowid, text) VALUES (new.id, new.text);
        END;
        """
    )

    chunk_n = conn.execute("SELECT COUNT(*) AS n FROM chunks").fetchone()[0]
    try:
        fts_n = conn.execute("SELECT COUNT(*) AS n FROM chunks_fts").fetchone()[0]
    except sqlite3.Error:
        fts_n = 0

    if chunk_n and fts_n == 0:
        conn.execute("INSERT INTO chunks_fts(rowid, text) SELECT id, text FROM chunks")
        logger.info("Backfilled chunks_fts with %s rows", chunk_n)
    elif chunk_n and fts_n != chunk_n:
        # Rebuild to clear stale rows after partial failures / legacy DBs.
        conn.execute("DELETE FROM chunks_fts")
        conn.execute("INSERT INTO chunks_fts(rowid, text) SELECT id, text FROM chunks")
        logger.info("Rebuilt chunks_fts (%s chunks)", chunk_n)

    return True


def build_fts_match_query(raw: str) -> str | None:
    """
    Turn a user question into a safe FTS5 MATCH expression.
    Returns None when there are no usable tokens.
    """
    if not raw or not str(raw).strip():
        return None
    tokens = _TOKEN_RE.findall(str(raw))
    if not tokens:
        return None
    # OR improves recall for natural-language questions; quoting blocks operators.
    parts = []
    for tok in tokens[:16]:
        safe = tok.replace('"', "")
        if not safe:
            continue
        parts.append(f'"{safe}"')
    if not parts:
        return None
    return " OR ".join(parts)


def keyword_search_chunk_ids(
    conn: sqlite3.Connection,
    query: str,
    *,
    limit: int = 20,
    category: str | None = None,
    department: str | None = None,
    document_ids: list[int] | None = None,
    include_superseded: bool = True,
) -> list[int]:
    """
    Rank chunk ids by FTS5 bm25 (lower is better). Returns best-first ids.
    Empty list when FTS is missing, query is empty, or nothing matches.
    """
    match = build_fts_match_query(query)
    if not match:
        return []

    tables = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table', 'virtual')"
        )
    }
    if "chunks_fts" not in tables:
        return []

    clauses = ["chunks_fts MATCH ?"]
    params: list = [match]

    join = """
        FROM chunks_fts
        JOIN chunks c ON c.id = chunks_fts.rowid
        JOIN documents d ON d.id = c.document_id
        WHERE
    """
    if category:
        clauses.append("d.category = ?")
        params.append(category)
    if department:
        clauses.append("d.department = ?")
        params.append(department)
    if not include_superseded:
        clauses.append("COALESCE(d.document_status, 'active') != 'superseded'")
    if document_ids is not None:
        if not document_ids:
            return []
        placeholders = ",".join("?" for _ in document_ids)
        clauses.append(f"d.id IN ({placeholders})")
        params.extend(int(i) for i in document_ids)

    sql = f"""
        SELECT c.id AS chunk_id, bm25(chunks_fts) AS rank
        {join}
        {" AND ".join(clauses)}
        ORDER BY rank ASC, c.id ASC
        LIMIT ?
    """
    params.append(int(limit))
    try:
        rows = conn.execute(sql, params).fetchall()
    except sqlite3.Error as exc:
        logger.warning("FTS keyword search failed: %s", exc)
        return []
    return [int(r["chunk_id"] if hasattr(r, "keys") else r[0]) for r in rows]
