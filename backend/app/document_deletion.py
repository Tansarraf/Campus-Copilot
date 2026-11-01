"""Permanent document deletion: SQLite records, chunks/embeddings, and original file."""
from __future__ import annotations

from pathlib import Path

from app.database import get_conn, now_iso
from app.document_storage import resolve_stored_file


class DocumentNotFoundError(LookupError):
    pass


class DocumentFileCleanupError(OSError):
    """Raised when the original file exists but could not be removed."""


def permanently_delete_document(document_id: int) -> dict:
    """
    Permanently remove one document and its indexed data.

    Ordering:
    1. Resolve and delete the original file (if present) while the DB row still
       identifies it — abort before DB mutation if an existing file cannot be removed.
    2. Atomically clear supersession pointers, delete chunks (incl. embeddings),
       and delete the documents row. academic_events.source_document_id is SET NULL
       by foreign key.
    """
    document_id = int(document_id)

    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM documents WHERE id = ?",
            (document_id,),
        ).fetchone()
        if row is None:
            raise DocumentNotFoundError(f"Document {document_id} not found")

        storage_key = None
        if "storage_path" in row.keys():
            storage_key = row["storage_path"]

        file_path = resolve_stored_file(storage_key)
        if file_path is not None:
            _unlink_original(file_path)

        # Clear inbound supersession links only (do not delete the other documents).
        conn.execute(
            """UPDATE documents
               SET supersedes_document_id = NULL, updated_at = ?
               WHERE supersedes_document_id = ?""",
            (now_iso(), document_id),
        )
        # Explicit chunk/embedding removal (also covered by ON DELETE CASCADE).
        conn.execute("DELETE FROM chunks WHERE document_id = ?", (document_id,))
        conn.execute("DELETE FROM documents WHERE id = ?", (document_id,))

        remaining = conn.execute(
            "SELECT COUNT(*) AS n FROM documents WHERE id = ?",
            (document_id,),
        ).fetchone()["n"]
        chunk_remaining = conn.execute(
            "SELECT COUNT(*) AS n FROM chunks WHERE document_id = ?",
            (document_id,),
        ).fetchone()["n"]
        if remaining or chunk_remaining:
            raise RuntimeError(
                f"Deletion incomplete for document {document_id} "
                f"(docs={remaining}, chunks={chunk_remaining})"
            )

    # Belt-and-suspenders: if a path key somehow still resolves, remove it.
    leftover = resolve_stored_file(storage_key)
    if leftover is not None:
        _unlink_original(leftover)

    return {"status": "deleted", "id": document_id}


def _unlink_original(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return
    except OSError as exc:
        raise DocumentFileCleanupError(
            f"Failed to delete original file for document: {exc}"
        ) from exc
