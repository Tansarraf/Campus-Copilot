"""
Deterministic evaluation runner (v2).

Uses similarity_search scoped to the selected corpus. Generation uses the
existing generate_answer path when not retrieval_only. No external LLM judge.
"""
from __future__ import annotations

import time
import uuid
from typing import Any

from app import config
from app.database import get_conn, get_embedding_index_meta
from app.embedding_validation import configured_embedding_identity
from app.evaluation.benchmark import load_benchmark_pack
from app.evaluation.corpus import resolve_corpus
from app.evaluation.keys import (
    filename_to_document_key,
    resolve_chunk_key,
    resolve_keys_for_question,
    slugify,
)
from app.evaluation.metrics import (
    answer_contains_expected,
    citation_coverage,
    citation_precision,
    hit_rate_at_k,
    percentile,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
)
from app.evaluation.persistence import new_run_id, save_evaluation_run
from app.generation import NOT_INDEXED_MESSAGE, generate_answer
from app.retrieval import similarity_search


DEFAULT_K_VALUES = (1, 3, 5)


def _mean(values: list[float | None]) -> float | None:
    nums = [v for v in values if v is not None]
    if not nums:
        return None
    return round(sum(nums) / len(nums), 4)


def _chunk_key_for_row(row: dict, doc_key: str | None) -> str | None:
    if not doc_key:
        return None
    if row.get("section_label"):
        return f"{doc_key}:{slugify(row['section_label'])}"
    # Try content anchors by resolving known keys containing this doc
    # Fall back to idxN
    return f"{doc_key}:idx{row.get('chunk_index', 0)}"


def _map_retrieved(chunks: list[dict]) -> tuple[list[str | None], list[str | None], list[dict]]:
    doc_keys: list[str | None] = []
    chunk_keys: list[str | None] = []
    detailed = []
    for rank, c in enumerate(chunks, start=1):
        dkey = filename_to_document_key(c.get("filename") or "")
        # Prefer resolving via section / content when possible
        ckey = None
        if dkey and c.get("section_label"):
            ckey = f"{dkey}:{slugify(c['section_label'])}"
        elif dkey:
            # Attempt content-anchor match against known keys for this doc
            from app.evaluation.keys import CONTENT_ANCHORS

            text_l = (c.get("text") or "").lower()
            for key, marker in CONTENT_ANCHORS.items():
                if key.startswith(dkey + ":") and marker.lower() in text_l:
                    ckey = key
                    break
            if ckey is None:
                ckey = f"{dkey}:idx{c.get('chunk_index', 0)}"
        doc_keys.append(dkey)
        chunk_keys.append(ckey)
        detailed.append({
            "rank": rank,
            "chunk_id": c.get("chunk_id"),
            "document_id": c.get("document_id"),
            "document_key": dkey,
            "chunk_key": ckey,
            "filename": c.get("filename"),
            "section_label": c.get("section_label"),
            "score": c.get("score"),
        })
    return doc_keys, chunk_keys, detailed


