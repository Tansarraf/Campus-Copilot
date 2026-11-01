"""
Custom SQLite-backed vector store + scikit-learn cosine-similarity search.

Deliberately not FAISS/Chroma/pgvector: at MVP scale (a few hundred to a
few thousand chunks) loading all embeddings into one numpy array and
calling sklearn's cosine_similarity is simple, dependency-light, fully
transparent, and fast enough (single-digit milliseconds). This is the
retriever LangChain's ChatGoogleGenerativeAI-based generation step is
plugged into.
"""
import time
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity

from app import config  # TOP_K
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
            # Surface as compatibility error so /documents/upload and callers
            # can map to a clear failure without writing mixed vectors.
            raise EmbeddingCompatibilityError(str(exc)) from exc

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

        # Only establish metadata when this is the first content in an empty index.
        # Never silently overwrite an existing meta row during ordinary ingestion.
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


def _metadata_score_adjustment(query: str, row) -> float:
    """Soft boost/penalty; never hard-filters out semantic matches."""
    from app.document_metadata import infer_query_category_boost

    adj = 0.0
    status = (row["document_status"] if "document_status" in row.keys() else None) or "active"
    if status == "superseded":
        # Prefer active replacements for current-policy questions unless the
        # user explicitly asks for history / previous / superseded.
        q = (query or "").lower()
        if not any(w in q for w in ("previous", "old", "superseded", "historical", "earlier", "former")):
            adj -= 0.04
    hinted = infer_query_category_boost(query)
    if hinted and row["category"] and hinted.lower() in str(row["category"]).lower():
        adj += 0.03
    # Mild academic-year hint when the query mentions a year present on the doc.
    year = row["academic_year"] if "academic_year" in row.keys() else None
    if year:
        for token in str(year).replace("–", "-").split("-"):
            token = token.strip()
            if len(token) >= 2 and token in (query or ""):
                adj += 0.015
                break
    return adj


def similarity_search(
    query: str,
    top_k: int | None = None,
    category: str | None = None,
    department: str | None = None,
    document_ids: list[int] | None = None,
    include_superseded: bool = True,
) -> tuple[list[dict], float]:
    """Returns (ranked chunk dicts, latency_ms)."""
    top_k = top_k or config.TOP_K
    start = time.perf_counter()

    rows, meta = _load_all_chunks(
        category,
        department,
        document_ids=document_ids,
        include_superseded=include_superseded,
    )
    if not rows:
        return [], (time.perf_counter() - start) * 1000

    stored_dim = assert_uniform_chunk_dims(rows)
    assert_query_identity_matches_index(meta, stored_dim)
    query_raw = embed_text(query, task_type="retrieval_query")
    query_vec = assert_query_dim_matches(query_raw, stored_dim).reshape(1, -1)
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
    # Pull a wider candidate pool then trim so soft boosts can reorder near-ties.
    pool = min(len(rows), max(top_k * 3, top_k))
    ranked_idx = np.argsort(-adjusted)[:pool][:top_k]

    results = []
    for i in ranked_idx:
        r = rows[int(i)]
        results.append({
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
            "score": float(adjusted[int(i)]),
            "document_status": (r["document_status"] if "document_status" in r.keys() else None) or "active",
        })
    latency_ms = (time.perf_counter() - start) * 1000
    return results, latency_ms
