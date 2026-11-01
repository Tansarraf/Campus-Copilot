import os
import shutil

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.auth import get_current_user, require_admin
from app.database import get_conn, now_iso
from app.document_metadata import (
    extract_lightweight_metadata,
    set_supersession,
    update_document_metadata,
)
from app.document_deletion import (
    DocumentFileCleanupError,
    DocumentNotFoundError,
    permanently_delete_document,
)
from app.document_storage import (
    allocate_storage_path,
    delete_stored_file,
    mime_for_extension,
    resolve_stored_file,
    sanitize_filename,
)
from app.embedding_validation import EmbeddingCompatibilityError
from app.gemini_errors import GeminiAPIError
from app.ingestion.chunker import chunk_units
from app.ingestion.loaders import load_document
from app.retrieval import index_document_chunks
from app.schemas import DocumentOut

router = APIRouter(prefix="/documents", tags=["documents"])

ALLOWED_EXT = {".pdf", ".docx", ".md", ".markdown", ".txt", ".jpg", ".jpeg", ".png"}


def _row_to_document_out(row) -> DocumentOut:
    data = dict(row)
    storage = data.get("storage_path")
    return DocumentOut(
        id=data["id"],
        filename=data["filename"],
        title=data["title"],
        category=data["category"],
        department=data.get("department"),
        academic_year=data.get("academic_year"),
        file_type=data["file_type"],
        uploaded_at=data["uploaded_at"],
        chunk_count=data.get("chunk_count") or 0,
        document_type=data.get("document_type"),
        publication_date=data.get("publication_date"),
        effective_date=data.get("effective_date"),
        expiry_date=data.get("expiry_date"),
        extraction_method=data.get("extraction_method"),
        processing_status=data.get("processing_status"),
        document_status=data.get("document_status") or "active",
        supersedes_document_id=data.get("supersedes_document_id"),
        updated_at=data.get("updated_at"),
        has_original_file=bool(storage and resolve_stored_file(storage)),
    )


class SupersessionRequest(BaseModel):
    supersedes_document_id: int | None = Field(
        None,
        description="Older document this one replaces; null clears the link on this document.",
    )


def _student_may_access_document(row) -> bool:
    """Students may only open catalogued, successfully processed, active documents."""
    status = (row["document_status"] if "document_status" in row.keys() else None) or "active"
    processing = row["processing_status"] if "processing_status" in row.keys() else None
    return status == "active" and (processing in (None, "ready"))


