"""
Embedding layer: wraps Gemini's embedding model via LangChain's
GoogleGenerativeAIEmbeddings, with a deterministic mock fallback so the rest
of the pipeline can be built and tested without an API key.

Mock vectors are NOT semantically meaningful. Real retrieval quality requires
GEMINI_API_KEY with USE_MOCK_LLM=false. Real-mode failures never fall back to mock.
"""
import hashlib
import numpy as np
from functools import lru_cache

from app import config
from app.gemini_errors import GeminiAPIError, sanitize_gemini_error

MOCK_DIM = 128


def _mock_embedding(text: str) -> np.ndarray:
    seed = int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:8], 16)
    rng = np.random.default_rng(seed)
    vec = rng.normal(size=MOCK_DIM)
    return vec / (np.linalg.norm(vec) + 1e-8)


@lru_cache(maxsize=1)
def _get_gemini_embedder():
    from langchain_google_genai import GoogleGenerativeAIEmbeddings
    if config.USE_MOCK_LLM:
        raise GeminiAPIError(
            "Refusing to create a Gemini embedder while USE_MOCK_LLM is active.",
            status_hint="config",
        )
    if config.GEMINI_API_KEY in ("", "your_gemini_api_key_here"):
        raise GeminiAPIError(
            "GEMINI_API_KEY is missing or still the placeholder value.",
            status_hint="auth",
        )
    return GoogleGenerativeAIEmbeddings(
        model=config.GEMINI_EMBEDDING_MODEL,
        google_api_key=config.GEMINI_API_KEY,
    )


def clear_embedder_cache() -> None:
    """Call after config reload / tests so cached clients are recreated."""
    _get_gemini_embedder.cache_clear()


def embed_text(text: str, task_type: str = "retrieval_document") -> np.ndarray:
    """Embed a single piece of text. task_type follows Gemini's
    'retrieval_document' (for indexed chunks) vs 'retrieval_query' (for the
    user's question) distinction, which measurably improves retrieval."""
    if config.USE_MOCK_LLM:
        return _mock_embedding(text)
    try:
        embedder = _get_gemini_embedder()
        vec = (
            embedder.embed_query(text)
            if task_type == "retrieval_query"
            else embedder.embed_documents([text])[0]
        )
    except GeminiAPIError:
        raise
    except Exception as exc:
        raise sanitize_gemini_error(exc) from exc
    return np.asarray(vec, dtype=np.float32)


def embed_batch(texts: list[str], task_type: str = "retrieval_document") -> list[np.ndarray]:
    if config.USE_MOCK_LLM:
        return [_mock_embedding(t) for t in texts]
    if not texts:
        return []
    try:
        embedder = _get_gemini_embedder()
        vecs = embedder.embed_documents(texts)
    except GeminiAPIError:
        raise
    except Exception as exc:
        raise sanitize_gemini_error(exc) from exc
    return [np.asarray(v, dtype=np.float32) for v in vecs]
