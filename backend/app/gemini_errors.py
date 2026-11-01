"""Shared Gemini API error classification (never expose secrets)."""
from __future__ import annotations


class GeminiAPIError(RuntimeError):
    """Raised when a real Gemini embedding/generation call fails."""

    def __init__(self, message: str, *, status_hint: str | None = None):
        super().__init__(message)
        self.status_hint = status_hint or "upstream_error"


def sanitize_gemini_error(exc: BaseException) -> GeminiAPIError:
    """
    Convert SDK/HTTP exceptions into safe operator-facing messages.
    Does not include API keys or raw response bodies that may leak secrets.
    """
    name = type(exc).__name__
    raw = str(exc) or name
    lower = raw.lower()

    if any(tok in lower for tok in ("api key", "api_key", "permission", "401", "unauthenticated", "invalid_argument")):
        return GeminiAPIError(
            "Gemini authentication failed. Check that GEMINI_API_KEY is valid "
            "and that USE_MOCK_LLM=false is intentional.",
            status_hint="auth",
        )
    if any(tok in lower for tok in ("quota", "429", "resource exhausted", "rate")):
        return GeminiAPIError(
            "Gemini rate limit or quota exhausted. Retry later or check project quotas.",
            status_hint="quota",
        )
    if any(tok in lower for tok in ("not found", "404", "is not found", "unsupported", "does not exist")):
        return GeminiAPIError(
            f"Configured Gemini model is unavailable ({name}). "
            "Update GEMINI_EMBEDDING_MODEL / GEMINI_GENERATION_MODEL to a supported ID.",
            status_hint="model_unavailable",
        )
    if any(tok in lower for tok in ("timeout", "timed out", "deadline")):
        return GeminiAPIError(
            "Gemini request timed out. Retry the operation.",
            status_hint="timeout",
        )
    if any(tok in lower for tok in ("connection", "network", "unreachable", "dns")):
        return GeminiAPIError(
            "Network failure contacting Gemini. Check connectivity and retry.",
            status_hint="network",
        )
    # Keep type name only — avoid dumping potentially large/sensitive payloads
    return GeminiAPIError(
        f"Gemini API call failed ({name}). See server logs for details.",
        status_hint="upstream_error",
    )
