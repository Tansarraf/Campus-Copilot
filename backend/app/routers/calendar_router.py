"""Student calendar read APIs + admin calendar management APIs."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth import get_current_user, require_admin
from app import calendar_service as svc
from app.schemas import (
    AcademicEventCreate,
    AcademicEventOut,
    AcademicEventUpdate,
)

student_router = APIRouter(prefix="/calendar", tags=["calendar"])
admin_router = APIRouter(prefix="/admin/calendar", tags=["admin-calendar"])


def _http_value_error(exc: ValueError) -> HTTPException:
    return HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc))


@student_router.get("/events", response_model=list[AcademicEventOut])
def list_published_events(
    user: dict = Depends(get_current_user),
    category: str | None = None,
    from_date: str | None = Query(None, description="YYYY-MM-DD"),
    to_date: str | None = Query(None, description="YYYY-MM-DD"),
):
    """Any authenticated user may read published calendar events (shared globally)."""
    return svc.list_events(
        published_only=True,
        category=category,
        from_date=from_date,
        to_date=to_date,
    )


@student_router.get("/events/{event_id}", response_model=AcademicEventOut)
def get_published_event(event_id: int, user: dict = Depends(get_current_user)):
    event = svc.get_event(event_id, published_only=True)
    if not event:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Event not found")
    return event


@student_router.get("/categories")
def list_categories(user: dict = Depends(get_current_user)):
    return {"categories": list(svc.EVENT_CATEGORIES)}


@admin_router.get("/events", response_model=list[AcademicEventOut])
def admin_list_events(
    admin: dict = Depends(require_admin),
    category: str | None = None,
    status_filter: str | None = Query(None, alias="status"),
    include_archived: bool = True,
):
    events = svc.list_events(
        published_only=False,
        category=category,
        include_archived=include_archived,
    )
    if status_filter:
        events = [e for e in events if e["publication_status"] == status_filter]
    return events


@admin_router.post("/events", response_model=AcademicEventOut, status_code=status.HTTP_201_CREATED)
def admin_create_event(body: AcademicEventCreate, admin: dict = Depends(require_admin)):
    try:
        return svc.create_event(body.model_dump(), admin_id=int(admin["id"]))
    except ValueError as exc:
        raise _http_value_error(exc) from exc


@admin_router.patch("/events/{event_id}", response_model=AcademicEventOut)
def admin_update_event(
    event_id: int,
    body: AcademicEventUpdate,
    admin: dict = Depends(require_admin),
):
    try:
        updated = svc.update_event(
            event_id,
            body.model_dump(exclude_unset=True),
        )
    except ValueError as exc:
        raise _http_value_error(exc) from exc
    if not updated:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Event not found")
    return updated


@admin_router.delete("/events/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
def admin_delete_event(event_id: int, admin: dict = Depends(require_admin)):
    if not svc.delete_event(event_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Event not found")
    return None
