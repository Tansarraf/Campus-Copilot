"""
Evaluation corpus identities and fingerprints.

synthetic_v1  — the seven seed campus fixtures (NOT a real university corpus)
university_v1 — reserved for future genuine documents (empty pack for now)
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

from app.database import get_conn

# Filenames intentionally excluded from synthetic_v1 evaluation without DB deletion.
SYNTHETIC_V1_EXCLUDED_FILENAMES = frozenset({
    "Receipt-2775-3790.pdf",
})

# Stable document keys → source filenames for the synthetic seed pack.
SYNTHETIC_V1_DOCUMENT_KEYS: dict[str, str] = {
    "academic_calendar": "academic_calendar_2026_27.md",
    "fee_payment_circular": "fee_payment_circular.pdf",
    "hostel_rules_handbook": "hostel_rules_handbook.docx",
    "scholarship_notice": "scholarship_notice.md",
    "placement_guidelines": "placement_guidelines.txt",
    "examination_regulations": "examination_regulations.pdf",
    "library_circular": "library_circular.txt",
}

CORPUS_PACKS = {
    "synthetic_v1": {
        "identity": "synthetic_v1",
        "label": "Synthetic campus fixtures (development only)",
        "is_real_university_corpus": False,
        "document_keys": SYNTHETIC_V1_DOCUMENT_KEYS,
        "excluded_filenames": SYNTHETIC_V1_EXCLUDED_FILENAMES,
    },
    "university_v1": {
        "identity": "university_v1",
        "label": "Reserved for genuine university documents",
        "is_real_university_corpus": True,
        "document_keys": {},
        "excluded_filenames": frozenset(),
    },
}


@dataclass(frozen=True)
class CorpusSnapshot:
    identity: str
    label: str
    is_real_university_corpus: bool
    document_ids: list[int]
    filenames: list[str]
    chunk_count: int
    fingerprint: str
    excluded_present: list[str]


def resolve_corpus(corpus_identity: str = "synthetic_v1") -> CorpusSnapshot:
    if corpus_identity not in CORPUS_PACKS:
        raise ValueError(
            f"Unknown corpus identity {corpus_identity!r}. "
            f"Known: {sorted(CORPUS_PACKS)}"
        )
    pack = CORPUS_PACKS[corpus_identity]
    key_to_file = pack["document_keys"]
    excluded = pack["excluded_filenames"]

    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, filename FROM documents ORDER BY id"
        ).fetchall()
        excluded_present = [
            r["filename"] for r in rows if r["filename"] in excluded
        ]

        selected = []
        for key, filename in key_to_file.items():
            match = [r for r in rows if r["filename"] == filename]
            if not match:
                raise ValueError(
                    f"Corpus {corpus_identity}: expected document {filename!r} "
                    f"(key={key}) is not indexed."
                )
            selected.append(match[0])

        doc_ids = [int(r["id"]) for r in selected]
        filenames = [r["filename"] for r in selected]

        if doc_ids:
            placeholders = ",".join("?" for _ in doc_ids)
            chunk_rows = conn.execute(
                f"""SELECT c.id, c.document_id, c.chunk_index, c.section_label, c.text,
                           d.filename
                    FROM chunks c JOIN documents d ON d.id = c.document_id
                    WHERE c.document_id IN ({placeholders})
                    ORDER BY c.document_id, c.chunk_index, c.id""",
                doc_ids,
            ).fetchall()
        else:
            chunk_rows = []

    fingerprint = _fingerprint(corpus_identity, selected, chunk_rows)
    return CorpusSnapshot(
        identity=pack["identity"],
        label=pack["label"],
        is_real_university_corpus=bool(pack["is_real_university_corpus"]),
        document_ids=doc_ids,
        filenames=filenames,
        chunk_count=len(chunk_rows),
        fingerprint=fingerprint,
        excluded_present=excluded_present,
    )


def _fingerprint(identity: str, docs, chunks) -> str:
    h = hashlib.sha256()
    h.update(identity.encode("utf-8"))
    for d in docs:
        h.update(b"|doc|")
        h.update(str(d["filename"]).encode("utf-8"))
    for c in chunks:
        h.update(b"|chunk|")
        h.update(str(c["filename"]).encode("utf-8"))
        h.update(str(c["chunk_index"]).encode("utf-8"))
        h.update((c["section_label"] or "").encode("utf-8"))
        h.update(hashlib.sha256(c["text"].encode("utf-8")).digest())
    return h.hexdigest()
