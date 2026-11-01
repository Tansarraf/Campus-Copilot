"""
Stable document / evidence key resolution for evaluation.

Document keys map to filenames (stable across re-ingest of the same seed file).
Chunk keys use `{document_key}:{anchor}` where anchor is a section slug or a
content-marker slug. Resolution verifies a content fingerprint when provided;
mismatches are reported as needing re-annotation rather than silently remapped.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from app.database import get_conn
from app.evaluation.corpus import SYNTHETIC_V1_DOCUMENT_KEYS


def slugify(value: str) -> str:
    s = (value or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")


def content_fingerprint(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:16]


# Content markers for documents whose chunks lack reliable section_label (PDFs).
CONTENT_ANCHORS: dict[str, str] = {
    "fee_payment_circular:tuition_structure": "Tuition Fee Structure",
    "fee_payment_circular:payment_deadlines": "Payment Deadlines",
    "fee_payment_circular:late_fee": "Late Fee Penalty",
    "fee_payment_circular:refund_policy": "Refund Policy",
    "examination_regulations:attendance": "Attendance Requirement",
    "examination_regulations:grading_scale": "Grading Scale",
    "examination_regulations:revaluation": "Revaluation",
    "examination_regulations:malpractice": "Examination Malpractice",
}


@dataclass
class ResolvedDocument:
    key: str
    document_id: int
    filename: str
    title: str


@dataclass
class ResolvedChunk:
    key: str
    chunk_id: int
    document_id: int
    document_key: str
    section_label: str | None
    fingerprint: str
    needs_reannotation: bool = False
    note: str | None = None


@dataclass
class KeyResolutionReport:
    documents: dict[str, ResolvedDocument]
    chunks: dict[str, ResolvedChunk]
    errors: list[str]
    reannotation_warnings: list[str]


def filename_to_document_key(filename: str, key_map: dict[str, str] | None = None) -> str | None:
    mapping = key_map or SYNTHETIC_V1_DOCUMENT_KEYS
    for key, fname in mapping.items():
        if fname == filename:
            return key
    return None


def resolve_document_keys(
    keys: list[str],
    key_map: dict[str, str] | None = None,
) -> tuple[dict[str, ResolvedDocument], list[str]]:
    mapping = key_map or SYNTHETIC_V1_DOCUMENT_KEYS
    resolved: dict[str, ResolvedDocument] = {}
    errors: list[str] = []
    with get_conn() as conn:
        for key in keys:
            filename = mapping.get(key)
            if not filename:
                errors.append(f"Unknown document key: {key}")
                continue
            row = conn.execute(
                "SELECT id, filename, title FROM documents WHERE filename = ?",
                (filename,),
            ).fetchone()
            if row is None:
                errors.append(f"Document key {key} ({filename}) not found in database")
                continue
            resolved[key] = ResolvedDocument(
                key=key,
                document_id=int(row["id"]),
                filename=row["filename"],
                title=row["title"],
            )
    return resolved, errors


def resolve_chunk_key(
    chunk_key: str,
    key_map: dict[str, str] | None = None,
    expected_fingerprint: str | None = None,
) -> tuple[ResolvedChunk | None, str | None]:
    """Resolve one chunk key. Returns (resolved, error)."""
    if ":" not in chunk_key:
        return None, f"Invalid chunk key (expected doc:anchor): {chunk_key}"
    doc_key, anchor = chunk_key.split(":", 1)
    docs, errors = resolve_document_keys([doc_key], key_map=key_map)
    if errors:
        return None, errors[0]
    doc = docs[doc_key]

    with get_conn() as conn:
        rows = conn.execute(
            """SELECT id, document_id, chunk_index, section_label, text
               FROM chunks WHERE document_id = ? ORDER BY chunk_index, id""",
            (doc.document_id,),
        ).fetchall()

    if not rows:
        return None, f"No chunks for document key {doc_key}"

    match = None
    # 1) Explicit content marker table
    marker = CONTENT_ANCHORS.get(chunk_key)
    if marker:
        for r in rows:
            if marker.lower() in (r["text"] or "").lower():
                match = r
                break
    # 2) Section label slug
    if match is None:
        for r in rows:
            if r["section_label"] and slugify(r["section_label"]) == slugify(anchor):
                match = r
                break
    # 3) idxN fallback
    if match is None and anchor.startswith("idx"):
        try:
            idx = int(anchor[3:])
        except ValueError:
            idx = -1
        for r in rows:
            if int(r["chunk_index"]) == idx:
                match = r
                break

    if match is None:
        return None, (
            f"Could not resolve chunk key {chunk_key} against current chunks "
            f"for {doc.filename}; needs re-annotation"
        )

    fp = content_fingerprint(match["text"])
    needs = False
    note = None
    if expected_fingerprint and expected_fingerprint != fp:
        needs = True
        note = (
            f"Content fingerprint changed for {chunk_key} "
            f"(expected {expected_fingerprint}, got {fp}); re-annotate gold evidence"
        )

    return ResolvedChunk(
        key=chunk_key,
        chunk_id=int(match["id"]),
        document_id=int(match["document_id"]),
        document_key=doc_key,
        section_label=match["section_label"],
        fingerprint=fp,
        needs_reannotation=needs,
        note=note,
    ), None


def resolve_keys_for_question(
    document_keys: list[str],
    chunk_keys: list[str],
    key_map: dict[str, str] | None = None,
    chunk_fingerprints: dict[str, str] | None = None,
) -> KeyResolutionReport:
    docs, errors = resolve_document_keys(document_keys, key_map=key_map)
    chunks: dict[str, ResolvedChunk] = {}
    warnings: list[str] = []
    fps = chunk_fingerprints or {}
    for ck in chunk_keys:
        resolved, err = resolve_chunk_key(
            ck, key_map=key_map, expected_fingerprint=fps.get(ck)
        )
        if err:
            errors.append(err)
            continue
        assert resolved is not None
        chunks[ck] = resolved
        if resolved.needs_reannotation and resolved.note:
            warnings.append(resolved.note)
    return KeyResolutionReport(
        documents=docs,
        chunks=chunks,
        errors=errors,
        reannotation_warnings=warnings,
    )
