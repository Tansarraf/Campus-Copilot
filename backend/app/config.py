"""
Central configuration for Campus Copilot.

Everything is read from environment variables (loaded from a .env file if
present) so the same code runs locally, in a demo, or in a grading VM
without edits.
"""
import os
from dotenv import dotenv_values, load_dotenv

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # backend/
_ENV_PATH = os.path.join(BASE_DIR, ".env")
# load_dotenv does NOT override variables already set in the process environment.
# A leftover shell `USE_MOCK_LLM=true` (e.g. from earlier tests) therefore wins
# over `USE_MOCK_LLM=false` in backend/.env — check ENV_FILE_OVERRIDE_WARNING.
load_dotenv(_ENV_PATH)


def _bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def _parse_bool_text(val: str | None, default: bool = False) -> bool:
    if val is None or not str(val).strip():
        return default
    return str(val).strip().lower() in ("1", "true", "yes", "on")


_file_env = dotenv_values(_ENV_PATH)
ENV_FILE_OVERRIDE_WARNING: str | None = None

# Process-env values win over .env via load_dotenv(override=False). A common
# footgun: tests leave GEMINI_API_KEY=your_gemini_api_key_here in the shell,
# which blocks the real key in backend/.env and forces mock embeddings.
_PLACEHOLDER_KEY = "your_gemini_api_key_here"
_raw_key = os.getenv("GEMINI_API_KEY", _PLACEHOLDER_KEY)
_file_key = (_file_env.get("GEMINI_API_KEY") or "").strip()
if _raw_key in ("", _PLACEHOLDER_KEY) and _file_key not in ("", _PLACEHOLDER_KEY):
    GEMINI_API_KEY = _file_key
    ENV_FILE_OVERRIDE_WARNING = (
        "Process environment GEMINI_API_KEY was missing/placeholder and blocked "
        "the real key in backend/.env; using the .env key so query embeddings can "
        "match the stored Gemini index. Clear the shell GEMINI_API_KEY variable "
        "to avoid this override warning."
    )
else:
    GEMINI_API_KEY = _raw_key

# Mock mode kicks in automatically if no real key is configured, OR if
# explicitly requested via USE_MOCK_LLM=true. This is what lets the whole
# pipeline be smoke-tested and demoed with zero API cost / no key at all.
_placeholder_key = GEMINI_API_KEY in ("", _PLACEHOLDER_KEY)
USE_MOCK_LLM = _bool("USE_MOCK_LLM", False) or _placeholder_key

# Detect stale process-env USE_MOCK_LLM that disagrees with backend/.env.
_file_mock = _file_env.get("USE_MOCK_LLM")
if _file_mock is not None:
    file_wants_mock = _parse_bool_text(_file_mock, False)
    process_raw = os.environ.get("USE_MOCK_LLM")
    if process_raw is not None and _parse_bool_text(process_raw, False) != file_wants_mock:
        mock_warning = (
            f"Process environment USE_MOCK_LLM={process_raw!r} overrides "
            f"backend/.env USE_MOCK_LLM={_file_mock!r}. "
            "Clear the shell variable (Remove-Item Env:USE_MOCK_LLM) and restart "
            "the backend so query embeddings match the stored index."
        )
        ENV_FILE_OVERRIDE_WARNING = (
            f"{ENV_FILE_OVERRIDE_WARNING} {mock_warning}"
            if ENV_FILE_OVERRIDE_WARNING
            else mock_warning
        )

# Defaults match currently listed Google AI models for this SDK generation.
# text-embedding-004 / gemini-2.0-flash may be unavailable on newer API keys.
GEMINI_EMBEDDING_MODEL = os.getenv("GEMINI_EMBEDDING_MODEL", "models/gemini-embedding-001")
GEMINI_GENERATION_MODEL = os.getenv("GEMINI_GENERATION_MODEL", "gemini-3.8-flash")
# Keep well below the frontend Nginx proxy_read_timeout so quota/hangs
# become a 503 instead of a silent 504.
GEMINI_GENERATION_TIMEOUT_SECONDS = int(os.getenv("GEMINI_GENERATION_TIMEOUT_SECONDS", "45"))

JWT_SECRET = os.getenv("JWT_SECRET", "dev-secret-change-me")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "720"))

DATABASE_PATH = os.getenv("DATABASE_PATH", os.path.join(BASE_DIR, "campus_copilot.db"))

# Persistent original uploads (Docker-friendly absolute/relative path under backend/).
DOCUMENTS_DIR = os.getenv(
    "DOCUMENTS_DIR",
    os.path.join(BASE_DIR, "uploaded_documents"),
)

CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "900"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "150"))
TOP_K = int(os.getenv("TOP_K", "4"))

# Chunks whose best similarity score falls below this are treated as
# "not confidently covered" -> the assistant says so instead of guessing,
# and the admin dashboard surfaces them as informational gaps.
# Always applied to vector (cosine) scores — never to raw RRF fusion ranks.
CONFIDENCE_THRESHOLD = float(os.getenv("CONFIDENCE_THRESHOLD", "0.45"))

# Retrieval fusion: hybrid (default) | vector | keyword
_RETRIEVAL_MODE_RAW = (os.getenv("RETRIEVAL_MODE") or "hybrid").strip().lower()
RETRIEVAL_MODE = (
    _RETRIEVAL_MODE_RAW
    if _RETRIEVAL_MODE_RAW in ("hybrid", "vector", "keyword")
    else "hybrid"
)
# Reciprocal Rank Fusion constant (standard default 60).
RRF_K = int(os.getenv("RRF_K", "60"))
# Per-channel candidate pool before RRF merge.
HYBRID_CANDIDATE_POOL = int(os.getenv("HYBRID_CANDIDATE_POOL", "20"))
