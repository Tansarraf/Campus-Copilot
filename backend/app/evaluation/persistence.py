"""Persist evaluation runs without overwriting history."""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from app.database import get_conn, init_db, now_iso

RESULTS_DIR = Path(__file__).resolve().parents[2] / "evaluation" / "results"


def new_run_id() -> str:
    ts = now_iso().replace(":", "").replace("+", "Z")
    return f"eval_{ts}_{uuid.uuid4().hex[:8]}"


def save_evaluation_run(
    *,
    run_id: str,
    meta: dict[str, Any],
    summary: dict[str, Any],
    per_question: list[dict[str, Any]],
    status: str = "completed",
) -> dict[str, str]:
    """
    Save to SQLite (evaluation_runs / evaluation_question_results) and mirror JSON.
    Never updates an existing run_id.
    """
    init_db()
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    created_at = meta.get("timestamp") or now_iso()
    summary_json = json.dumps(summary, indent=2)
    payload = {
        "run_id": run_id,
        "meta": meta,
        "summary": summary,
        "per_question": per_question,
        "status": status,
    }
    json_path = RESULTS_DIR / f"{run_id}.json"
    if json_path.exists():
        raise FileExistsError(f"Result file already exists: {json_path}")

    with get_conn() as conn:
        existing = conn.execute(
            "SELECT 1 FROM evaluation_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        if existing:
            raise FileExistsError(f"evaluation_runs already has run_id={run_id}")
        conn.execute(
            """INSERT INTO evaluation_runs (
                   run_id, created_at, benchmark_pack, benchmark_version,
                   corpus_identity, corpus_fingerprint, document_count, chunk_count,
                   mock_mode, embedding_provider, embedding_model, embedding_dim,
                   generation_provider, generation_model, top_k, confidence_threshold,
                   retrieval_only, summary_json, status
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run_id,
                created_at,
                meta.get("benchmark_pack"),
                meta.get("benchmark_version"),
                meta.get("corpus_identity"),
                meta.get("corpus_fingerprint"),
                int(meta.get("document_count") or 0),
                int(meta.get("chunk_count") or 0),
                1 if meta.get("mock_mode") else 0,
                meta.get("embedding_provider"),
                meta.get("embedding_model"),
                meta.get("embedding_dim"),
                meta.get("generation_provider"),
                meta.get("generation_model"),
                int(meta.get("top_k") or 0),
                meta.get("confidence_threshold"),
                1 if meta.get("retrieval_only") else 0,
                summary_json,
                status,
            ),
        )
        for row in per_question:
            conn.execute(
                """INSERT INTO evaluation_question_results (run_id, question_id, result_json)
                   VALUES (?, ?, ?)""",
                (run_id, row.get("question_id"), json.dumps(row)),
            )

    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return {"run_id": run_id, "json_path": str(json_path)}