def run_evaluation(
    *,
    benchmark_pack: str = "synthetic_v1",
    corpus_identity: str | None = None,
    k_values: tuple[int, ...] = DEFAULT_K_VALUES,
    top_k: int | None = None,
    retrieval_only: bool = False,
    persist: bool = True,
    progress=None,
    retrieval_mode: str | None = None,
) -> dict[str, Any]:
    log = progress or (lambda m: None)
    pack = load_benchmark_pack(benchmark_pack)
    corpus_id = corpus_identity or pack.get("corpus_identity") or benchmark_pack
    corpus = resolve_corpus(corpus_id)
    if corpus.is_real_university_corpus and not corpus.document_ids:
        raise ValueError(
            f"Corpus {corpus_id} has no documents yet (reserved pack)."
        )

    mode = (retrieval_mode or config.RETRIEVAL_MODE or "hybrid").strip().lower()
    if mode not in ("hybrid", "vector", "keyword"):
        mode = "hybrid"

    max_k = max(k_values) if k_values else 5
    retrieve_k = max(top_k or max_k, max_k, 10)
    identity = configured_embedding_identity()

    with get_conn() as conn:
        meta_row = get_embedding_index_meta(conn)
        # Observed dim from corpus chunks if meta missing
        dim_row = None
        if corpus.document_ids:
            placeholders = ",".join("?" for _ in corpus.document_ids)
            dim_row = conn.execute(
                f"""SELECT embedding_dim FROM chunks
                    WHERE document_id IN ({placeholders}) LIMIT 1""",
                corpus.document_ids,
            ).fetchone()

    embedding_dim = None
    if meta_row:
        embedding_dim = int(meta_row["vector_dim"])
    elif dim_row:
        embedding_dim = int(dim_row["embedding_dim"])

    run_id = new_run_id()
    per_question: list[dict[str, Any]] = []
    retrieval_latencies: list[float] = []
    generation_latencies: list[float] = []
    e2e_latencies: list[float] = []

    metric_buckets: dict[str, list[float | None]] = {
        f"doc_precision@{k}": [] for k in k_values
    }
    metric_buckets.update({f"doc_recall@{k}": [] for k in k_values})
    metric_buckets.update({f"doc_hit_rate@{k}": [] for k in k_values})
    metric_buckets.update({f"chunk_precision@{k}": [] for k in k_values})
    metric_buckets.update({f"chunk_recall@{k}": [] for k in k_values})
    metric_buckets.update({f"chunk_hit_rate@{k}": [] for k in k_values})
    metric_buckets["mrr_doc"] = []
    metric_buckets["mrr_chunk"] = []
    metric_buckets["citation_precision_doc"] = []
    metric_buckets["citation_coverage_doc"] = []
    metric_buckets["citation_precision_chunk"] = []
    metric_buckets["citation_coverage_chunk"] = []

    abstention_stats = {
        "answerable_total": 0,
        "answerable_correct_answer": 0,
        "answerable_false_abstention": 0,
        "unanswerable_total": 0,
        "unanswerable_correct_abstention": 0,
        "unanswerable_false_answer": 0,
        "partial_total": 0,
        "classification_correct": 0,
        "classification_total": 0,
        "api_failures": 0,
        "skipped": 0,
    }

    for item in pack["questions"]:
        qid = item["question_id"]
        log(f"Evaluating {qid}…")
        result: dict[str, Any] = {
            "question_id": qid,
            "question": item["question"],
            "category": item["category"],
            "answerability_label": item["answerability"],
            "difficulty": item["difficulty"],
            "expected_answer": item.get("expected_answer"),
            "expected_document_keys": item.get("expected_document_keys") or [],
            "expected_chunk_keys": item.get("expected_chunk_keys") or [],
            "skipped": False,
            "error": None,
        }

        resolution = resolve_keys_for_question(
            item.get("expected_document_keys") or [],
            item.get("expected_chunk_keys") or [],
        )
        if resolution.errors and item["answerability"] != "unanswerable":
            result["skipped"] = True
            result["skip_reason"] = "; ".join(resolution.errors)
            result["reannotation_warnings"] = resolution.reannotation_warnings
            abstention_stats["skipped"] += 1
            per_question.append(result)
            continue
        if resolution.reannotation_warnings:
            result["reannotation_warnings"] = resolution.reannotation_warnings

        gold_docs = set(resolution.documents.keys()) or set(item.get("expected_document_keys") or [])
        gold_chunks = set(resolution.chunks.keys()) or set(item.get("expected_chunk_keys") or [])
        # If chunk keys failed partially, keep whatever resolved
        if resolution.chunks:
            gold_chunks = set(resolution.chunks.keys())
        if resolution.documents:
            gold_docs = set(resolution.documents.keys())

        result["resolved_document_ids"] = {
            k: v.document_id for k, v in resolution.documents.items()
        }
        result["resolved_chunk_ids"] = {
            k: v.chunk_id for k, v in resolution.chunks.items()
        }

        try:
            t0 = time.perf_counter()
            # Keyword IR benchmarks can skip Gemini; production/query path keeps scores.
            attach_scores = not (retrieval_only and mode == "keyword")
            chunks, retrieval_ms = None, 0.0
            last_exc: Exception | None = None
            for attempt in range(4):
                try:
                    chunks, retrieval_ms = similarity_search(
                        item["question"],
                        top_k=retrieve_k,
                        document_ids=corpus.document_ids,
                        retrieval_mode=mode,
                        attach_vector_scores=attach_scores,
                    )
                    last_exc = None
                    break
                except Exception as exc:  # noqa: BLE001 — retry only rate-limit class
                    last_exc = exc
                    msg = str(exc).lower()
                    if attempt < 3 and ("rate limit" in msg or "quota" in msg or "429" in msg):
                        time.sleep(15 * (attempt + 1))
                        continue
                    raise
            if last_exc is not None:
                raise last_exc
            retrieval_latencies.append(float(retrieval_ms))
            result["retrieval_latency_ms"] = round(float(retrieval_ms), 3)
        except Exception as exc:
            abstention_stats["api_failures"] += 1
            result["error"] = f"retrieval_failure: {type(exc).__name__}: {exc}"
            result["system_decision"] = "api_failure"
            per_question.append(result)
            continue

        doc_keys, chunk_keys, detailed = _map_retrieved(chunks)
        result["retrieved"] = detailed

        # Retrieval metrics: undefined when no gold evidence (unanswerable / empty).
        has_gold_docs = bool(gold_docs) and item["answerability"] != "unanswerable"
        has_gold_chunks = bool(gold_chunks) and item["answerability"] != "unanswerable"
        gold_docs_for_ir = gold_docs if has_gold_docs else set()
        gold_chunks_for_ir = gold_chunks if has_gold_chunks else set()

        metrics: dict[str, Any] = {}
        for k in k_values:
            if has_gold_docs:
                metrics[f"doc_precision@{k}"] = precision_at_k(doc_keys, gold_docs_for_ir, k)
                metrics[f"doc_recall@{k}"] = recall_at_k(doc_keys, gold_docs_for_ir, k)
                metrics[f"doc_hit_rate@{k}"] = hit_rate_at_k(doc_keys, gold_docs_for_ir, k)
            else:
                metrics[f"doc_precision@{k}"] = None
                metrics[f"doc_recall@{k}"] = None
                metrics[f"doc_hit_rate@{k}"] = None
            if has_gold_chunks:
                metrics[f"chunk_precision@{k}"] = precision_at_k(chunk_keys, gold_chunks_for_ir, k)
                metrics[f"chunk_recall@{k}"] = recall_at_k(chunk_keys, gold_chunks_for_ir, k)
                metrics[f"chunk_hit_rate@{k}"] = hit_rate_at_k(chunk_keys, gold_chunks_for_ir, k)
            else:
                metrics[f"chunk_precision@{k}"] = None
                metrics[f"chunk_recall@{k}"] = None
                metrics[f"chunk_hit_rate@{k}"] = None
            for name in (
                f"doc_precision@{k}", f"doc_recall@{k}", f"doc_hit_rate@{k}",
                f"chunk_precision@{k}", f"chunk_recall@{k}", f"chunk_hit_rate@{k}",
            ):
                metric_buckets[name].append(metrics[name])

        metrics["mrr_doc"] = (
            reciprocal_rank(doc_keys, gold_docs_for_ir) if has_gold_docs else None
        )
        metrics["mrr_chunk"] = (
            reciprocal_rank(chunk_keys, gold_chunks_for_ir) if has_gold_chunks else None
        )
        metric_buckets["mrr_doc"].append(metrics["mrr_doc"])
        metric_buckets["mrr_chunk"].append(metrics["mrr_chunk"])

        # Answer / abstention path (same as /query: cosine vector_score, not RRF)
        if chunks:
            top_similarity = chunks[0].get("vector_score")
            if top_similarity is None:
                top_similarity = chunks[0].get("score") or 0.0
        else:
            top_similarity = 0.0
        confident = float(top_similarity) >= config.CONFIDENCE_THRESHOLD
        generation_ms = None
        answer = None
        cited_doc_keys: set[str] = set()
        cited_chunk_keys: set[str] = set()

        if retrieval_only:
            result["system_decision"] = "retrieval_only"
            result["confident"] = confident
            result["generation_latency_ms"] = None
            result["e2e_latency_ms"] = round(float(retrieval_ms), 3)
            e2e_latencies.append(float(retrieval_ms))
        else:
            try:
                if confident:
                    t1 = time.perf_counter()
                    answer = generate_answer(item["question"], chunks[: max_k])
                    generation_ms = (time.perf_counter() - t1) * 1000.0
                    generation_latencies.append(generation_ms)
                    # Citations correspond to chunks that would be returned when confident
                    for dkey, ckey in zip(doc_keys[:max_k], chunk_keys[:max_k]):
                        if dkey:
                            cited_doc_keys.add(dkey)
                        if ckey:
                            cited_chunk_keys.add(ckey)
                    abstained = normalize_is_abstention(answer)
                    result["system_decision"] = "abstained" if abstained else "answered"
                else:
                    answer = NOT_INDEXED_MESSAGE
                    result["system_decision"] = "abstained"
                    generation_ms = 0.0
                result["confident"] = confident
                result["generated_answer"] = answer
                result["generation_latency_ms"] = (
                    None if generation_ms is None else round(generation_ms, 3)
                )
                e2e = float(retrieval_ms) + float(generation_ms or 0.0)
                result["e2e_latency_ms"] = round(e2e, 3)
                e2e_latencies.append(e2e)
            except Exception as exc:
                abstention_stats["api_failures"] += 1
                result["error"] = f"generation_failure: {type(exc).__name__}: {exc}"
                result["system_decision"] = "api_failure"
                per_question.append(result)
                continue

        # Citation metrics from retrieved supporting chunks used as citations
        if not retrieval_only:
            metrics["citation_precision_doc"] = citation_precision(cited_doc_keys, gold_docs_for_ir)
            metrics["citation_coverage_doc"] = citation_coverage(cited_doc_keys, gold_docs_for_ir)
            metrics["citation_precision_chunk"] = citation_precision(cited_chunk_keys, gold_chunks_for_ir)
            metrics["citation_coverage_chunk"] = citation_coverage(cited_chunk_keys, gold_chunks_for_ir)
            for name in (
                "citation_precision_doc", "citation_coverage_doc",
                "citation_precision_chunk", "citation_coverage_chunk",
            ):
                metric_buckets[name].append(metrics[name])
            metrics["invalid_or_missing_citation"] = (
                1.0 if (result["system_decision"] == "answered" and not cited_doc_keys) else 0.0
            )
            result["citations"] = {
                "document_keys": sorted(cited_doc_keys),
                "chunk_keys": sorted(cited_chunk_keys),
                "note": (
                    "Citation IDs derived from retrieved chunks used for generation; "
                    "QueryResponse.Citation schema does not expose document_id/chunk_id."
                ),
            }

            # Answerability / abstention accounting
            decision = result["system_decision"]
            label = item["answerability"]
            abstention_stats["classification_total"] += 1
            if label == "answerable":
                abstention_stats["answerable_total"] += 1
                contains = answer_contains_expected(answer or "", item.get("expected_answer"))
                result["answer_contains_expected"] = contains
                if decision == "abstained":
                    abstention_stats["answerable_false_abstention"] += 1
                elif decision == "answered" and contains:
                    abstention_stats["answerable_correct_answer"] += 1
                    abstention_stats["classification_correct"] += 1
                elif decision == "answered":
                    # answered but failed objective containment
                    pass
            elif label == "unanswerable":
                abstention_stats["unanswerable_total"] += 1
                if decision == "abstained":
                    abstention_stats["unanswerable_correct_abstention"] += 1
                    abstention_stats["classification_correct"] += 1
                elif decision == "answered":
                    abstention_stats["unanswerable_false_answer"] += 1
            else:  # partial
                abstention_stats["partial_total"] += 1
                # Partial: abstention OR answered both acceptable; count classification
                # correct if system answered or abstained without API failure.
                if decision in ("answered", "abstained"):
                    abstention_stats["classification_correct"] += 1

        result["metrics"] = metrics
        result["wall_ms"] = round((time.perf_counter() - t0) * 1000.0, 3)
        per_question.append(result)

    summary = {
        "num_questions": len(pack["questions"]),
        "num_evaluated": len([r for r in per_question if not r.get("skipped") and not r.get("error")]),
        "num_skipped": abstention_stats["skipped"],
        "num_api_failures": abstention_stats["api_failures"],
        "k_values": list(k_values),
        "aggregates": {name: _mean(vals) for name, vals in metric_buckets.items()},
        "latency": {
            "retrieval_p50_ms": percentile(retrieval_latencies, 50),
            "retrieval_p95_ms": percentile(retrieval_latencies, 95),
            "generation_p50_ms": percentile(generation_latencies, 50) if generation_latencies else None,
            "generation_p95_ms": percentile(generation_latencies, 95) if generation_latencies else None,
            "e2e_p50_ms": percentile(e2e_latencies, 50) if e2e_latencies else None,
            "e2e_p95_ms": percentile(e2e_latencies, 95) if e2e_latencies else None,
        },
        "answerability": abstention_stats,
        "unavailable_metrics": _unavailable_metrics(config.USE_MOCK_LLM, retrieval_only),
        "notes": [
            "Document/chunk Precision@K = (# retrieved top-K items in gold set) / K.",
            "Document/chunk Recall@K = (|gold ∩ top-K|) / |gold|; undefined when gold empty.",
            "Hit Rate@K = 1 if |gold ∩ top-K| > 0 else 0; not the same as Recall@K.",
            "Faithfulness / LLM-as-judge is NOT computed in this deterministic runner.",
        ],
    }

    meta = {
        "timestamp": __import__("app.database", fromlist=["now_iso"]).now_iso(),
        "benchmark_pack": pack["pack"],
        "benchmark_version": pack["version"],
        "corpus_identity": corpus.identity,
        "corpus_label": corpus.label,
        "corpus_is_real_university_corpus": corpus.is_real_university_corpus,
        "corpus_fingerprint": corpus.fingerprint,
        "document_count": len(corpus.document_ids),
        "chunk_count": corpus.chunk_count,
        "excluded_from_corpus": corpus.excluded_present,
        "mock_mode": bool(config.USE_MOCK_LLM),
        "embedding_provider": identity.provider,
        "embedding_model": identity.model_name,
        "embedding_dim": embedding_dim,
        "generation_provider": "mock" if config.USE_MOCK_LLM else "gemini",
        "generation_model": (
            "mock-extractive-template" if config.USE_MOCK_LLM else config.GEMINI_GENERATION_MODEL
        ),
        "top_k": retrieve_k,
        "confidence_threshold": config.CONFIDENCE_THRESHOLD,
        "retrieval_mode": mode,
        "rrf_k": int(config.RRF_K),
        "retrieval_only": retrieval_only,
        "run_id": run_id,
    }

    out = {"run_id": run_id, "meta": meta, "summary": summary, "per_question": per_question}
    if persist:
        paths = save_evaluation_run(
            run_id=run_id,
            meta=meta,
            summary=summary,
            per_question=per_question,
            status="completed",
        )
        out["persistence"] = paths
    return out


