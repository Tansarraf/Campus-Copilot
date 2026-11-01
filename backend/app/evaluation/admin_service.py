"""
Read-only helpers for the Admin Evaluation Dashboard.

Serves persisted evaluation_runs / evaluation_question_results.
Does not recompute IR metrics from scratch — uses stored summary + per-question JSON.
Normalizes display so unavailable / unmeasured values stay null (never coerced to 0).
"""
from __future__ import annotations

import json
from typing import Any

from app.database import get_conn


def _row_to_run_list_item(row) -> dict[str, Any]:
    summary = json.loads(row["summary_json"]) if row["summary_json"] else {}
    aggregates = summary.get("aggregates") or {}
    return {
        "run_id": row["run_id"],
        "created_at": row["created_at"],
        "benchmark_pack": row["benchmark_pack"],
        "benchmark_version": row["benchmark_version"],
        "corpus_identity": row["corpus_identity"],
        "corpus_fingerprint": row["corpus_fingerprint"],
        "document_count": row["document_count"],
        "chunk_count": row["chunk_count"],
        "mock_mode": bool(row["mock_mode"]),
        "embedding_provider": row["embedding_provider"],
        "embedding_model": row["embedding_model"],
        "embedding_dim": row["embedding_dim"],
        "generation_provider": row["generation_provider"],
        "generation_model": row["generation_model"],
        "top_k": row["top_k"],
        "confidence_threshold": row["confidence_threshold"],
        "retrieval_only": bool(row["retrieval_only"]),
        "status": row["status"],
        "num_questions": summary.get("num_questions"),
        "num_evaluated": summary.get("num_evaluated"),
        "num_skipped": summary.get("num_skipped"),
        "num_api_failures": summary.get("num_api_failures"),
        "key_metrics": {
            "doc_recall@5": aggregates.get("doc_recall@5"),
            "doc_precision@5": aggregates.get("doc_precision@5"),
            "doc_hit_rate@5": aggregates.get("doc_hit_rate@5"),
            "mrr_doc": aggregates.get("mrr_doc"),
        },
        "mode_label": _mode_label(bool(row["mock_mode"])),
        "status_label": _status_label(row["status"], summary),
    }


def _mode_label(mock_mode: bool) -> str:
    return "Mock evaluation" if mock_mode else "Real Gemini evaluation"


def _status_label(status: str, summary: dict) -> str:
    if status == "failed":
        return "Evaluation failed"
    failures = int(summary.get("num_api_failures") or 0)
    skipped = int(summary.get("num_skipped") or 0)
    evaluated = int(summary.get("num_evaluated") or 0)
    total = int(summary.get("num_questions") or 0)
    if failures and evaluated == 0:
        return "Evaluation failed"
    if skipped or failures:
        return "Evaluation partially completed"
    if status == "completed" and (evaluated or total == 0):
        return "Evaluation completed"
    return status or "Unknown"


def _parse_summary(row) -> dict[str, Any]:
    return json.loads(row["summary_json"]) if row["summary_json"] else {}


