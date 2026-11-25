"""Pydantic request/response models."""
import re

from pydantic import BaseModel, Field, field_validator

from app.student_validation import is_valid_enrollment_number, normalize_enrollment_number

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class RegisterRequest(BaseModel):
    """Legacy self-registration body. Endpoint is disabled (admin-provisioned accounts)."""
    username: str
    password: str
    full_name: str
    department: str | None = None
    role: str = "student"


class LoginRequest(BaseModel):
    """Generic username/password login (legacy + admin username)."""
    username: str
    password: str


class AdminLoginRequest(BaseModel):
    username: str
    password: str


class StudentLoginRequest(BaseModel):
    enrollment_number: str
    password: str

    @field_validator("enrollment_number")
    @classmethod
    def enrollment_must_be_11_digits(cls, value: str) -> str:
        return normalize_enrollment_number(value)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    full_name: str
    first_name: str | None = None
    enrollment_number: str | None = None


class ProfileResponse(BaseModel):
    id: int
    username: str | None = None
    role: str
    full_name: str
    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None
    email_verified: bool = False
    account_status: str
    department: str | None = None
    enrollment_number: str | None = None
    course: str | None = None
    academic_year: str | None = None
    current_semester: int | None = None
    is_demo: bool = False
    profile_complete: bool = True
    missing_fields: list[str] = Field(default_factory=list)
    editable_fields: list[str] = Field(default_factory=list)
    required_fields: list[str] = Field(default_factory=list)


class ChangePasswordRequest(BaseModel):
    """Authenticated password change. Target account is taken from the JWT only."""
    current_password: str
    new_password: str
    confirm_password: str


class ChangePasswordResponse(BaseModel):
    message: str


class ProfileUpdateRequest(BaseModel):
    """Student self-service profile updates. Protected fields are ignored server-side."""
    email: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    academic_year: str | None = None
    current_semester: int | None = None

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            return None
        if not _EMAIL_RE.match(value):
            raise ValueError("Invalid email address")
        return value

    @field_validator("first_name", "last_name", "academic_year")
    @classmethod
    def strip_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @field_validator("current_semester")
    @classmethod
    def validate_semester(cls, value: int | None) -> int | None:
        if value is None:
            return None
        if value < 1 or value > 12:
            raise ValueError("current_semester must be between 1 and 12")
        return value


class ConversationTurn(BaseModel):
    role: str  # 'user' | 'assistant'
    content: str


class QueryRequest(BaseModel):
    question: str
    history: list[ConversationTurn] = Field(default_factory=list)
    category: str | None = None
    department: str | None = None


class Citation(BaseModel):
    title: str
    section_label: str | None = None
    page_number: int | None = None
    score: float
    text_preview: str


class QueryResponse(BaseModel):
    query_log_id: int
    answer: str
    citations: list[Citation]
    confident: bool
    latency_ms: float


class FeedbackRequest(BaseModel):
    query_log_id: int
    rating: int  # 1 (helpful) or -1 (not helpful)
    comment: str | None = None


class DocumentOut(BaseModel):
    id: int
    filename: str
    title: str
    category: str
    department: str | None
    academic_year: str | None
    file_type: str
    uploaded_at: str
    chunk_count: int
    document_type: str | None = None
    publication_date: str | None = None
    effective_date: str | None = None
    expiry_date: str | None = None
    extraction_method: str | None = None
    processing_status: str | None = None
    document_status: str | None = "active"
    supersedes_document_id: int | None = None
    updated_at: str | None = None
    has_original_file: bool = False


class DocumentListResponse(BaseModel):
    items: list[DocumentOut]
    total: int
    page: int
    page_size: int
    total_pages: int


class DocumentCategoriesResponse(BaseModel):
    categories: list[str]
    has_uncategorized: bool = False


class UploadMetadata(BaseModel):
    title: str
    category: str
    department: str | None = None
    academic_year: str | None = None


class ConversationCreate(BaseModel):
    title: str | None = None


class ConversationRename(BaseModel):
    title: str


class ConversationOut(BaseModel):
    id: int
    title: str
    created_at: str
    updated_at: str


class ConversationMessageCreate(BaseModel):
    role: str
    content: str
    citations: list[Citation] | None = None
    query_log_id: int | None = None
    confident: bool | None = None


class ConversationMessageOut(BaseModel):
    id: int
    conversation_id: int
    role: str
    content: str
    citations: list[Citation] = Field(default_factory=list)
    query_log_id: int | None = None
    confident: bool | None = None
    created_at: str


