"""
Real Gemini connectivity smoke test (embedding + generation).

Does NOT print API keys. Exit 0 on success.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import importlib

import app.config as config

importlib.reload(config)

from app.embeddings import clear_embedder_cache, embed_text
from app.generation import clear_chat_cache, generate_answer


def main() -> int:
    print("=== Gemini smoke test ===")
    print(f"USE_MOCK_LLM          : {config.USE_MOCK_LLM}")
    print(f"GEMINI_EMBEDDING_MODEL: {config.GEMINI_EMBEDDING_MODEL}")
    print(f"GEMINI_GENERATION_MODEL: {config.GEMINI_GENERATION_MODEL}")
    key_ok = config.GEMINI_API_KEY not in ("", "your_gemini_api_key_here")
    print(f"API key configured    : {key_ok}")
    if config.USE_MOCK_LLM:
        print("FAIL: still in mock mode (placeholder key or USE_MOCK_LLM=true)")
        return 1
    if not key_ok:
        print("FAIL: API key not configured")
        return 1

    clear_embedder_cache()
    clear_chat_cache()

    print("--- embedding ---")
    try:
        vec = embed_text("Campus Copilot embedding smoke test", task_type="retrieval_document")
        print(f"OK dim={len(vec)} dtype={vec.dtype} finite={bool(vec.size and (vec == vec).all())}")
    except Exception as exc:
        print(f"FAIL embedding: {type(exc).__name__}: {exc}")
        return 1

    print("--- generation ---")
    try:
        chunks = [{
            "title": "Smoke Test Circular",
            "section_label": "General",
            "page_number": None,
            "text": (
                "The campus library opens at 8:00 AM on weekdays for the smoke-test "
                "circular. Late returns incur a fine of Rs. 2 per day."
            ),
        }]
        answer = generate_answer("When does the library open on weekdays?", chunks)
        preview = (answer or "").replace("\n", " ")[:180]
        print(f"OK answer_len={len(answer or '')} preview={preview!r}")
        if not (answer or "").strip():
            print("FAIL: empty generation")
            return 1
    except Exception as exc:
        print(f"FAIL generation: {type(exc).__name__}: {exc}")
        return 1

    print("=== smoke test passed ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
