from fastapi import APIRouter, Depends, HTTPException, status

from app.auth import get_current_user
from app.database import get_conn, now_iso
from app.schemas import FeedbackRequest

router = APIRouter(prefix="/feedback", tags=["feedback"])


@router.post("")
def submit_feedback(req: FeedbackRequest, user: dict = Depends(get_current_user)):
    if req.rating not in (1, -1):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "rating must be 1 or -1")
    with get_conn() as conn:
        log = conn.execute("SELECT id FROM query_logs WHERE id = ?", (req.query_log_id,)).fetchone()
        if log is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "query_log_id not found")
        conn.execute(
            "INSERT INTO feedback (query_log_id, rating, comment, created_at) VALUES (?, ?, ?, ?)",
            (req.query_log_id, req.rating, req.comment, now_iso()),
        )
    return {"status": "ok"}