class ConversationDetail(ConversationOut):
    messages: list[ConversationMessageOut] = Field(default_factory=list)


def assert_enrollment_format(value: str) -> str:
    if not is_valid_enrollment_number(value):
        raise ValueError("Enrollment number must be exactly 11 digits")
    return normalize_enrollment_number(value)


class AcademicEventOut(BaseModel):
    id: int
    title: str
    description: str | None = None
    category: str
    start_datetime: str
    end_datetime: str | None = None
    location: str | None = None
    is_official: bool = False
    publication_status: str
    source_document_id: int | None = None
    created_by: int | None = None
    created_at: str
    updated_at: str
    seed_key: str | None = None
    is_demo: bool = False


class AcademicEventCreate(BaseModel):
    title: str
    description: str | None = None
    category: str
    start_datetime: str
    end_datetime: str | None = None
    location: str | None = None
    is_official: bool = True
    publication_status: str = "published"
    source_document_id: int | None = None

    @field_validator("title")
    @classmethod
    def title_required(cls, value: str) -> str:
        value = (value or "").strip()
        if not value:
            raise ValueError("title is required")
        return value


class AcademicEventUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    category: str | None = None
    start_datetime: str | None = None
    end_datetime: str | None = None
    location: str | None = None
    is_official: bool | None = None
    publication_status: str | None = None
    source_document_id: int | None = None


class NotificationOut(BaseModel):
    id: int
    title: str
    message: str
    notification_type: str
    related_document_id: int | None = None
    related_event_id: int | None = None
    created_at: str
    read_at: str | None = None
    is_read: bool = False


class NotificationListResponse(BaseModel):
    items: list[NotificationOut]
    total: int
    unread_count: int
    limit: int
    offset: int


class NotificationUnreadCountResponse(BaseModel):
    unread_count: int


class MarkReadResponse(BaseModel):
    status: str
    id: int | None = None
    marked: int | None = None


class StudentCreateRequest(BaseModel):
    full_name: str
    enrollment_number: str
    email: str
    course: str
    academic_year: str
    current_semester: int = Field(ge=1, le=12)

    @field_validator("enrollment_number")
    @classmethod
    def enrollment_digits(cls, value: str) -> str:
        return normalize_enrollment_number(value)

    @field_validator("email")
    @classmethod
    def email_shape(cls, value: str) -> str:
        value = (value or "").strip().lower()
        if not _EMAIL_RE.match(value):
            raise ValueError("A valid email address is required")
        return value

    @field_validator("full_name", "course", "academic_year")
    @classmethod
    def required_text(cls, value: str) -> str:
        value = (value or "").strip()
        if not value:
            raise ValueError("This field is required")
        return value


class StudentUpdateRequest(BaseModel):
    full_name: str | None = None
    email: str | None = None
    course: str | None = None
    academic_year: str | None = None
    current_semester: int | None = Field(default=None, ge=1, le=12)

    @field_validator("email")
    @classmethod
    def email_shape(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip().lower()
        if not _EMAIL_RE.match(value):
            raise ValueError("A valid email address is required")
        return value

    @field_validator("full_name", "course", "academic_year")
    @classmethod
    def optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("This field cannot be empty")
        return value


class StudentStatusRequest(BaseModel):
    account_status: str

    @field_validator("account_status")
    @classmethod
    def allowed_status(cls, value: str) -> str:
        value = (value or "").strip().lower()
        if value not in ("active", "disabled"):
            raise ValueError("Status must be active or disabled")
        return value


class StudentOut(BaseModel):
    id: int
    full_name: str
    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None
    enrollment_number: str
    course: str
    department: str | None = None
    academic_year: str
    current_semester: int
    account_status: str
    created_at: str


class StudentListResponse(BaseModel):
    items: list[StudentOut]
    total: int
    page: int
    page_size: int
    total_pages: int
    active_count: int
    student_count: int


class StudentFilterOptions(BaseModel):
    courses: list[str]
    academic_years: list[str]
    statuses: list[str]


class SetupCredential(BaseModel):
    token: str
    expires_at: str
    purpose: str
    delivery: str


class StudentCreateResponse(BaseModel):
    student: StudentOut
    setup: SetupCredential


class PasswordSetupRequest(BaseModel):
    token: str
    new_password: str
    confirm_password: str