def build_display_metrics(meta: dict, summary: dict) -> dict[str, Any]:
    """
    Map stored aggregates into dashboard-facing metrics.
    Unavailable values are explicit null with reasons — never fabricated zeros.
    """
    unavailable = list(summary.get("unavailable_metrics") or [])
    aggregates = summary.get("aggregates") or {}
    latency = summary.get("latency") or {}
    answerability = summary.get("answerability") or {}
    mock_mode = bool(meta.get("mock_mode"))

    reasons: dict[str, str] = {}
    for name in unavailable:
        reasons[name] = "Listed as unavailable by the evaluation runner"

    # LLM-as-judge never computed by deterministic runner
    for key, label in (
        ("faithfulness", "llm_judge_faithfulness"),
        ("answer_correctness", "llm_judge_correctness"),
    ):
        reasons[key] = (
            "Not measured — deterministic evaluation does not run an LLM judge"
        )
        if label not in unavailable:
            unavailable.append(label)

    if mock_mode:
        reasons["genuine_gemini_generation_quality"] = (
            "Mock evaluation — not a genuine Gemini quality score"
        )

    answered_count = int(answerability.get("answerable_correct_answer") or 0)
    # Citations / generation quality require at least one generated answer
    generation_ran = any(
        latency.get(k) is not None
        for k in ("generation_p50_ms", "generation_p95_ms")
    )

    def agg(name: str) -> Any:
        val = aggregates.get(name)
        return val  # may be None

    retrieval = {
        "doc_precision": {str(k): agg(f"doc_precision@{k}") for k in (1, 3, 5)},
        "doc_recall": {str(k): agg(f"doc_recall@{k}") for k in (1, 3, 5)},
        "doc_hit_rate": {str(k): agg(f"doc_hit_rate@{k}") for k in (1, 3, 5)},
        "chunk_precision": {str(k): agg(f"chunk_precision@{k}") for k in (1, 3, 5)},
        "chunk_recall": {str(k): agg(f"chunk_recall@{k}") for k in (1, 3, 5)},
        "chunk_hit_rate": {str(k): agg(f"chunk_hit_rate@{k}") for k in (1, 3, 5)},
        "mrr_doc": agg("mrr_doc"),
        "mrr_chunk": agg("mrr_chunk"),
    }

    citation_precision_doc = agg("citation_precision_doc")
    citation_coverage_doc = agg("citation_coverage_doc")
    citation_precision_chunk = agg("citation_precision_chunk")
    citation_coverage_chunk = agg("citation_coverage_chunk")

    if not generation_ran and answered_count == 0:
        citation_precision_doc = None
        citation_coverage_doc = None
        citation_precision_chunk = None
        citation_coverage_chunk = None
        reasons["citation_metrics"] = (
            "Not measured — no answers were generated in this run "
            "(citations only apply when the system answers)"
        )

    answer_quality = {
        "faithfulness": None,
        "answer_correctness": None,
        "citation_precision_doc": citation_precision_doc,
        "citation_coverage_doc": citation_coverage_doc,
        "citation_precision_chunk": citation_precision_chunk,
        "citation_coverage_chunk": citation_coverage_chunk,
        "correct_abstention_rate": _rate(
            answerability.get("unanswerable_correct_abstention"),
            answerability.get("unanswerable_total"),
        ),
        "false_answer_rate": _rate(
            answerability.get("unanswerable_false_answer"),
            answerability.get("unanswerable_total"),
        ),
        "false_abstention_rate": _rate(
            answerability.get("answerable_false_abstention"),
            answerability.get("answerable_total"),
        ),
        "answerable_correct_answer_rate": _rate(
            answerability.get("answerable_correct_answer"),
            answerability.get("answerable_total"),
        ),
        "answerability_counts": answerability,
    }

    performance = {
        "retrieval_p50_ms": latency.get("retrieval_p50_ms"),
        "retrieval_p95_ms": latency.get("retrieval_p95_ms"),
        "generation_p50_ms": latency.get("generation_p50_ms"),
        "generation_p95_ms": latency.get("generation_p95_ms"),
        "e2e_p50_ms": latency.get("e2e_p50_ms"),
        "e2e_p95_ms": latency.get("e2e_p95_ms"),
    }
    if performance["generation_p50_ms"] is None:
        reasons["generation_latency"] = (
            "Not measured — generation did not run (or latency was not recorded)"
        )

    return {
        "retrieval": retrieval,
        "answer_quality": answer_quality,
        "performance": performance,
        "unavailable_metrics": sorted(set(unavailable)),
        "unavailable_reasons": reasons,
        "k_values": summary.get("k_values") or [1, 3, 5],
    }


def _rate(num, den) -> float | None:
    if den is None or int(den) == 0:
        return None
    if num is None:
        return None
    return round(int(num) / int(den), 4)


def get_run_row(run_id: str):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM evaluation_runs WHERE run_id = ?", (run_id,)
        ).fetchone()


def list_runs(
    *,
    corpus: str | None = None,
    mock_mode: bool | None = None,
    embedding_model: str | None = None,
    generation_model: str | None = None,
    q: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> dict[str, Any]:
    clauses: list[str] = []
    params: list[Any] = []
    if corpus:
        clauses.append("corpus_identity = ?")
        params.append(corpus)
    if mock_mode is not None:
        clauses.append("mock_mode = ?")
        params.append(1 if mock_mode else 0)
    if embedding_model:
        clauses.append("embedding_model = ?")
        params.append(embedding_model)
    if generation_model:
        clauses.append("generation_model = ?")
        params.append(generation_model)
    if q:
        clauses.append("(run_id LIKE ? OR corpus_identity LIKE ? OR embedding_model LIKE ?)")
        like = f"%{q}%"
        params.extend([like, like, like])

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with get_conn() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) AS n FROM evaluation_runs {where}", params
        ).fetchone()["n"]
        rows = conn.execute(
            f"""SELECT * FROM evaluation_runs {where}
                ORDER BY created_at DESC LIMIT ? OFFSET ?""",
            [*params, limit, offset],
        ).fetchall()
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "runs": [_row_to_run_list_item(r) for r in rows],
    }


