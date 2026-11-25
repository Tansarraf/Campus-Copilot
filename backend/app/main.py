import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import config
from app.database import init_db
from app.embedding_validation import (
    EmbeddingCompatibilityError,
    diagnose_embedding_alignment,
    assert_startup_embedding_alignment,
)
from app.notification_service import start_deadline_reminder_scheduler
from app.routers import (
    admin_router,
    auth_router,
    calendar_router,
    conversations_router,
    documents_router,
    evaluation_admin_router,
    feedback_router,
    notifications_router,
    query_router,
)
from app.routers.students_admin_router import register_public_setup, router as students_admin_router

logger = logging.getLogger("campus_copilot")

app = FastAPI(
    title="Campus Copilot",
    description="Retrieval-Augmented Knowledge Assistant for University Information & Circulars",
    version="0.1.0",
)


def _cors_origins() -> list[str]:
    """
    Same-origin Nginx deployments do not need broad CORS.
    Set CORS_ORIGINS to a comma-separated list when the static UI is served
    from a different origin during local non-Docker development.
    """
    raw = (os.getenv("CORS_ORIGINS") or "").strip()
    if not raw or raw == "*":
        return ["*"]
    return [o.strip() for o in raw.split(",") if o.strip()]


_origins = _cors_origins()
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    # Browsers reject allow_credentials=True with wildcard origins.
    allow_credentials=("*" not in _origins),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    init_db()
    try:
        diagnosis = assert_startup_embedding_alignment()
        logger.info(
            "Embedding OK: %s (index=%s)",
            diagnosis["query_label"],
            diagnosis["index_label"] or "unset",
        )
    except EmbeddingCompatibilityError as exc:
        # Fail startup so /query cannot run under the wrong embedder.
        logger.error("Embedding index mismatch at startup: %s", exc)
        raise
    try:
        start_deadline_reminder_scheduler()
    except Exception:  # noqa: BLE001 — notifications must not block boot
        logger.exception("Deadline reminder scheduler failed to start")


@app.get("/health")
def health():
    try:
        embedding = diagnose_embedding_alignment()
    except Exception as exc:  # noqa: BLE001 — health must stay reachable
        embedding = {"error": str(exc), "aligned": False}
    return {
        "status": "ok" if embedding.get("aligned", False) else "degraded",
        "mock_mode": config.USE_MOCK_LLM,
        "embedding": embedding,
        "env_file_override_warning": getattr(config, "ENV_FILE_OVERRIDE_WARNING", None),
    }


register_public_setup(auth_router.router)
app.include_router(auth_router.router)
app.include_router(query_router.router)
app.include_router(conversations_router.router)
app.include_router(documents_router.router)
app.include_router(feedback_router.router)
app.include_router(admin_router.router)
app.include_router(evaluation_admin_router.router)
app.include_router(calendar_router.student_router)
app.include_router(calendar_router.admin_router)
app.include_router(notifications_router.router)
app.include_router(students_admin_router)

