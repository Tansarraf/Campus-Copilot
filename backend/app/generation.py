"""
Generation layer: builds a grounded prompt from retrieved chunks + recent
conversation turns and calls Gemini (via LangChain's ChatGoogleGenerativeAI)
to produce a cited answer. Falls back to a templated extractive answer in
mock mode only. Real-mode failures never fall back to mock.
"""
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache

from app import config
from app.gemini_errors import GeminiAPIError, sanitize_gemini_error

NOT_INDEXED_MESSAGE = "I don't have that information in the indexed documents yet."

SYSTEM_PROMPT = """You are Campus Copilot, a university information assistant.

Rules you must follow strictly:
1. Answer ONLY using the information in the provided CONTEXT. Do not use
   outside knowledge, even if you know the answer.
2. Do not invent university policies, fees, dates, deadlines, contacts,
   eligibility rules, or other institutional facts that are not present in
   CONTEXT.
3. Every factual claim must be followed by a citation in the form
   [Document Title, Section/Page]. Use the exact titles and section/page
   labels given in the CONTEXT. Never fabricate citations.
4. Preserve important conditions, exceptions, eligibility caveats, and dates
   from the source text. Do not simplify them away.
5. If the CONTEXT does not contain enough information to answer the
   question, say clearly: "I don't have that information in the indexed
   documents yet." Do not guess or present assumptions as official policy.
6. Clearly distinguish facts supported by CONTEXT from information that is
   missing.
7. Keep answers concise and clear. Use short paragraphs or a short list only
   if it genuinely improves clarity.
8. If recent conversation turns are provided, use them only to resolve
   follow-up references (e.g. "what about for MTech students?"); the answer
   must still be grounded in CONTEXT.
"""


def _format_context(chunks: list[dict]) -> str:
    parts = []
    for i, c in enumerate(chunks, 1):
        loc = c.get("section_label") or (f"page {c['page_number']}" if c.get("page_number") else "")
        loc = f", {loc}" if loc else ""
        parts.append(f"[Source {i}: {c['title']}{loc}]\n{c['text']}")
    return "\n\n".join(parts)


def _format_history(history: list[dict]) -> str:
    if not history:
        return ""
    lines = []
    for turn in history[-4:]:  # keep last 4 turns for cheap multi-turn context
        role = "User" if turn.get("role") == "user" else "Assistant"
        lines.append(f"{role}: {turn.get('content', '')}")
    return "\n".join(lines)


@lru_cache(maxsize=1)
def _get_gemini_chat():
    from langchain_google_genai import ChatGoogleGenerativeAI
    if config.USE_MOCK_LLM:
        raise GeminiAPIError(
            "Refusing to create a Gemini chat client while USE_MOCK_LLM is active.",
            status_hint="config",
        )
    if config.GEMINI_API_KEY in ("", "your_gemini_api_key_here"):
        raise GeminiAPIError(
            "GEMINI_API_KEY is missing or still the placeholder value.",
            status_hint="auth",
        )
    return ChatGoogleGenerativeAI(
        model=config.GEMINI_GENERATION_MODEL,
        google_api_key=config.GEMINI_API_KEY,
        temperature=0.2,
        timeout=config.GEMINI_GENERATION_TIMEOUT_SECONDS,
        max_retries=1,
    )


def clear_chat_cache() -> None:
    """Call after config reload / tests so cached clients are recreated."""
    _get_gemini_chat.cache_clear()


def _mock_answer(question: str, chunks: list[dict]) -> str:
    if not chunks:
        return f"{NOT_INDEXED_MESSAGE} [MOCK MODE]"
    top = chunks[0]
    loc = top.get("section_label") or (f"page {top['page_number']}" if top.get("page_number") else "")
    loc = f", {loc}" if loc else ""
    snippet = top["text"].strip().replace("\n", " ")[:300]
    return (
        f"[MOCK MODE - no Gemini API key configured, this is a templated "
        f"extractive stand-in, not a real generated answer]\n\n"
        f"Based on the closest matching indexed passage: {snippet}... "
        f"[{top['title']}{loc}]"
    )


def generate_answer(question: str, chunks: list[dict], history: list[dict] | None = None) -> str:
    if config.USE_MOCK_LLM:
        return _mock_answer(question, chunks)

    context = _format_context(chunks) if chunks else "(no relevant documents found)"
    history_text = _format_history(history or [])
    history_block = f"\nRECENT CONVERSATION:\n{history_text}\n" if history_text else ""

    user_prompt = (
        f"CONTEXT:\n{context}\n{history_block}\n"
        f"QUESTION: {question}\n\n"
        f"Answer following all the rules above."
    )

    messages = [
        ("system", SYSTEM_PROMPT),
        ("human", user_prompt),
    ]
    timeout = max(1, int(config.GEMINI_GENERATION_TIMEOUT_SECONDS))
    try:
        chat = _get_gemini_chat()
        pool = ThreadPoolExecutor(max_workers=1)
        try:
            future = pool.submit(chat.invoke, messages)
            try:
                response = future.result(timeout=timeout)
            except TimeoutError as exc:
                future.cancel()
                raise GeminiAPIError(
                    "Gemini request timed out. Retry the operation.",
                    status_hint="timeout",
                ) from exc
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
    except GeminiAPIError:
        raise
    except Exception as exc:
        raise sanitize_gemini_error(exc) from exc

    content = getattr(response, "content", None)
    if content is None or (isinstance(content, str) and not content.strip()):
        raise GeminiAPIError(
            "Gemini returned an empty or malformed generation response.",
            status_hint="malformed_response",
        )
    if isinstance(content, list):
        # Some LangChain versions return content blocks
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and "text" in block:
                parts.append(str(block["text"]))
            else:
                parts.append(str(block))
        content = "\n".join(parts).strip()
    return str(content).strip()
