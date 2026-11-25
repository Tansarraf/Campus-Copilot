from fastapi import APIRouter, Depends, HTTPException, status

from app import config
from app.auth import get_current_user
from app.database import get_conn, now_iso, dumps
from app.embedding_validation import EmbeddingCompatibilityError
from app.gemini_errors import GeminiAPIError
from app.generation import NOT_INDEXED_MESSAGE, generate_answer
from app.retrieval import similarity_search
from app.schemas import Citation, QueryRequest, QueryResponse

router = APIRouter(prefix="/query", tags=["query"])


@router.post("", response_model=QueryResponse)
def ask(req: QueryRequest, user: dict = Depends(get_current_user)):
    try:
        chunks, latency_ms = similarity_search(
            req.question, category=req.category, department=req.department,
        )
    except EmbeddingCompatibilityError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except GeminiAPIError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    # Abstention uses cosine vector_score, never raw RRF fusion ranks.
    if chunks:
        top = chunks[0]
        top_similarity = top.get("vector_score")
        if top_similarity is None:
            top_similarity = top.get("score") or 0.0
    else:
        top_similarity = 0.0
    confident = float(top_similarity) >= config.CONFIDENCE_THRESHOLD

    if confident:
        history = [t.model_dump() for t in req.history]
        try:
            answer = generate_answer(req.question, chunks, history=history)
        except GeminiAPIError as exc:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=str(exc),
            ) from exc
    else:
        # Below the confidence threshold: skip the generation call entirely
        # rather than asking the model to recognise a weak retrieval on its
        # own. Cheaper (no LLM call) and more reliable (no chance the model
        # answers from its own knowledge instead of admitting the gap).
        answer = NOT_INDEXED_MESSAGE
        chunks = []

    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO query_logs
               (user_id, query_text, answer_text, top_similarity, retrieved_chunk_ids, latency_ms, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (user["id"], req.question, answer, top_similarity,
             dumps([c["chunk_id"] for c in chunks]), latency_ms, now_iso()),
        )
        query_log_id = cur.lastrowid

    citations = [
        Citation(
            title=c["title"], section_label=c["section_label"], page_number=c["page_number"],
            score=round(c["score"], 4), text_preview=(c["text"][:220] + ("…" if len(c["text"]) > 220 else "")),
        )
        for c in chunks
    ]
    return QueryResponse(
        query_log_id=query_log_id, answer=answer, citations=citations,
        confident=confident, latency_ms=round(latency_ms, 1),
    )
