"""
Admin insights dashboard data: aggregate query logs + feedback into stats an
administrator can use to spot frequently-asked questions and informational
gaps (queries the indexed corpus doesn't confidently cover).
"""
from fastapi import APIRouter, Depends

from app import config
from app.auth import require_admin
from app.database import get_conn

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/insights")
def insights(admin: dict = Depends(require_admin)):
    with get_conn() as conn:
        total_queries = conn.execute("SELECT COUNT(*) c FROM query_logs").fetchone()["c"]

        avg_latency = conn.execute("SELECT AVG(latency_ms) a FROM query_logs").fetchone()["a"] or 0

        feedback_row = conn.execute(
            """SELECT
                 SUM(CASE WHEN rating = 1 THEN 1 ELSE 0 END) AS up,
                 SUM(CASE WHEN rating = -1 THEN 1 ELSE 0 END) AS down
               FROM feedback"""
        ).fetchone()

        gaps = conn.execute(
            """SELECT query_text, top_similarity, created_at FROM query_logs
               WHERE top_similarity < ? ORDER BY created_at DESC LIMIT 20""",
            (config.CONFIDENCE_THRESHOLD,),
        ).fetchall()

        # Frequently-asked questions: grouped by a normalized (lowercased,
        # trimmed, whitespace-collapsed) form of the query text. This is
        # exact/near-duplicate grouping, not semantic clustering -- two
        # differently-worded questions about the same topic are counted
        # separately. Good enough to surface literal repeat questions
        # ("what is the hostel curfew" asked by many students) cheaply.
        faq = conn.execute(
            """SELECT
                 TRIM(LOWER(query_text)) AS normalized_query,
                 COUNT(*) AS occurrences,
                 MAX(query_text) AS example_query_text,
                 MAX(created_at) AS last_asked_at
               FROM query_logs
               GROUP BY TRIM(LOWER(query_text))
               HAVING COUNT(*) > 1
               ORDER BY occurrences DESC, last_asked_at DESC
               LIMIT 10"""
        ).fetchall()

        recent = conn.execute(
            """SELECT query_text, top_similarity, latency_ms, created_at FROM query_logs
               ORDER BY created_at DESC LIMIT 20"""
        ).fetchall()

        by_category = conn.execute(
            """SELECT category, COUNT(*) AS doc_count,
                      (SELECT COUNT(*) FROM chunks c WHERE c.document_id IN
                        (SELECT id FROM documents d2 WHERE d2.category = documents.category)) AS chunk_count
               FROM documents GROUP BY category"""
        ).fetchall()

    return {
        "total_queries": total_queries,
        "avg_latency_ms": round(avg_latency, 1),
        "feedback_up": feedback_row["up"] or 0,
        "feedback_down": feedback_row["down"] or 0,
        "informational_gaps": [dict(r) for r in gaps],
        "frequent_questions": [dict(r) for r in faq],
        "recent_queries": [dict(r) for r in recent],
        "documents_by_category": [dict(r) for r in by_category],
        "confidence_threshold": config.CONFIDENCE_THRESHOLD,
    }