def get_latest_run_id() -> str | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT run_id FROM evaluation_runs ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    return row["run_id"] if row else None


def get_run_detail(run_id: str) -> dict[str, Any] | None:
    row = get_run_row(run_id)
    if not row:
        return None
    summary = _parse_summary(row)
    meta = {
        "run_id": row["run_id"],
        "timestamp": row["created_at"],
        "benchmark_pack": row["benchmark_pack"],
        "benchmark_version": row["benchmark_version"],
        "corpus_identity": row["corpus_identity"],
        "corpus_fingerprint": row["corpus_fingerprint"],
        "document_count": row["document_count"],
        "chunk_count": row["chunk_count"],
        "mock_mode": bool(row["mock_mode"]),
        "embedding_provider": row["embedding_provider"],
        "embedding_model": row["embedding_model"],
        "embedding_dim": row["embedding_dim"],
        "generation_provider": row["generation_provider"],
        "generation_model": row["generation_model"],
        "top_k": row["top_k"],
        "confidence_threshold": row["confidence_threshold"],
        "retrieval_only": bool(row["retrieval_only"]),
        "status": row["status"],
        "mode_label": _mode_label(bool(row["mock_mode"])),
        "status_label": _status_label(row["status"], summary),
    }
    # Prefer richer meta from JSON mirror fields stored only in summary companion —
    # summary_json does not include meta; reconstruct from columns. Optional extras
    # from on-disk file are not required.
    display = build_display_metrics(meta, summary)
    return {
        "run_id": run_id,
        "meta": meta,
        "summary": summary,
        "display_metrics": display,
        "num_questions": summary.get("num_questions"),
        "num_evaluated": summary.get("num_evaluated"),
        "num_skipped": summary.get("num_skipped"),
        "num_api_failures": summary.get("num_api_failures"),
    }


def get_summary() -> dict[str, Any]:
    """Dashboard landing payload: latest run or empty state."""
    run_id = get_latest_run_id()
    if not run_id:
        return {
            "has_runs": False,
            "latest": None,
            "message": (
                "No evaluation results are available yet. "
                "Run an evaluation from the backend CLI: "
                "python scripts/evaluate.py --benchmark synthetic_v1"
            ),
            "cli_hint": "python scripts/evaluate.py --benchmark synthetic_v1",
        }
    detail = get_run_detail(run_id)
    return {
        "has_runs": True,
        "latest": detail,
        "message": None,
        "cli_hint": "python scripts/evaluate.py --benchmark synthetic_v1",
    }


def list_questions(
    run_id: str,
    *,
    category: str | None = None,
    answerability: str | None = None,
    difficulty: str | None = None,
    decision: str | None = None,
    retrieval: str | None = None,
    status: str | None = None,
    q: str | None = None,
    limit: int = 25,
    offset: int = 0,
) -> dict[str, Any] | None:
    if not get_run_row(run_id):
        return None

    with get_conn() as conn:
        rows = conn.execute(
            """SELECT question_id, result_json FROM evaluation_question_results
               WHERE run_id = ? ORDER BY id""",
            (run_id,),
        ).fetchall()

    items = []
    for r in rows:
        data = json.loads(r["result_json"])
        items.append(_question_list_item(data))

    def keep(item: dict) -> bool:
        if category and item.get("category") != category:
            return False
        if answerability and item.get("answerability") != answerability:
            return False
        if difficulty and item.get("difficulty") != difficulty:
            return False
        if decision and item.get("system_decision") != decision:
            return False
        if retrieval == "success" and not item.get("retrieval_hit"):
            return False
        if retrieval == "failure" and item.get("retrieval_hit"):
            return False
        if status == "skipped" and not item.get("skipped"):
            return False
        if status == "error" and not item.get("error"):
            return False
        if status == "ok" and (item.get("skipped") or item.get("error")):
            return False
        if status == "passed" and not item.get("passed"):
            return False
        if status == "failed" and item.get("passed") is not False:
            return False
        if q:
            needle = q.lower()
            blob = f"{item.get('question_id','')} {item.get('question','')}".lower()
            if needle not in blob:
                return False
        return True

    filtered = [i for i in items if keep(i)]
    page = filtered[offset : offset + limit]
    categories = sorted({i.get("category") for i in items if i.get("category")})
    return {
        "run_id": run_id,
        "total": len(filtered),
        "limit": limit,
        "offset": offset,
        "categories": categories,
        "questions": page,
    }


