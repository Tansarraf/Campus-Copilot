"""Persistent storage for original uploaded documents (authorized file serving)."""
from __future__ import annotations

import os
import re
import uuid
from pathlib import Path

from app import config

_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


def ensure_documents_dir() -> Path:
    root = Path(config.DOCUMENTS_DIR).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def sanitize_filename(name: str | None) -> str:
    base = os.path.basename(name or "document")
    cleaned = _SAFE_NAME_RE.sub("_", base).strip("._") or "document"
    return cleaned[:180]


def allocate_storage_path(original_filename: str | None) -> tuple[str, Path]:
    """
    Return (relative_storage_key, absolute_path) under DOCUMENTS_DIR.
    Relative keys are stored in SQLite; absolute paths are never exposed to clients.
    """
    root = ensure_documents_dir()
    safe = sanitize_filename(original_filename)
    key = f"{uuid.uuid4().hex}_{safe}"
    abs_path = (root / key).resolve()
    if not str(abs_path).startswith(str(root)):
        raise ValueError("Invalid storage path")
    return key, abs_path


def resolve_stored_file(storage_path: str | None) -> Path | None:
    """Resolve a DB storage_path to an absolute file inside DOCUMENTS_DIR only."""
    if not storage_path:
        return None
    # Reject absolute / traversal inputs from DB corruption or bugs.
    if os.path.isabs(storage_path) or ".." in Path(storage_path).parts:
        return None
    root = ensure_documents_dir()
    candidate = (root / storage_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    if not candidate.is_file():
        return None
    return candidate


def delete_stored_file(storage_path: str | None) -> None:
    path = resolve_stored_file(storage_path)
    if path is None:
        return
    try:
        path.unlink()
    except OSError:
        pass


def mime_for_extension(ext: str) -> str:
    ext = (ext or "").lower().lstrip(".")
    return {
        "pdf": "application/pdf",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "txt": "text/plain; charset=utf-8",
        "md": "text/markdown; charset=utf-8",
        "markdown": "text/markdown; charset=utf-8",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
    }.get(ext, "application/octet-stream")