@router.get("", response_model=list[DocumentOut])
def list_documents(user: dict = Depends(get_current_user)):
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT d.*, (SELECT COUNT(*) FROM chunks c WHERE c.document_id = d.id) AS chunk_count
               FROM documents d ORDER BY d.uploaded_at DESC"""
        ).fetchall()
    if user.get("role") != "admin":
        rows = [r for r in rows if _student_may_access_document(r)]
    return [_row_to_document_out(r) for r in rows]


@router.post("/upload", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
def upload_document(
    file: UploadFile = File(...),
    title: str = Form(...),
    category: str = Form(...),
    department: str | None = Form(None),
    academic_year: str | None = Form(None),
    admin: dict = Depends(require_admin),
):
    title = (title or "").strip()
    category = (category or "").strip()
    if not title:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "title is required")
    if not category:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "category is required")
    if not file.filename:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "file is required")

    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unsupported file type: {ext}")

    original_name = sanitize_filename(file.filename)
    storage_key, abs_path = allocate_storage_path(original_name)

    # Persist original first so the file survives processing / restarts.
    try:
        with open(abs_path, "wb") as out:
            shutil.copyfileobj(file.file, out)
    except OSError as exc:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to store uploaded file: {exc}",
        ) from exc

    document_id: int | None = None
    try:
        try:
            units, load_meta = load_document(str(abs_path))
        except Exception as exc:  # noqa: BLE001 — map extraction failures clearly
            delete_stored_file(storage_key)
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Text extraction failed: {exc}",
            ) from exc

        usable = [u for u in units if (u.get("text") or "").strip()]
        sample_text = "\n".join(u["text"] for u in usable[:5])
        meta = extract_lightweight_metadata(
            title=title,
            filename=original_name,
            category=category,
            department=department,
            academic_year=academic_year,
            file_type=ext.lstrip("."),
            sample_text=sample_text,
        )
        extraction_method = load_meta.get("extraction_method")
        processing_status = "ready" if usable else "extraction_failed"

        with get_conn() as conn:
            cur = conn.execute(
                """INSERT INTO documents (
                       filename, title, category, department, academic_year,
                       file_type, uploaded_by, uploaded_at, storage_path,
                       document_type, publication_date, effective_date, expiry_date,
                       extraction_method, processing_status, document_status,
                       supersedes_document_id, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', NULL, ?)""",
                (
                    original_name,
                    title,
                    category,
                    (department or None) or meta.get("department"),
                    (academic_year or None) or meta.get("academic_year"),
                    ext.lstrip("."),
                    admin["id"],
                    now_iso(),
                    storage_key,
                    meta.get("document_type"),
                    meta.get("publication_date"),
                    meta.get("effective_date"),
                    meta.get("expiry_date"),
                    extraction_method,
                    processing_status,
                    now_iso(),
                ),
            )
            document_id = cur.lastrowid

        if usable:
            chunks = chunk_units(usable)
            try:
                index_document_chunks(document_id, chunks)
            except EmbeddingCompatibilityError as exc:
                update_document_metadata(
                    document_id,
                    {"processing_status": "embedding_failed"},
                )
                raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
            except GeminiAPIError as exc:
                update_document_metadata(
                    document_id,
                    {"processing_status": "embedding_failed"},
                )
                raise HTTPException(
                    status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail=str(exc),
                ) from exc
            except Exception as exc:  # noqa: BLE001
                update_document_metadata(
                    document_id,
                    {"processing_status": "embedding_failed"},
                )
                raise HTTPException(
                    status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail=f"Embedding failed: {exc}",
                ) from exc
            update_document_metadata(
                document_id,
                {"processing_status": "ready"},
            )
        else:
            update_document_metadata(
                document_id,
                {
                    "processing_status": "extraction_failed",
                    "extraction_method": extraction_method,
                },
            )
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "No extractable text found in the uploaded file. "
                    "The original file was stored, but embedding was skipped."
                ),
            )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        if document_id is None:
            delete_stored_file(storage_key)
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ingestion failed: {exc}",
        ) from exc

    with get_conn() as conn:
        row = conn.execute(
            """SELECT d.*, (SELECT COUNT(*) FROM chunks c WHERE c.document_id = d.id) AS chunk_count
               FROM documents d WHERE d.id = ?""",
            (document_id,),
        ).fetchone()
    return _row_to_document_out(row)


@router.get("/{document_id}/file")
def download_document_file(
    document_id: int,
    user: dict = Depends(get_current_user),
    disposition: str = Query("inline", pattern="^(inline|attachment)$"),
):
    """
    Serve the original uploaded file for an authenticated user.
    Paths are resolved only inside DOCUMENTS_DIR via DB storage_path keys.
    """
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM documents WHERE id = ?",
            (document_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")

    if user.get("role") != "admin" and not _student_may_access_document(row):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="This document is not available for student access.",
        )

    # Paths resolve only via DB storage_path keys inside DOCUMENTS_DIR.
    path = resolve_stored_file(row["storage_path"] if "storage_path" in row.keys() else None)
    if path is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail="Original file is not available for this document.",
        )

    filename = sanitize_filename(row["filename"])
    media = mime_for_extension(row["file_type"])
    return FileResponse(
        path,
        media_type=media,
        filename=filename,
        content_disposition_type=disposition,
    )


@router.post("/{document_id}/supersede", response_model=DocumentOut)
def supersede_document(
    document_id: int,
    body: SupersessionRequest,
    admin: dict = Depends(require_admin),
):
    try:
        set_supersession(document_id, body.supersedes_document_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    with get_conn() as conn:
        row = conn.execute(
            """SELECT d.*, (SELECT COUNT(*) FROM chunks c WHERE c.document_id = d.id) AS chunk_count
               FROM documents d WHERE d.id = ?""",
            (document_id,),
        ).fetchone()
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    return _row_to_document_out(row)


@router.delete("/{document_id}")
def delete_document(document_id: int, admin: dict = Depends(require_admin)):
    """
    Permanently delete a document for an authenticated admin.
    Removes the original file, SQLite document row, chunks and embeddings.
    """
    try:
        return permanently_delete_document(document_id)
    except DocumentNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Document not found") from exc
    except DocumentFileCleanupError as exc:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Document deletion failed: {exc}",
        ) from exc
