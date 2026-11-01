"""
Embedding shape / identity checks shared by re-indexing and retrieval.

Deliberately does not truncate, pad, or reshape vectors to force a match —
incompatible corpora must fail loudly with an actionable message.
"""
from __future__ import annotations

from dataclasses import dataclass
import sys

import numpy as np

from app import config
from app.embeddings import MOCK_DIM


class EmbeddingCompatibilityError(ValueError):
    """Query and stored chunk embedding spaces are incompatible."""


class EmbeddingValidationError(ValueError):
    """A candidate embedding failed structural validation."""


# importlib.reload() redefines classes; keep one identity so assertRaises and
# except clauses in already-imported modules (retrieval, reembed) still match.
_mod = sys.modules[__name__]
EmbeddingCompatibilityError = getattr(_mod, "_STABLE_COMPAT", EmbeddingCompatibilityError)
EmbeddingValidationError = getattr(_mod, "_STABLE_VALIDATION", EmbeddingValidationError)
_mod._STABLE_COMPAT = EmbeddingCompatibilityError
_mod._STABLE_VALIDATION = EmbeddingValidationError


MOCK_PROVIDER = "mock"
MOCK_MODEL_NAME = "mock-hash-v1"
GEMINI_PROVIDER = "gemini"


@dataclass(frozen=True)
class EmbeddingIdentity:
    provider: str
    model_name: str
    mode: str  # mock | real

    def label(self) -> str:
        return f"{self.provider}/{self.model_name} (mode={self.mode})"


def configured_embedding_identity() -> EmbeddingIdentity:
    if config.USE_MOCK_LLM:
        return EmbeddingIdentity(
            provider=MOCK_PROVIDER,
            model_name=MOCK_MODEL_NAME,
            mode="mock",
        )
    return EmbeddingIdentity(
        provider=GEMINI_PROVIDER,
        model_name=config.GEMINI_EMBEDDING_MODEL,
        mode="real",
    )


def as_float32_vector(vec) -> np.ndarray:
    arr = np.asarray(vec, dtype=np.float32).reshape(-1)
    return arr


def validate_embedding_vector(
    vec,
    *,
    expected_dim: int | None = None,
    chunk_id: int | None = None,
    document_id: int | None = None,
) -> np.ndarray:
    """
    Ensure a vector is a non-empty, finite float32 array of consistent length.
    Returns the float32 view used for storage.
    """
    try:
        arr = as_float32_vector(vec)
    except (TypeError, ValueError) as exc:
        raise EmbeddingValidationError(
            _context(chunk_id, document_id, f"could not coerce embedding to float array ({exc})")
        ) from exc

    if arr.size == 0:
        raise EmbeddingValidationError(
            _context(chunk_id, document_id, "embedding is empty")
        )
    if not np.isfinite(arr).all():
        raise EmbeddingValidationError(
            _context(chunk_id, document_id, "embedding contains NaN or Inf")
        )
    if expected_dim is not None and int(arr.shape[0]) != int(expected_dim):
        raise EmbeddingValidationError(
            _context(
                chunk_id,
                document_id,
                f"embedding dim {arr.shape[0]} != expected {expected_dim}",
            )
        )
    return arr


def validate_blob_matches_dim(blob: bytes, dim: int, *, chunk_id: int | None = None) -> None:
    expected_bytes = int(dim) * 4  # float32
    if blob is None or len(blob) != expected_bytes:
        raise EmbeddingCompatibilityError(
            f"Chunk {chunk_id}: embedding BLOB length {0 if blob is None else len(blob)} "
            f"does not match embedding_dim={dim} (expected {expected_bytes} bytes). "
            "Re-run scripts/reembed_documents.py after configuring a real Gemini key."
        )


def assert_uniform_chunk_dims(rows) -> int:
    """Return the shared stored dimension, or raise if mixed / missing."""
    if not rows:
        raise EmbeddingCompatibilityError("No chunks available for retrieval.")
    dims = {int(r["embedding_dim"]) for r in rows}
    if len(dims) != 1:
        raise EmbeddingCompatibilityError(
            "Mixed embedding dimensions detected in the chunk store "
            f"({sorted(dims)}). Cosine similarity cannot run on incompatible "
            "vectors. Re-embed the full corpus with scripts/reembed_documents.py "
            "(after setting a real GEMINI_API_KEY and USE_MOCK_LLM=false) so "
            "every chunk uses the same model dimension."
        )
    dim = dims.pop()
    for r in rows:
        validate_blob_matches_dim(r["embedding"], dim, chunk_id=r["id"])
    return dim


def assert_query_dim_matches(query_vec: np.ndarray, stored_dim: int) -> np.ndarray:
    q = as_float32_vector(query_vec)
    if q.size != stored_dim:
        raise EmbeddingCompatibilityError(
            f"Query embedding dimension ({q.size}) does not match stored chunk "
            f"dimension ({stored_dim}). This usually means mock embeddings are "
            "still in the database while retrieval is using a real Gemini model "
            "(or the reverse). Fix: keep USE_MOCK_LLM consistent with the stored "
            "corpus, or re-embed the full corpus with scripts/reembed_documents.py."
        )
    if not np.isfinite(q).all():
        raise EmbeddingCompatibilityError("Query embedding contains NaN or Inf.")
    return q


