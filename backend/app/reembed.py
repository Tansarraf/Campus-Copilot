"""
Safe in-place re-embedding of existing chunk rows.

Architecture (preserved):
  generate ALL replacements → validate ALL → (backup) → one transaction UPDATE.

Write mode is full-corpus only. Document-scoped mode is dry-run inspection only.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import numpy as np

from app import config
from app.database import (
    embedding_to_blob,
    get_embedding_index_meta,
    migrate_schema,
    upsert_embedding_index_meta,
)
from app.embedding_validation import (
    EmbeddingIdentity,
    EmbeddingValidationError,
    MOCK_DIM,
    configured_embedding_identity,
    validate_embedding_vector,
)
from app.embeddings import embed_batch


EmbedFn = Callable[[list[str]], list[np.ndarray]]


@dataclass
class ChunkRef:
    chunk_id: int
    document_id: int
    text: str
    embedding_dim: int
    embedding_blob: bytes


@dataclass
class IndexState:
    """Observed state of the chunk store + optional metadata row."""
    empty: bool
    consistent: bool
    dims: set[int]
    chunk_count: int
    meta: dict | None
    inferred_mode: str | None  # mock | real | None if unknown/ambiguous
    errors: list[str] = field(default_factory=list)

    @property
    def uniform_dim(self) -> int | None:
        if len(self.dims) == 1:
            return next(iter(self.dims))
        return None


@dataclass
class ReembedResult:
    dry_run: bool
    document_id: int | None
    chunks_considered: int = 0
    chunks_validated: int = 0
    chunks_updated: int = 0
    vector_dim: int | None = None
    mode: str = "mock"
    provider: str = ""
    model_name: str = ""
    backup_path: str | None = None
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _now_stamp() -> str:
    # Include microseconds so consecutive backups in the same second never collide.
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def open_db(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    migrate_schema(conn)
    conn.commit()
    return conn


def create_database_backup(
    db_path: str | Path,
    source_conn: sqlite3.Connection | None = None,
) -> Path:
    """
    Create a consistent SQLite snapshot via the Online Backup API.

    Operational note: stop the backend (uvicorn) during a full index migration so
    no concurrent writers race the migration transaction. The backup itself is
    SQLite-consistent even if other connections exist, but migration safety is
    highest with the API idle.
    """
    src_path = Path(db_path).resolve()
    if not src_path.is_file():
        raise FileNotFoundError(f"Database not found: {src_path}")

    dest = src_path.with_name(f"{src_path.name}.backup_reembed_{_now_stamp()}")
    if dest.exists():
        raise FileExistsError(f"Backup target already exists: {dest}")

    owns_source = source_conn is None
    src = source_conn or sqlite3.connect(str(src_path))
    dst = sqlite3.connect(str(dest))
    try:
        with dst:
            src.backup(dst)
        # Verification: backup must open and expose expected schema objects.
        verify = sqlite3.connect(str(dest))
        try:
            tables = {
                r[0]
                for r in verify.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            if "chunks" not in tables or "documents" not in tables:
                raise RuntimeError(
                    f"Backup verification failed: missing core tables in {dest}"
                )
            verify.execute("SELECT COUNT(*) FROM chunks").fetchone()
            verify.execute("SELECT COUNT(*) FROM documents").fetchone()
        finally:
            verify.close()
    except Exception:
        dst.close()
        if dest.exists():
            try:
                dest.unlink()
            except OSError:
                pass
        if owns_source:
            src.close()
        raise
    else:
        dst.close()
        if owns_source:
            src.close()
    return dest


def inspect_index_state(conn: sqlite3.Connection) -> IndexState:
    rows = conn.execute("SELECT embedding_dim FROM chunks").fetchall()
    dims = {int(r["embedding_dim"]) for r in rows}
    meta = get_embedding_index_meta(conn)
    errors: list[str] = []

    if not rows:
        return IndexState(
            empty=True,
            consistent=True,
            dims=set(),
            chunk_count=0,
            meta=meta,
            inferred_mode=None,
        )

    if len(dims) != 1:
        errors.append(
            f"Inconsistent chunk embedding dimensions: {sorted(dims)}. "
            "Refuse to proceed; repair with a full-corpus re-embed."
        )
        return IndexState(
            empty=False,
            consistent=False,
            dims=dims,
            chunk_count=len(rows),
            meta=meta,
            inferred_mode=None,
            errors=errors,
        )

    uniform = next(iter(dims))
    if meta is not None and int(meta["vector_dim"]) != uniform:
        errors.append(
            f"embedding_index_meta.vector_dim={meta['vector_dim']} disagrees with "
            f"chunk embedding_dim={uniform}."
        )
        return IndexState(
            empty=False,
            consistent=False,
            dims=dims,
            chunk_count=len(rows),
            meta=meta,
            inferred_mode=None,
            errors=errors,
        )

    if meta is not None:
        inferred = meta.get("mode")
        if inferred not in ("mock", "real"):
            errors.append(f"Invalid embedding_index_meta.mode={inferred!r}.")
            return IndexState(
                empty=False,
                consistent=False,
                dims=dims,
                chunk_count=len(rows),
                meta=meta,
                inferred_mode=None,
                errors=errors,
            )
        return IndexState(
            empty=False,
            consistent=True,
            dims=dims,
            chunk_count=len(rows),
            meta=meta,
            inferred_mode=inferred,
        )

    # No meta: infer mode only when unambiguous.
    if uniform == MOCK_DIM:
        inferred_mode = "mock"
    else:
        inferred_mode = "real"

    return IndexState(
        empty=False,
        consistent=True,
        dims=dims,
        chunk_count=len(rows),
        meta=None,
        inferred_mode=inferred_mode,
    )


def assert_index_replacement_allowed(
    state: IndexState,
    target: EmbeddingIdentity,
    *,
    allow_index_replacement: bool,
) -> None:
    """Raise EmbeddingValidationError unless the transition is permitted."""
    if not state.consistent:
        raise EmbeddingValidationError(
            " ".join(state.errors)
            or "Index state is inconsistent; refusing to re-embed."
        )
    if state.empty:
        return

    source_mode = state.inferred_mode
    source_provider = None
    source_model = None
    if state.meta:
        source_provider = (state.meta.get("provider") or "").strip() or None
        source_model = (state.meta.get("model_name") or "").strip() or None
        source_mode = state.meta.get("mode") or source_mode

    same_mode = source_mode == target.mode
    same_model = True
    if source_provider and source_model:
        same_model = (
            source_provider == target.provider and source_model == target.model_name
        )
    elif source_mode == "real" and target.mode == "real" and state.meta is None:
        # Legacy real index without model identity — require explicit replacement
        # so we do not silently assume the configured model matches.
        same_model = False

    if same_mode and same_model:
        return

    if allow_index_replacement:
        return

    src_label = (
        f"{source_provider}/{source_model} (mode={source_mode})"
        if source_provider and source_model
        else f"mode={source_mode}, dim={state.uniform_dim}"
    )
    raise EmbeddingValidationError(
        f"Refusing to replace embedding index {src_label} with "
        f"{target.label()} without explicit opt-in. Re-run with "
        "--allow-index-replacement after reviewing the migration plan "
        "(and stop the backend during the write)."
    )


def assert_ingestion_compatible_with_index(
    conn: sqlite3.Connection,
    incoming_dim: int,
    incoming: EmbeddingIdentity,
) -> None:
    """
    Block ordinary document ingestion from creating a mixed / incompatible index.
    Does not mutate metadata.
    """
    state = inspect_index_state(conn)
    if not state.consistent:
        raise EmbeddingValidationError(
            " ".join(state.errors)
            or "Existing embedding index is inconsistent; refuse new ingestion."
        )
    if state.empty:
        return

    if state.uniform_dim is not None and int(incoming_dim) != int(state.uniform_dim):
        raise EmbeddingValidationError(
            f"Cannot ingest chunks with dim={incoming_dim} into an index of "
            f"dim={state.uniform_dim}. Re-embed the full corpus or keep the "
            "same embedding configuration."
        )

    if state.meta:
        if (
            (state.meta.get("provider") or "").strip() != incoming.provider
            or (state.meta.get("model_name") or "").strip() != incoming.model_name
            or (state.meta.get("mode") or "").strip() != incoming.mode
        ):
            raise EmbeddingValidationError(
                "Configured embedder does not match embedding_index_meta "
                f"({state.meta.get('provider')}/{state.meta.get('model_name')} "
                f"mode={state.meta.get('mode')}). Align USE_MOCK_LLM / "
                "GEMINI_EMBEDDING_MODEL or run a full-corpus re-embed with "
                "--allow-index-replacement."
            )
    else:
        # Legacy index without meta: only allow same inferred mode + dim.
        if state.inferred_mode != incoming.mode:
            raise EmbeddingValidationError(
                f"Legacy index appears mode={state.inferred_mode} but ingestion "
                f"would use {incoming.label()}. Establish metadata with a "
                "full-corpus re-embed before adding documents."
            )


def load_chunks_for_reembed(
    conn: sqlite3.Connection,
    document_id: int | None = None,
) -> list[ChunkRef]:
    if document_id is None:
        rows = conn.execute(
            """SELECT id, document_id, text, embedding, embedding_dim
               FROM chunks ORDER BY document_id ASC, id ASC"""
        ).fetchall()
    else:
        doc = conn.execute(
            "SELECT id FROM documents WHERE id = ?", (document_id,)
        ).fetchone()
        if doc is None:
            raise LookupError(f"Document id {document_id} does not exist")
        rows = conn.execute(
            """SELECT id, document_id, text, embedding, embedding_dim
               FROM chunks WHERE document_id = ? ORDER BY id ASC""",
            (document_id,),
        ).fetchall()
    return [
        ChunkRef(
            chunk_id=int(r["id"]),
            document_id=int(r["document_id"]),
            text=r["text"],
            embedding_dim=int(r["embedding_dim"]),
            embedding_blob=r["embedding"],
        )
        for r in rows
    ]


def default_embed_fn(texts: list[str]) -> list[np.ndarray]:
    """Reuse the project's embedding layer (mock or Gemini per config)."""
    return embed_batch(texts, task_type="retrieval_document")


