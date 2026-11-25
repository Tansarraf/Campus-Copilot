"""Student in-app notification APIs (own records only)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth import require_student
from app.notification_service import (
    list_notifications_for_user,
    mark_all_notifications_read,
    mark_notification_read,
    unread_count_for_user,
)
from app.schemas import (
    MarkReadResponse,
    NotificationListResponse,
    NotificationOut,
    NotificationUnreadCountResponse,
)

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=NotificationListResponse)
def list_my_notifications(
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
    unread_only: bool = Query(False),
    user: dict = Depends(require_student),
):
    items, total, unread = list_notifications_for_user(
        int(user["id"]),
        limit=limit,
        offset=offset,
        unread_only=unread_only,
    )
    return NotificationListResponse(
        items=[NotificationOut(**row) for row in items],
        total=total,
        unread_count=unread,
        limit=limit,
        offset=offset,
    )


@router.get("/unread-count", response_model=NotificationUnreadCountResponse)
def my_unread_count(user: dict = Depends(require_student)):
    return NotificationUnreadCountResponse(unread_count=unread_count_for_user(int(user["id"])))


@router.post("/{notification_id}/read", response_model=MarkReadResponse)
def mark_one_read(notification_id: int, user: dict = Depends(require_student)):
    ok = mark_notification_read(int(user["id"]), int(notification_id))
    if not ok:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Notification not found")
    return MarkReadResponse(status="read", id=notification_id)


@router.post("/read-all", response_model=MarkReadResponse)
def mark_all_read(user: dict = Depends(require_student)):
    n = mark_all_notifications_read(int(user["id"]))
    return MarkReadResponse(status="ok", marked=n)
