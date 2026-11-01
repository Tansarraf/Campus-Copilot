"""Benchmark pack loading and schema validation (evaluation v2)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PACKS_ROOT = Path(__file__).resolve().parents[2] / "evaluation" / "packs"

REQUIRED_FIELDS = {
    "question_id",
    "question",
    "category",
    "expected_answer",
    "expected_document_keys",
    "expected_chunk_keys",
    "answerability",
    "difficulty",
    "evaluation_notes",
}
ANSWERABILITY = {"answerable", "unanswerable", "partial"}
DIFFICULTY = {"easy", "medium", "hard"}


class BenchmarkValidationError(ValueError):
    pass


def pack_dir(pack_name: str) -> Path:
    return PACKS_ROOT / pack_name


def load_benchmark_pack(pack_name: str = "synthetic_v1") -> dict[str, Any]:
    path = pack_dir(pack_name) / "benchmark.json"
    if not path.is_file():
        raise FileNotFoundError(
            f"Benchmark pack not found: {path}. "
            "university_v1 is reserved and may be empty until real docs are annotated."
        )
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    validate_benchmark_pack(data)
    return data


def validate_benchmark_pack(data: dict[str, Any]) -> None:
    if not isinstance(data, dict):
        raise BenchmarkValidationError("Benchmark root must be an object")
    for field in ("pack", "version", "corpus_identity", "questions"):
        if field not in data:
            raise BenchmarkValidationError(f"Missing pack field: {field}")
    if not isinstance(data["questions"], list) or not data["questions"]:
        raise BenchmarkValidationError("questions must be a non-empty list")

    seen_ids: set[str] = set()
    for i, q in enumerate(data["questions"]):
        prefix = f"questions[{i}]"
        if not isinstance(q, dict):
            raise BenchmarkValidationError(f"{prefix} must be an object")
        missing = REQUIRED_FIELDS - set(q)
        if missing:
            raise BenchmarkValidationError(f"{prefix} missing fields: {sorted(missing)}")
        qid = q["question_id"]
        if qid in seen_ids:
            raise BenchmarkValidationError(f"Duplicate question_id: {qid}")
        seen_ids.add(qid)
        if q["answerability"] not in ANSWERABILITY:
            raise BenchmarkValidationError(
                f"{prefix}.answerability invalid: {q['answerability']}"
            )
        if q["difficulty"] not in DIFFICULTY:
            raise BenchmarkValidationError(
                f"{prefix}.difficulty invalid: {q['difficulty']}"
            )
        if not isinstance(q["expected_document_keys"], list):
            raise BenchmarkValidationError(f"{prefix}.expected_document_keys must be a list")
        if not isinstance(q["expected_chunk_keys"], list):
            raise BenchmarkValidationError(f"{prefix}.expected_chunk_keys must be a list")

        if q["answerability"] == "unanswerable":
            if q["expected_document_keys"] or q["expected_chunk_keys"]:
                raise BenchmarkValidationError(
                    f"{prefix}: unanswerable items must not list expected evidence"
                )
            if q.get("expected_answer") not in (None, ""):
                # Allow null/empty only
                if q["expected_answer"] is not None and str(q["expected_answer"]).strip():
                    raise BenchmarkValidationError(
                        f"{prefix}: unanswerable items must not set expected_answer"
                    )
        elif q["answerability"] == "answerable":
            if not q["expected_document_keys"]:
                raise BenchmarkValidationError(
                    f"{prefix}: answerable items require expected_document_keys"
                )
            if not q.get("expected_answer"):
                raise BenchmarkValidationError(
                    f"{prefix}: answerable items require expected_answer"
                )


def list_packs() -> list[str]:
    if not PACKS_ROOT.is_dir():
        return []
    return sorted(
        p.name for p in PACKS_ROOT.iterdir()
        if p.is_dir() and (p / "benchmark.json").is_file()
    )