def generate_replacement_embeddings(
    chunks: list[ChunkRef],
    embed_fn: EmbedFn | None = None,
    *,
    progress: Callable[[str], None] | None = None,
) -> list[tuple[ChunkRef, np.ndarray]]:
    """
    Embed every chunk, validate each vector, and ensure a single shared dim.
    On any failure, raise EmbeddingValidationError — callers must not write.
    """
    if not chunks:
        return []
    embed = embed_fn or default_embed_fn
    log = progress or (lambda _msg: None)

    texts = [c.text for c in chunks]
    log(f"Generating embeddings for {len(texts)} chunk(s)…")
    try:
        vectors = embed(texts)
    except Exception as exc:
        raise EmbeddingValidationError(
            f"Embedding provider failed before any database update: {type(exc).__name__}: {exc}"
        ) from exc

    if vectors is None or len(vectors) != len(chunks):
        raise EmbeddingValidationError(
            f"Embedding provider returned {0 if vectors is None else len(vectors)} "
            f"vector(s) for {len(chunks)} chunk(s)"
        )

    expected_dim: int | None = None
    prepared: list[tuple[ChunkRef, np.ndarray]] = []
    for chunk, raw in zip(chunks, vectors):
        arr = validate_embedding_vector(
            raw,
            expected_dim=expected_dim,
            chunk_id=chunk.chunk_id,
            document_id=chunk.document_id,
        )
        if expected_dim is None:
            expected_dim = int(arr.shape[0])
        prepared.append((chunk, arr))
        log(
            f"  validated chunk_id={chunk.chunk_id} document_id={chunk.document_id} "
            f"dim={arr.shape[0]}"
        )
    return prepared