def normalize_is_abstention(answer: str) -> bool:
    a = (answer or "").strip()
    if not a:
        return True
    if NOT_INDEXED_MESSAGE.lower() in a.lower():
        return True
    if a.lower().startswith("[mock mode") and "don't have" in a.lower():
        return True
    return False


def _unavailable_metrics(mock_mode: bool, retrieval_only: bool) -> list[str]:
    unavailable = [
        "llm_judge_faithfulness",
        "llm_judge_correctness",
        "true_nli_faithfulness",
    ]
    if mock_mode:
        unavailable.append("genuine_gemini_generation_quality")
    if retrieval_only:
        unavailable.extend([
            "answer_contains_expected",
            "abstention_metrics",
            "citation_metrics",
            "generation_latency",
        ])
    return unavailable


def print_summary(result: dict[str, Any]) -> None:
    meta = result["meta"]
    summary = result["summary"]
    agg = summary["aggregates"]
    print("\n=== Campus Copilot Evaluation v2 ===")
    print(f"run_id           : {result['run_id']}")
    print(f"benchmark        : {meta['benchmark_pack']} @ {meta['benchmark_version']}")
    print(f"corpus           : {meta['corpus_identity']} (real_university={meta['corpus_is_real_university_corpus']})")
    print(f"fingerprint      : {meta['corpus_fingerprint'][:16]}…")
    print(f"docs/chunks      : {meta['document_count']} / {meta['chunk_count']}")
    print(f"excluded kept    : {meta.get('excluded_from_corpus')}")
    print(f"mock_mode        : {meta['mock_mode']}")
    print(f"embedder         : {meta['embedding_provider']}/{meta['embedding_model']} dim={meta['embedding_dim']}")
    print(f"generator        : {meta['generation_provider']}/{meta['generation_model']}")
    print(f"questions        : {summary['num_questions']} (skipped={summary['num_skipped']}, api_failures={summary['num_api_failures']})")
    print("--- retrieval aggregates ---")
    for key in sorted(agg):
        if key.startswith("doc_") or key.startswith("chunk_") or key.startswith("mrr_"):
            print(f"  {key:24s} {agg[key]}")
    print("--- latency (ms) ---")
    for k, v in summary["latency"].items():
        print(f"  {k:24s} {v}")
    print("--- answerability ---")
    for k, v in summary["answerability"].items():
        print(f"  {k:32s} {v}")
    print("--- unavailable ---")
    for u in summary["unavailable_metrics"]:
        print(f"  - {u}")
    if result.get("persistence"):
        print(f"saved            : {result['persistence'].get('json_path')}")
    print()
