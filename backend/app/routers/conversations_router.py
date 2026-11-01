"""
Per-user chat conversation persistence.

All routes require authentication and scope rows to the JWT user id.
Admins may use the same endpoints for their own chats; they cannot
access another user's conversations.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth import get_current_user
from app.database import dumps, get_conn, loads, now_iso
from app.schemas import (
    ConversationCreate,
    ConversationDetail,
    ConversationMessageCreate,
    ConversationMessageOut,
    ConversationOut,
    ConversationRename,
)

router = APIRouter(prefix="/conversations", tags=["conversations"])


def _get_owned_conversation(conn, conversation_id: int, user_id: int):
    row = conn.execute(
        "SELECT * FROM conversations WHERE id = ? AND user_id = ?",
        (conversation_id, user_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
    return row


def _message_out(row) -> ConversationMessageOut:
    from app.schemas import Citation

    raw = loads(row["citations_json"]) or []
    citations = []
    for item in raw:
        if isinstance(item, dict):
            citations.append(Citation(**item))
    return ConversationMessageOut(
        id=row["id"],
        conversation_id=row["conversation_id"],
        role=row["role"],
        content=row["content"],
        citations=citations,
        query_log_id=row["query_log_id"],
        confident=None if row["confident"] is None else bool(row["confident"]),
        created_at=row["created_at"],
    )


@router.get("", response_model=list[ConversationOut])
def list_conversations(
    q: str | None = Query(None, description="Search titles and message content"),
    user: dict = Depends(get_current_user),
):
    with get_conn() as conn:
        if q and q.strip():
            term = f"%{q.strip().lower()}%"
            rows = conn.execute(
                """SELECT DISTINCT c.*
                   FROM conversations c
                   LEFT JOIN conversation_messages m ON m.conversation_id = c.id
                   WHERE c.user_id = ?
                     AND (LOWER(c.title) LIKE ? OR LOWER(m.content) LIKE ?)
                   ORDER BY c.updated_at DESC
                   LIMIT 50""",
                (user["id"], term, term),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT * FROM conversations
                   WHERE user_id = ?
                   ORDER BY updated_at DESC
                   LIMIT 50""",
                (user["id"],),
            ).fetchall()
    return [ConversationOut(**dict(r)) for r in rows]


@router.post("", response_model=ConversationOut, status_code=status.HTTP_201_CREATED)
def create_conversation(req: ConversationCreate, user: dict = Depends(get_current_user)):
    title = (req.title or "New chat").strip() or "New chat"
    if len(title) > 120:
        title = title[:117] + "…"
    ts = now_iso()
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO conversations (user_id, title, created_at, updated_at)
               VALUES (?, ?, ?, ?)""",
            (user["id"], title, ts, ts),
        )
        row = conn.execute(
            "SELECT * FROM conversations WHERE id = ?",
            (cur.lastrowid,),
        ).fetchone()
    return ConversationOut(**dict(row))


@router.get("/{conversation_id}", response_model=ConversationDetail)
def get_conversation(conversation_id: int, user: dict = Depends(get_current_user)):
    with get_conn() as conn:
        conv = _get_owned_conversation(conn, conversation_id, user["id"])
        messages = conn.execute(
            """SELECT * FROM conversation_messages
               WHERE conversation_id = ?
               ORDER BY id ASC""",
            (conversation_id,),
        ).fetchall()
    return ConversationDetail(
        **dict(conv),
        messages=[_message_out(m) for m in messages],
    )


@router.patch("/{conversation_id}", response_model=ConversationOut)
def rename_conversation(
    conversation_id: int,
    req: ConversationRename,
    user: dict = Depends(get_current_user),
):
    title = req.title.strip()
    if not title:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Title cannot be empty")
    if len(title) > 120:
        title = title[:117] + "…"
    with get_conn() as conn:
        _get_owned_conversation(conn, conversation_id, user["id"])
        conn.execute(
            "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ? AND user_id = ?",
            (title, now_iso(), conversation_id, user["id"]),
        )
        row = conn.execute(
            "SELECT * FROM conversations WHERE id = ?",
            (conversation_id,),
        ).fetchone()
    return ConversationOut(**dict(row))


@router.post(
    "/{conversation_id}/messages",
    response_model=ConversationMessageOut,
    status_code=status.HTTP_201_CREATED,
)
def append_message(
    conversation_id: int,
    req: ConversationMessageCreate,
    user: dict = Depends(get_current_user),
):
    if req.role not in ("user", "assistant"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "role must be user or assistant")
    content = (req.content or "").strip()
    if not content:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "content cannot be empty")

    if req.citations is None:
        citations_json = None
    else:
        citations_json = dumps([
            c.model_dump() if hasattr(c, "model_dump") else c
            for c in req.citations
        ])
    confident_int = None if req.confident is None else (1 if req.confident else 0)
    ts = now_iso()

    with get_conn() as conn:
        _get_owned_conversation(conn, conversation_id, user["id"])
        cur = conn.execute(
            """INSERT INTO conversation_messages
               (conversation_id, role, content, citations_json, query_log_id, confident, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                conversation_id,
                req.role,
                content,
                citations_json,
                req.query_log_id,
                confident_int,
                ts,
            ),
        )
        # Bump conversation activity; set title from first user question if still default.
        conv = conn.execute(
            "SELECT title FROM conversations WHERE id = ?",
            (conversation_id,),
        ).fetchone()
        new_title = conv["title"]
        if req.role == "user" and (not new_title or new_title == "New chat"):
            new_title = content if len(content) <= 80 else content[:77] + "…"
        conn.execute(
            "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
            (new_title, ts, conversation_id),
        )
        row = conn.execute(
            "SELECT * FROM conversation_messages WHERE id = ?",
            (cur.lastrowid,),
        ).fetchone()
    return _message_out(row)


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conversation(conversation_id: int, user: dict = Depends(get_current_user)):
    """
    Permanently delete one conversation owned by the JWT user.

    Ownership is verified from the authenticated token only — never from a
    client-supplied user id. Unknown or other-users' ids return the same
    privacy-preserving 404. Messages cascade via FK; query_logs, feedback,
    evaluation runs, documents and embeddings are intentionally left intact.
    """
    with get_conn() as conn:
        # Raises 404 for missing or non-owned conversations (no data leak).
        _get_owned_conversation(conn, conversation_id, user["id"])
        cur = conn.execute(
            "DELETE FROM conversations WHERE id = ? AND user_id = ?",
            (conversation_id, user["id"]),
        )
        if cur.rowcount != 1:
            # Race / unexpected — do not report another user's data.
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
    return None


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
def clear_conversations(user: dict = Depends(get_current_user)):
    """Delete all conversations for the authenticated user only."""
    with get_conn() as conn:
        conn.execute("DELETE FROM conversations WHERE user_id = ?", (user["id"],))
    return None