def _question_list_item(data: dict) -> dict[str, Any]:
    metrics = data.get("metrics") or {}
    retrieved = data.get("retrieved") or []
    gold_docs = data.get("expected_document_keys") or []
    retrieved_docs = []
    seen = set()
    first_relevant_rank = None
    for r in retrieved:
        dkey = r.get("document_key") or r.get("filename")
        if dkey and dkey not in seen:
            retrieved_docs.append(dkey)
            seen.add(dkey)
        if first_relevant_rank is None and r.get("document_key") in gold_docs:
            first_relevant_rank = r.get("rank")

    hit = bool(metrics.get("doc_hit_rate@5") or metrics.get("doc_hit_rate@3") or metrics.get("doc_hit_rate@1"))
    if metrics.get("doc_hit_rate@5") is None and metrics.get("doc_hit_rate@1") is None:
        # Fallback: any retrieved doc in gold
        hit = any(r.get("document_key") in gold_docs for r in retrieved) if gold_docs else None

    decision = data.get("system_decision")
    answerability = data.get("answerability_label")
    passed = None
    if data.get("skipped") or data.get("error"):
        passed = False
    elif answerability == "unanswerable":
        passed = decision == "abstained"
    elif answerability == "answerable":
        if decision == "answered" and data.get("answer_contains_expected"):
            passed = True
        elif decision == "abstained":
            passed = False
        elif decision == "answered":
            passed = False if data.get("answer_contains_expected") is False else None
    elif answerability == "partial":
        passed = decision in ("answered", "abstained")

    citations = data.get("citations") or {}
    has_citations = bool(citations.get("document_keys") or citations.get("chunk_keys"))

    return {
        "question_id": data.get("question_id"),
        "question": data.get("question"),
        "category": data.get("category"),
        "difficulty": data.get("difficulty"),
        "answerability": answerability,
        "skipped": bool(data.get("skipped")),
        "error": data.get("error"),
        "skip_reason": data.get("skip_reason"),
        "evaluation_status": (
            "skipped" if data.get("skipped")
            else "error" if data.get("error")
            else "ok"
        ),
        "expected_documents": gold_docs,
        "retrieved_documents": retrieved_docs[:5],
        "retrieval_rank": first_relevant_rank,
        "retrieval_hit": hit,
        "system_decision": decision,
        "citation_status": (
            "present" if has_citations
            else "none" if decision == "answered"
            else "n/a"
        ),
        "latency_ms": data.get("e2e_latency_ms") or data.get("retrieval_latency_ms"),
        "passed": passed,
    }


def get_question_detail(run_id: str, question_id: str) -> dict[str, Any] | None:
    if not get_run_row(run_id):
        return None
    with get_conn() as conn:
        row = conn.execute(
            """SELECT result_json FROM evaluation_question_results
               WHERE run_id = ? AND question_id = ?""",
            (run_id, question_id),
        ).fetchone()
    if not row:
        return None
    data = json.loads(row["result_json"])
    return {
        "run_id": run_id,
        "question": data,
        "list_view": _question_list_item(data),
    }