def apply_embedding_updates(
    conn: sqlite3.Connection,
    prepared: list[tuple[ChunkRef, np.ndarray]],
) -> int:
    """UPDATE only embedding + embedding_dim. Caller owns the transaction."""
    updated = 0
    for chunk, vec in prepared:
        cur = conn.execute(
            """UPDATE chunks
               SET embedding = ?, embedding_dim = ?
               WHERE id = ? AND document_id = ?""",
            (
                embedding_to_blob(vec),
                int(vec.shape[0]),
                chunk.chunk_id,
                chunk.document_id,
            ),
        )
        if cur.rowcount != 1:
            raise RuntimeError(
                f"Failed to update chunk_id={chunk.chunk_id} "
                f"(document_id={chunk.document_id}); row missing mid-transaction"
            )
        updated += 1
    return updated


def run_reembed(
    *,
    db_path: str | Path | None = None,
    document_id: int | None = None,
    dry_run: bool = False,
    embed_fn: EmbedFn | None = None,
    progress: Callable[[str], None] | None = None,
    create_backup: bool = True,
    allow_index_replacement: bool = False,
) -> ReembedResult:
    """
    Full re-embed workflow.

    Write mode requires the complete corpus (document_id must be None).
    --document-id is allowed only with dry_run=True for inspection.
    """
    path = Path(db_path or config.DATABASE_PATH)
    log = progress or print
    identity = configured_embedding_identity()
    result = ReembedResult(
        dry_run=dry_run,
        document_id=document_id,
        mode=identity.mode,
        provider=identity.provider,
        model_name=identity.model_name,
    )

    if not dry_run and document_id is not None:
        result.errors.append(
            "Write-mode re-embedding is full-corpus only. "
            "Omit --document-id for writes, or use --dry-run --document-id N "
            "for inspection."
        )
        return result

    if not path.is_file():
        result.errors.append(f"Database not found: {path}")
        return result

    conn = open_db(path)
    try:
        try:
            chunks = load_chunks_for_reembed(conn, document_id=document_id)
        except LookupError as exc:
            result.errors.append(str(exc))
            log(f"FAILED: {exc}")
            return result

        result.chunks_considered = len(chunks)
        if not chunks:
            msg = (
                f"No chunks found for document_id={document_id}"
                if document_id is not None
                else "No chunks found in database"
            )
            log(msg)
            # Empty corpus: do not write misleading metadata.
            return result

        # Overwrite / transition guards (also for dry-run so operators see refusal early).
        # Document-scoped dry-run still inspects global index state for transitions.
        state = inspect_index_state(conn)
        try:
            assert_index_replacement_allowed(
                state,
                identity,
                allow_index_replacement=allow_index_replacement,
            )
        except EmbeddingValidationError as exc:
            result.errors.append(str(exc))
            log(f"FAILED index replacement check: {exc}")
            return result

        try:
            prepared = generate_replacement_embeddings(
                chunks, embed_fn=embed_fn, progress=log
            )
        except EmbeddingValidationError as exc:
            result.errors.append(str(exc))
            log(f"FAILED during generation/validation: {exc}")
            return result

        result.chunks_validated = len(prepared)
        result.vector_dim = int(prepared[0][1].shape[0]) if prepared else None

        if dry_run:
            log(
                f"Dry-run OK: validated {result.chunks_validated} chunk(s) at "
                f"dim={result.vector_dim}; database NOT modified."
            )
            return result

        # Write path: full corpus only (enforced above).
        if create_backup:
            try:
                backup = create_database_backup(path, source_conn=conn)
            except Exception as exc:
                result.errors.append(
                    f"Backup failed; refusing to re-embed: {type(exc).__name__}: {exc}"
                )
                log(result.errors[-1])
                return result
            result.backup_path = str(backup)
            log(f"Backup created and verified: {backup}")
            log(
                "Operational recommendation: stop the backend during full index "
                "migration so no concurrent writers race the update."
            )

        try:
            conn.execute("BEGIN IMMEDIATE")
            updated = apply_embedding_updates(conn, prepared)
            upsert_embedding_index_meta(
                conn,
                provider=result.provider,
                model_name=result.model_name,
                vector_dim=int(result.vector_dim),
                mode=result.mode,
            )
            conn.commit()
            result.chunks_updated = updated
            log(
                f"SUCCESS: updated {updated} chunk embedding(s) to dim={result.vector_dim} "
                f"({result.provider}/{result.model_name}, mode={result.mode})."
            )
        except Exception as exc:
            conn.rollback()
            result.errors.append(
                f"Database update failed and was rolled back: {type(exc).__name__}: {exc}"
            )
            log(result.errors[-1])
            return result

        meta = get_embedding_index_meta(conn)
        if meta:
            log(
                f"embedding_index_meta → provider={meta.get('provider')} "
                f"model={meta['model_name']} dim={meta['vector_dim']} "
                f"mode={meta['mode']} at={meta['last_indexed_at']}"
            )
        return result
    finally:
        conn.close()


def snapshot_chunk_identity(conn: sqlite3.Connection, document_id: int | None = None) -> list[dict]:
    """Helper for tests: capture immutable identity fields."""
    if document_id is None:
        rows = conn.execute(
            """SELECT id, document_id, chunk_index, section_label, page_number, text,
                      embedding_dim, embedding FROM chunks ORDER BY id"""
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT id, document_id, chunk_index, section_label, page_number, text,
                      embedding_dim, embedding FROM chunks
               WHERE document_id = ? ORDER BY id""",
            (document_id,),
        ).fetchall()
    return [dict(r) for r in rows]
