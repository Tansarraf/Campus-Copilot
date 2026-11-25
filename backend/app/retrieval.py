"""
SQLite-backed retrieval: Gemini embeddings (cosine) + optional FTS5 keyword
search, fused with Reciprocal Rank Fusion (RRF).

Deliberately not FAISS/Chroma/pgvector: at MVP scale loading embeddings into
one numpy array is simple and fast enough. Keyword search uses SQLite FTS5
bm25 with no extra Gemini calls.
"""
from __future__ import annotations

import time
from typing import Any

import numpy as np
from sklearn.metrics.pairwise import cosine_similarity

from app import config
from app.database import (
    get_conn,
    embedding_to_blob,
    blob_to_embedding,
    get_embedding_index_meta,
    upsert_embedding_index_meta,
)
from app.embedding_validation import (
    EmbeddingCompatibilityError,
    EmbeddingValidationError,
    assert_query_dim_matches,
    assert_query_identity_matches_index,
    assert_uniform_chunk_dims,
    configured_embedding_identity,
    validate_embedding_vector,
)
from app.embeddings import embed_text, embed_batch
from app.fts_index import ensure_chunks_fts, keyword_search_chunk_ids
from app.reembed import assert_ingestion_compatible_with_index


def index_document_chunks(document_id: int, chunks: list[dict]) -> int:
    """Embeds and stores chunks for one document. Returns count stored."""
    if not chunks:
        return 0
    texts = [c["text"] for c in chunks]
    vectors = embed_batch(texts, task_type="retrieval_document")
    if not vectors:
        return 0
    first = validate_embedding_vector(vectors[0])
    dim0 = int(first.shape[0])
    prepared = [first] + [
        validate_embedding_vector(v, expected_dim=dim0) for v in vectors[1:]
    ]
    identity = configured_embedding_identity()

    with get_conn() as conn:
        try:
            assert_ingestion_compatible_with_index(conn, dim0, identity)
        except EmbeddingValidationError as exc:
            raise EmbeddingCompatibilityError(str(exc)) from exc

        # Keep FTS in sync even if migrate was skipped on an older process.
        ensure_chunks_fts(conn)

        meta_before = get_embedding_index_meta(conn)
        chunk_count_before = conn.execute("SELECT COUNT(*) AS n FROM chunks").fetchone()["n"]

        for c, vec in zip(chunks, prepared):
            conn.execute(
                """INSERT INTO chunks
                   (document_id, chunk_index, section_label, page_number, text, embedding, embedding_dim)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    document_id, c["chunk_index"], c.get("section_label"),
                    c.get("page_number"), c["text"],
                    embedding_to_blob(vec), len(vec),
                ),
            )

        if chunk_count_before == 0 and meta_before is None:
            upsert_embedding_index_meta(
                conn,
                provider=identity.provider,
                model_name=identity.model_name,
                vector_dim=dim0,
                mode=identity.mode,
            )
    return len(chunks)


def _load_all_chunks(
    category: str | None = None,
    department: str | None = None,
    document_ids: list[int] | None = None,
    *,
    include_superseded: bool = True,
):
    query = """
        SELECT c.id, c.document_id, c.chunk_index, c.section_label, c.page_number, c.text,
               c.embedding, c.embedding_dim, d.title, d.category, d.department,
               d.filename, d.academic_year, d.document_status, d.supersedes_document_id
        FROM chunks c JOIN documents d ON c.document_id = d.id
        WHERE 1=1
    """
    params: list = []
    if category:
        query += " AND d.category = ?"
        params.append(category)
    if department:
        query += " AND d.department = ?"
        params.append(department)
    if not include_superseded:
        query += " AND COALESCE(d.document_status, 'active') != 'superseded'"
    if document_ids is not None:
        if not document_ids:
            with get_conn() as conn:
                meta = get_embedding_index_meta(conn)
            return [], meta
        placeholders = ",".join("?" for _ in document_ids)
        query += f" AND d.id IN ({placeholders})"
        params.extend(int(i) for i in document_ids)
    with get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
        meta = get_embedding_index_meta(conn)
    return rows, meta


def _load_chunks_by_ids(chunk_ids: list[int]):
    if not chunk_ids:
        return []
    placeholders = ",".join("?" for _ in chunk_ids)
    with get_conn() as conn:
        rows = conn.execute(
            f"""SELECT c.id, c.document_id, c.chunk_index, c.section_label, c.page_number, c.text,
                      c.embedding, c.embedding_dim, d.title, d.category, d.department,
                      d.filename, d.academic_year, d.document_status, d.supersedes_document_id
               FROM chunks c JOIN documents d ON c.document_id = d.id
               WHERE c.id IN ({placeholders})""",
            [int(i) for i in chunk_ids],
        ).fetchall()
    by_id = {int(r["id"]): r for r in rows}
    return [by_id[i] for i in chunk_ids if i in by_id]


def _metadata_score_adjustment(query: str, row) -> float:
    """Soft boost/penalty; never hard-filters out semantic matches."""
    from app.document_metadata import infer_query_category_boost

    adj = 0.0
    status = (row["document_status"] if "document_status" in row.keys() else None) or "active"
    if status == "superseded":
        q = (query or "").lower()
        if not any(w in q for w in ("previous", "old", "superseded", "historical", "earlier", "former")):
            adj -= 0.04
    hinted = infer_query_category_boost(query)
    if hinted and row["category"] and hinted.lower() in str(row["category"]).lower():
        adj += 0.03
    year = row["academic_year"] if "academic_year" in row.keys() else None
    if year:
        for token in str(year).replace("–", "-").split("-"):
            token = token.strip()
            if len(token) >= 2 and token in (query or ""):
                adj += 0.015
                break
    return adj


def _row_to_result(r, *, score: float, vector_score: float | None, keyword_rank: int | None) -> dict:
    return {
        "chunk_id": r["id"],
        "document_id": r["document_id"],
        "chunk_index": r["chunk_index"],
        "filename": r["filename"],
        "title": r["title"],
        "category": r["category"],
        "department": r["department"],
        "section_label": r["section_label"],
        "page_number": r["page_number"],
        "text": r["text"],
        "score": float(score),
        "vector_score": None if vector_score is None else float(vector_score),
        "keyword_rank": keyword_rank,
        "document_status": (r["document_status"] if "document_status" in r.keys() else None) or "active",
    }


def _vector_rank(
    query: str,
    rows,
    meta,
    *,
    top_k: int,
    query_vec: np.ndarray | None = None,
) -> tuple[list[dict], np.ndarray]:
    """Return vector-ranked results and the query embedding used."""
    if not rows:
        empty = np.zeros((0,), dtype=np.float32)
        return [], empty if query_vec is None else query_vec

    stored_dim = assert_uniform_chunk_dims(rows)
    assert_query_identity_matches_index(meta, stored_dim)
    if query_vec is None:
        query_raw = embed_text(query, task_type="retrieval_query")
        query_vec = assert_query_dim_matches(query_raw, stored_dim).reshape(1, -1)
    else:
        query_vec = assert_query_dim_matches(query_vec.reshape(-1), stored_dim).reshape(1, -1)

    matrix = np.stack([blob_to_embedding(r["embedding"], r["embedding_dim"]) for r in rows])
    if matrix.shape[1] != stored_dim:
        raise EmbeddingCompatibilityError(
            f"Loaded embedding matrix width {matrix.shape[1]} != declared dim {stored_dim}."
        )

    sims = cosine_similarity(query_vec, matrix)[0]
    adjusted = np.array(
        [float(sims[i]) + _metadata_score_adjustment(query, rows[int(i)]) for i in range(len(rows))],
        dtype=float,
    )
    ranked_idx = np.argsort(-adjusted)[: min(len(rows), top_k)]

    results = []
    for rank, i in enumerate(ranked_idx, start=1):
        r = rows[int(i)]
        results.append(
            _row_to_result(
                r,
                score=float(adjusted[int(i)]),
                vector_score=float(adjusted[int(i)]),
                keyword_rank=None,
            )
        )
        results[-1]["_vector_rank"] = rank
    return results, query_vec


def _keyword_rank(
    query: str,
    *,
    top_k: int,
    category: str | None,
    department: str | None,
    document_ids: list[int] | None,
    include_superseded: bool,
) -> list[dict]:
    with get_conn() as conn:
        ensure_chunks_fts(conn)
        ids = keyword_search_chunk_ids(
            conn,
            query,
            limit=top_k,
            category=category,
            department=department,
            document_ids=document_ids,
            include_superseded=include_superseded,
        )
    rows = _load_chunks_by_ids(ids)
    # Soft superseded penalty: demote unless the query asks for history.
    q = (query or "").lower()
    historical = any(
        w in q for w in ("previous", "old", "superseded", "historical", "earlier", "former")
    )
    if not historical:
        active = []
        superseded = []
        for r in rows:
            status = (r["document_status"] if "document_status" in r.keys() else None) or "active"
            (superseded if status == "superseded" else active).append(r)
        rows = active + superseded

    results = []
    for rank, r in enumerate(rows, start=1):
        # bm25 is not comparable to cosine; expose rank via keyword_rank only.
        results.append(
            _row_to_result(
                r,
                score=float(1.0 / rank),
                vector_score=None,
                keyword_rank=rank,
            )
        )
        results[-1]["_keyword_rank"] = rank
    return results


def reciprocal_rank_fusion(
    ranked_lists: list[list[dict]],
    *,
    rrf_k: int,
    top_k: int,
) -> list[dict]:
    """
    Fuse ranked lists with RRF. Deduplicates by chunk_id.
    Final `score` is the RRF score; vector_score/keyword_rank are preserved.
    """
    fused: dict[int, dict[str, Any]] = {}
    for result_list in ranked_lists:
        for rank, item in enumerate(result_list, start=1):
            cid = int(item["chunk_id"])
            contrib = 1.0 / (float(rrf_k) + float(rank))
            if cid not in fused:
                fused[cid] = {
                    **{k: v for k, v in item.items() if not str(k).startswith("_")},
                    "score": 0.0,
                    "vector_score": item.get("vector_score"),
                    "keyword_rank": item.get("keyword_rank"),
                }
            fused[cid]["score"] = float(fused[cid]["score"]) + contrib
            if item.get("vector_score") is not None:
                fused[cid]["vector_score"] = item["vector_score"]
            if item.get("keyword_rank") is not None:
                fused[cid]["keyword_rank"] = item["keyword_rank"]

    ordered = sorted(
        fused.values(),
        key=lambda x: (-float(x["score"]), -float(x.get("vector_score") or -1.0), int(x["chunk_id"])),
    )
    return ordered[:top_k]


def similarity_search(
    query: str,
    top_k: int | None = None,
    category: str | None = None,
    department: str | None = None,
    document_ids: list[int] | None = None,
    include_superseded: bool = True,
    retrieval_mode: str | None = None,
    attach_vector_scores: bool = True,
) -> tuple[list[dict], float]:
    """
    Returns (ranked chunk dicts, latency_ms).

    Modes:
      - vector: cosine only (legacy behaviour)
      - keyword: FTS5 bm25 only
      - hybrid: RRF of vector + keyword (default)

    Abstention should use `vector_score` (cosine), not RRF `score`.
    Set attach_vector_scores=False for keyword-only IR benchmarks (no Gemini call).
    """
    top_k = top_k or config.TOP_K
    mode = (retrieval_mode or config.RETRIEVAL_MODE or "hybrid").strip().lower()
    if mode not in ("hybrid", "vector", "keyword"):
        mode = "hybrid"
    pool = max(int(config.HYBRID_CANDIDATE_POOL), top_k)
    start = time.perf_counter()

    if mode == "keyword":
        kw = _keyword_rank(
            query,
            top_k=pool,
            category=category,
            department=department,
            document_ids=document_ids,
            include_superseded=include_superseded,
        )
        # Score keyword hits with the query embedding so confidence stays cosine-based.
        if kw and attach_vector_scores:
            rows, meta = _load_all_chunks(
                category, department, document_ids=document_ids, include_superseded=include_superseded
            )
            rows_by_id = {int(r["id"]): r for r in rows}
            if rows:
                stored_dim = assert_uniform_chunk_dims(rows)
                assert_query_identity_matches_index(meta, stored_dim)
                qvec = assert_query_dim_matches(
                    embed_text(query, task_type="retrieval_query"), stored_dim
                ).reshape(1, -1)
                for item in kw:
                    row = rows_by_id.get(int(item["chunk_id"]))
                    if row is None:
                        continue
                    vec = blob_to_embedding(row["embedding"], row["embedding_dim"]).reshape(1, -1)
                    sim = float(cosine_similarity(qvec, vec)[0][0])
                    item["vector_score"] = sim + _metadata_score_adjustment(query, row)
                kw.sort(
                    key=lambda x: (
                        int(x.get("keyword_rank") or 10**9),
                        -float(x.get("vector_score") or -1.0),
                    )
                )
        results = kw[:top_k]
        for r in results:
            r.pop("_keyword_rank", None)
            r.pop("_vector_rank", None)
        return results, (time.perf_counter() - start) * 1000

    rows, meta = _load_all_chunks(
        category,
        department,
        document_ids=document_ids,
        include_superseded=include_superseded,
    )
    if not rows:
        return [], (time.perf_counter() - start) * 1000

    vector_results, query_vec = _vector_rank(query, rows, meta, top_k=pool)
    if mode == "vector":
        results = vector_results[:top_k]
        for r in results:
            r.pop("_vector_rank", None)
            r.pop("_keyword_rank", None)
        return results, (time.perf_counter() - start) * 1000

    # hybrid
    keyword_results = _keyword_rank(
        query,
        top_k=pool,
        category=category,
        department=department,
        document_ids=document_ids,
        include_superseded=include_superseded,
    )
    rows_by_id = {int(r["id"]): r for r in rows}
    # Give keyword-only hits a cosine score for abstention / telemetry.
    for item in keyword_results:
        if item.get("vector_score") is not None:
            continue
        row = rows_by_id.get(int(item["chunk_id"]))
        if row is None:
            continue
        vec = blob_to_embedding(row["embedding"], row["embedding_dim"]).reshape(1, -1)
        sim = float(cosine_similarity(query_vec.reshape(1, -1), vec)[0][0])
        item["vector_score"] = sim + _metadata_score_adjustment(query, row)

    if not keyword_results:
        results = vector_results[:top_k]
    elif not vector_results:
        results = keyword_results[:top_k]
    else:
        results = reciprocal_rank_fusion(
            [vector_results, keyword_results],
            rrf_k=int(config.RRF_K),
            top_k=top_k,
        )

    for r in results:
        r.pop("_vector_rank", None)
        r.pop("_keyword_rank", None)
    return results, (time.perf_counter() - start) * 1000