def get_retrieval_analysis(run_id: str) -> dict[str, Any] | None:
    detail = get_run_detail(run_id)
    if not detail:
        return None
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT result_json FROM evaluation_question_results
               WHERE run_id = ? ORDER BY id""",
            (run_id,),
        ).fetchall()

    questions = [json.loads(r["result_json"]) for r in rows]
    k_values = detail["summary"].get("k_values") or [1, 3, 5]
    display = detail["display_metrics"]["retrieval"]

    # Category breakdown
    by_cat: dict[str, dict] = {}
    no_hit = []
    low_rank = []
    success = []
    excluded_no_gold = 0

    for q in questions:
        if q.get("skipped") or q.get("error"):
            continue
        label = q.get("answerability_label")
        metrics = q.get("metrics") or {}
        if label == "unanswerable" or metrics.get("doc_recall@5") is None:
            if label == "unanswerable" or not (q.get("expected_document_keys") or []):
                excluded_no_gold += 1
                continue

        cat = q.get("category") or "Uncategorized"
        bucket = by_cat.setdefault(
            cat,
            {
                "category": cat,
                "count": 0,
                "doc_hit_rate@5_sum": 0.0,
                "doc_recall@5_sum": 0.0,
                "doc_precision@5_sum": 0.0,
                "mrr_doc_sum": 0.0,
                "measured": 0,
            },
        )
        bucket["count"] += 1
        for key, dest in (
            ("doc_hit_rate@5", "doc_hit_rate@5_sum"),
            ("doc_recall@5", "doc_recall@5_sum"),
            ("doc_precision@5", "doc_precision@5_sum"),
            ("mrr_doc", "mrr_doc_sum"),
        ):
            val = metrics.get(key)
            if val is not None:
                bucket[dest] += float(val)
                if key == "doc_hit_rate@5":
                    bucket["measured"] += 1

        hit5 = metrics.get("doc_hit_rate@5")
        mrr = metrics.get("mrr_doc")
        item = {
            "question_id": q.get("question_id"),
            "question": q.get("question"),
            "category": cat,
            "expected_documents": q.get("expected_document_keys") or [],
            "retrieved": [
                {
                    "rank": r.get("rank"),
                    "document_key": r.get("document_key"),
                    "chunk_key": r.get("chunk_key"),
                    "filename": r.get("filename"),
                    "score": r.get("score"),
                }
                for r in (q.get("retrieved") or [])[:5]
            ],
            "doc_hit_rate@5": hit5,
            "mrr_doc": mrr,
        }
        if hit5 == 0.0:
            no_hit.append(item)
        elif mrr is not None and mrr < 0.5:
            low_rank.append(item)
        elif hit5 == 1.0:
            success.append(item)

    category_breakdown = []
    for cat, b in sorted(by_cat.items()):
        n = b["measured"] or b["count"]
        category_breakdown.append({
            "category": cat,
            "question_count": b["count"],
            "doc_hit_rate@5": round(b["doc_hit_rate@5_sum"] / n, 4) if n else None,
            "doc_recall@5": round(b["doc_recall@5_sum"] / n, 4) if n else None,
            "doc_precision@5": round(b["doc_precision@5_sum"] / n, 4) if n else None,
            "mrr_doc": round(b["mrr_doc_sum"] / n, 4) if n else None,
        })

    return {
        "run_id": run_id,
        "meta": detail["meta"],
        "metrics": display,
        "latency": detail["display_metrics"]["performance"],
        "k_values": k_values,
        "category_breakdown": category_breakdown,
        "excluded_no_gold_count": excluded_no_gold,
        "no_relevant_retrieved": no_hit[:50],
        "low_ranking": low_rank[:50],
        "successful_retrievals": success[:50],
    }


def compare_runs(run_a: str, run_b: str) -> dict[str, Any] | None:
    a = get_run_detail(run_a)
    b = get_run_detail(run_b)
    if not a or not b:
        return None

    warnings = []
    if a["meta"]["benchmark_version"] != b["meta"]["benchmark_version"]:
        warnings.append("Benchmark versions differ — compare carefully.")
    if a["meta"]["corpus_fingerprint"] != b["meta"]["corpus_fingerprint"]:
        warnings.append("Corpus fingerprints differ — datasets are not identical.")
    if a["meta"]["mock_mode"] != b["meta"]["mock_mode"]:
        warnings.append(
            "One run is mock and the other is real — do not treat as a single unlabeled aggregate."
        )
    if a["meta"]["corpus_identity"] != b["meta"]["corpus_identity"]:
        warnings.append("Corpus identities differ.")

    compatible = a["meta"]["mock_mode"] == b["meta"]["mock_mode"]

    def pick(detail, path: list[str]):
        node = detail["display_metrics"]
        for p in path:
            if node is None:
                return None
            node = node.get(p) if isinstance(node, dict) else None
        return node

    metric_paths = [
        (["retrieval", "doc_recall", "5"], "doc_recall@5"),
        (["retrieval", "doc_precision", "5"], "doc_precision@5"),
        (["retrieval", "doc_hit_rate", "5"], "doc_hit_rate@5"),
        (["retrieval", "chunk_recall", "5"], "chunk_recall@5"),
        (["retrieval", "chunk_precision", "5"], "chunk_precision@5"),
        (["retrieval", "mrr_doc"], "mrr_doc"),
        (["retrieval", "mrr_chunk"], "mrr_chunk"),
        (["answer_quality", "citation_precision_doc"], "citation_precision_doc"),
        (["answer_quality", "citation_coverage_doc"], "citation_coverage_doc"),
        (["answer_quality", "correct_abstention_rate"], "correct_abstention_rate"),
        (["answer_quality", "false_answer_rate"], "false_answer_rate"),
        (["answer_quality", "false_abstention_rate"], "false_abstention_rate"),
        (["performance", "retrieval_p50_ms"], "retrieval_p50_ms"),
        (["performance", "retrieval_p95_ms"], "retrieval_p95_ms"),
        (["performance", "generation_p50_ms"], "generation_p50_ms"),
        (["performance", "e2e_p50_ms"], "e2e_p50_ms"),
    ]

    comparisons = []
    for path, label in metric_paths:
        va = detail_get(a["display_metrics"], path)
        vb = detail_get(b["display_metrics"], path)
        comparisons.append({
            "metric": label,
            "run_a": va,
            "run_b": vb,
            "delta": None if va is None or vb is None else round(float(vb) - float(va), 4),
            "comparable": va is not None and vb is not None,
        })

    return {
        "run_a": {"run_id": run_a, "meta": a["meta"]},
        "run_b": {"run_id": run_b, "meta": b["meta"]},
        "compatible_modes": compatible,
        "warnings": warnings,
        "comparisons": comparisons,
    }


def detail_get(obj: dict, path: list) -> Any:
    cur: Any = obj
    for p in path:
        if cur is None or not isinstance(cur, dict):
            return None
        cur = cur.get(p)
    return cur


def get_experiments_view() -> dict[str, Any]:
    """Group runs by configuration dimensions present in stored metadata."""
    listed = list_runs(limit=100, offset=0)
    runs = listed["runs"]
    dimensions = [
        {
            "id": "embedding_model",
            "label": "Embedding model",
            "note": "Taken from evaluation run metadata.",
        },
        {
            "id": "generation_model",
            "label": "Generation model",
            "note": "Taken from evaluation run metadata.",
        },
        {
            "id": "top_k",
            "label": "Retrieval top-K",
            "note": "Configured top-K for the run.",
        },
        {
            "id": "confidence_threshold",
            "label": "Confidence threshold",
            "note": "Abstention threshold used during evaluation.",
        },
        {
            "id": "mock_mode",
            "label": "Mock vs real",
            "note": "Mock and real runs must not be aggregated together.",
        },
    ]
    unimplemented = [
        "Chunk size / overlap changes",
        "Hybrid retrieval",
        "Reranking",
        "Supersession-aware retrieval",
    ]

    groups: dict[str, list] = {}
    for r in runs:
        key = (
            f"{r['embedding_model']}|{r['generation_model']}|"
            f"k={r['top_k']}|thr={r['confidence_threshold']}|"
            f"mock={r['mock_mode']}"
        )
        groups.setdefault(key, []).append(r)

    experiments = []
    for key, group in groups.items():
        experiments.append({
            "config_key": key,
            "run_count": len(group),
            "latest_run_id": group[0]["run_id"],
            "mock_mode": group[0]["mock_mode"],
            "embedding_model": group[0]["embedding_model"],
            "generation_model": group[0]["generation_model"],
            "top_k": group[0]["top_k"],
            "confidence_threshold": group[0]["confidence_threshold"],
            "runs": group,
        })

    return {
        "dimensions": dimensions,
        "unimplemented_dimensions": unimplemented,
        "experiments": experiments,
        "has_runs": bool(runs),
        "message": None if runs else (
            "No completed evaluation runs yet. Execute the CLI evaluation to "
            "populate experiment configurations."
        ),
    }