def index_identity_from_meta(meta: dict | None) -> EmbeddingIdentity | None:
    if not meta:
        return None
    return EmbeddingIdentity(
        provider=(meta.get("provider") or "unknown").strip(),
        model_name=(meta.get("model_name") or "").strip(),
        mode=(meta.get("mode") or "").strip() or "unknown",
    )


def diagnose_embedding_alignment(meta: dict | None = None) -> dict:
    """
    Report configured query embedder vs stored index metadata.
    Does not mutate the database or embeddings.
    """
    from app.database import get_conn, get_embedding_index_meta

    configured = configured_embedding_identity()
    if meta is None:
        with get_conn() as conn:
            meta = get_embedding_index_meta(conn)

    index = index_identity_from_meta(meta)
    aligned = True
    mismatch_reason: str | None = None
    if index is None:
        aligned = True  # empty / unknown index — queries still guard at search time
        mismatch_reason = None
    elif (
        index.provider != configured.provider
        or index.model_name != configured.model_name
        or index.mode != configured.mode
    ):
        aligned = False
        mismatch_reason = (
            "Configured query embedder does not match the stored index: "
            f"query={configured.label()} vs index={index.label()}. "
            "Keep USE_MOCK_LLM / GEMINI_EMBEDDING_MODEL aligned with the index "
            "(clear a stale process-env USE_MOCK_LLM if backend/.env already "
            "sets the correct mode). Do not re-embed unless you intentionally "
            "change models."
        )
        warning = getattr(config, "ENV_FILE_OVERRIDE_WARNING", None)
        if warning:
            mismatch_reason = f"{mismatch_reason} ({warning})"

    return {
        "query_provider": configured.provider,
        "query_model": configured.model_name,
        "query_mode": configured.mode,
        "query_label": configured.label(),
        "index_provider": index.provider if index else None,
        "index_model": index.model_name if index else None,
        "index_mode": index.mode if index else None,
        "index_label": index.label() if index else None,
        "index_vector_dim": int(meta["vector_dim"]) if meta and meta.get("vector_dim") is not None else None,
        "aligned": aligned,
        "mismatch_reason": mismatch_reason,
        "env_file_override_warning": getattr(config, "ENV_FILE_OVERRIDE_WARNING", None),
        "use_mock_llm": bool(config.USE_MOCK_LLM),
    }


def assert_startup_embedding_alignment() -> dict:
    """
    Fail fast when a stored index exists and disagrees with the configured
    query embedder. Prevents accepting chat queries under the wrong mode.
    """
    import logging

    diagnosis = diagnose_embedding_alignment()
    logger = logging.getLogger("campus_copilot.embeddings")
    logger.info(
        "Embedding runtime: query=%s index=%s aligned=%s",
        diagnosis["query_label"],
        diagnosis["index_label"] or "(none)",
        diagnosis["aligned"],
    )
    if diagnosis.get("env_file_override_warning"):
        logger.warning(diagnosis["env_file_override_warning"])
    if not diagnosis["aligned"]:
        raise EmbeddingCompatibilityError(diagnosis["mismatch_reason"] or "Embedding index mismatch.")
    return diagnosis


def assert_query_identity_matches_index(meta: dict | None, stored_dim: int) -> None:
    """
    Compare configured embedder identity to stored index metadata.
    Legacy indexes without meta are only accepted when they unambiguously match
    the current mock setup (uniform MOCK_DIM).
    """
    configured = configured_embedding_identity()
    if meta is None:
        if configured.mode == "mock" and stored_dim == MOCK_DIM:
            return
        raise EmbeddingCompatibilityError(
            "Chunk store has no embedding_index_meta row, so the embedding model "
            "cannot be verified. Run a full-corpus "
            "`python scripts/reembed_documents.py` (with the intended Gemini/mock "
            "configuration) to establish index metadata before querying."
        )

    stored_provider = (meta.get("provider") or "unknown").strip()
    stored_model = (meta.get("model_name") or "").strip()
    stored_mode = (meta.get("mode") or "").strip()
    stored_meta_dim = int(meta["vector_dim"])

    if stored_meta_dim != stored_dim:
        raise EmbeddingCompatibilityError(
            f"embedding_index_meta.vector_dim ({stored_meta_dim}) disagrees with "
            f"stored chunk dimension ({stored_dim}). Index metadata is inconsistent; "
            "refuse to search. Run a full-corpus re-embed to repair."
        )

    if (
        stored_provider != configured.provider
        or stored_model != configured.model_name
        or stored_mode != configured.mode
    ):
        warning = getattr(config, "ENV_FILE_OVERRIDE_WARNING", None)
        extra = f" {warning}" if warning else ""
        raise EmbeddingCompatibilityError(
            "Configured query embedder does not match the stored index: "
            f"query={configured.label()} vs index="
            f"{stored_provider}/{stored_model} (mode={stored_mode}). "
            "Keep USE_MOCK_LLM / GEMINI_EMBEDDING_MODEL aligned with the index, "
            "or run a full-corpus re-embed with --allow-index-replacement."
            f"{extra}"
        )


def _context(chunk_id, document_id, message: str) -> str:
    parts = []
    if document_id is not None:
        parts.append(f"document_id={document_id}")
    if chunk_id is not None:
        parts.append(f"chunk_id={chunk_id}")
    prefix = f"[{', '.join(parts)}] " if parts else ""
    return prefix + message
