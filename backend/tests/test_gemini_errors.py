"""Unit tests for Gemini error sanitization and real-mode no-fallback behavior."""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))


class GeminiErrorTests(unittest.TestCase):
    def test_sanitize_auth_and_quota(self):
        from app.gemini_errors import sanitize_gemini_error

        auth = sanitize_gemini_error(RuntimeError("401 Unauthenticated invalid API key"))
        self.assertEqual(auth.status_hint, "auth")
        self.assertNotIn("API_KEY=", str(auth))

        quota = sanitize_gemini_error(RuntimeError("429 RESOURCE_EXHAUSTED quota exceeded"))
        self.assertEqual(quota.status_hint, "quota")

        missing = sanitize_gemini_error(RuntimeError("404 model is not found"))
        self.assertEqual(missing.status_hint, "model_unavailable")

    def test_real_mode_embed_does_not_fallback_to_mock(self):
        os.environ["USE_MOCK_LLM"] = "false"
        os.environ["GEMINI_API_KEY"] = "not-a-real-key-for-unit-test"
        import importlib
        import app.config as config
        import app.embeddings as embeddings

        importlib.reload(config)
        importlib.reload(embeddings)
        embeddings.clear_embedder_cache()

        with patch.object(embeddings, "_get_gemini_embedder", side_effect=RuntimeError("boom network")):
            from app.gemini_errors import GeminiAPIError

            with self.assertRaises(GeminiAPIError):
                embeddings.embed_text("hello", task_type="retrieval_document")

    def test_mock_mode_still_uses_mock_vectors(self):
        os.environ["USE_MOCK_LLM"] = "true"
        os.environ["GEMINI_API_KEY"] = "your_gemini_api_key_here"
        import importlib
        import app.config as config
        import app.embeddings as embeddings

        importlib.reload(config)
        importlib.reload(embeddings)
        vec = embeddings.embed_text("hello")
        self.assertEqual(len(vec), embeddings.MOCK_DIM)


if __name__ == "__main__":
    unittest.main()
