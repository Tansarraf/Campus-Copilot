"""Admin-only student directory and account provisioning."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth import require_admin, validate_password_strength
from app.schemas import (
    PasswordSetupRequest,
    StudentCreateRequest,
    StudentCreateResponse,
    StudentFilterOptions,
    StudentListResponse,
    StudentOut,
    StudentStatusRequest,
    StudentUpdateRequest,
)
from app.student_admin import (
    complete_password_setup,
    create_student,
    filter_options,
    list_students,
    reset_student_password,
    set_student_status,
    update_student,
)

router = APIRouter(prefix="/admin/students", tags=["admin-students"])


@router.get("", response_model=StudentListResponse)
def directory(
    q: str | None = Query(None),
    course: str | None = Query(None),
    academic_year: str | None = Query(None),
    account_status: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    admin: dict = Depends(require_admin),
):
    return list_students(
        q=q,
        course=course,
        academic_year=academic_year,
        account_status=account_status,
        page=page,
        page_size=page_size,
    )


@router.get("/filters", response_model=StudentFilterOptions)
def filters(admin: dict = Depends(require_admin)):
    return filter_options()


@router.post("", response_model=StudentCreateResponse, status_code=status.HTTP_201_CREATED)
def create(body: StudentCreateRequest, admin: dict = Depends(require_admin)):
    return create_student(body.model_dump(), admin_id=int(admin["id"]))


@router.patch("/{user_id}", response_model=StudentOut)
def edit(user_id: int, body: StudentUpdateRequest, admin: dict = Depends(require_admin)):
    return update_student(user_id, body.model_dump(exclude_unset=True), admin_id=int(admin["id"]))


@router.post("/{user_id}/status", response_model=StudentOut)
def status_change(user_id: int, body: StudentStatusRequest, admin: dict = Depends(require_admin)):
    return set_student_status(user_id, body.account_status, admin_id=int(admin["id"]))


@router.post("/{user_id}/password-reset", response_model=StudentCreateResponse)
def password_reset(user_id: int, admin: dict = Depends(require_admin)):
    return reset_student_password(user_id, admin_id=int(admin["id"]))


def register_public_setup(auth_router: APIRouter) -> None:
    """Attach the unauthenticated setup endpoint onto the existing auth router."""

    @auth_router.post("/setup-password")
    def setup_password(body: PasswordSetupRequest):
        if body.new_password != body.confirm_password:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "New passwords do not match.")
        validate_password_strength(body.new_password)
        complete_password_setup(token=body.token, new_password=body.new_password)
        return {"message": "Password saved. You can sign in with your enrollment number."}
