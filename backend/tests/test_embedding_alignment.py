"""Startup / health embedding identity alignment diagnostics."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))


class EmbeddingAlignmentTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self._tmpdir.name, "align.db")
        os.environ["DATABASE_PATH"] = self.db_path
        os.environ["USE_MOCK_LLM"] = "true"
        os.environ["GEMINI_API_KEY"] = "your_gemini_api_key_here"
        os.environ["JWT_SECRET"] = "test-secret-align"

        import importlib
        import app.config as config
        import app.database as database
        import app.embedding_validation as ev

        importlib.reload(config)
        importlib.reload(database)
        importlib.reload(ev)
        database.DATABASE_PATH = self.db_path
        config.DATABASE_PATH = self.db_path
        database.init_db()
        self.config = config
        self.database = database
        self.ev = ev

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_empty_index_is_aligned(self):
        diagnosis = self.ev.diagnose_embedding_alignment()
        self.assertTrue(diagnosis["aligned"])
        self.assertEqual(diagnosis["query_mode"], "mock")
        self.assertIsNone(diagnosis["index_label"])
        self.ev.assert_startup_embedding_alignment()

    def test_mismatch_raises_at_startup(self):
        with self.database.get_conn() as conn:
            self.database.upsert_embedding_index_meta(
                conn,
                provider="gemini",
                model_name="models/gemini-embedding-001",
                vector_dim=3072,
                mode="real",
            )
        diagnosis = self.ev.diagnose_embedding_alignment()
        self.assertFalse(diagnosis["aligned"])
        self.assertIn("does not match", diagnosis["mismatch_reason"])
        with self.assertRaises(self.ev.EmbeddingCompatibilityError):
            self.ev.assert_startup_embedding_alignment()

    def test_matching_real_index_ok(self):
        os.environ["USE_MOCK_LLM"] = "false"
        os.environ["GEMINI_API_KEY"] = "not-a-real-key-but-not-placeholder"
        import importlib
        importlib.reload(self.config)
        importlib.reload(self.ev)
        self.config.DATABASE_PATH = self.db_path
        self.database.DATABASE_PATH = self.db_path

        with self.database.get_conn() as conn:
            self.database.upsert_embedding_index_meta(
                conn,
                provider="gemini",
                model_name=self.config.GEMINI_EMBEDDING_MODEL,
                vector_dim=3072,
                mode="real",
            )
        diagnosis = self.ev.diagnose_embedding_alignment()
        self.assertTrue(diagnosis["aligned"])
        self.assertEqual(diagnosis["query_mode"], "real")
        self.ev.assert_startup_embedding_alignment()

    def test_placeholder_process_key_yields_to_dotenv_real_key(self):
        """Stale shell placeholder must not force mock when .env has a real key."""
        os.environ["USE_MOCK_LLM"] = "false"
        os.environ["GEMINI_API_KEY"] = "your_gemini_api_key_here"
        import importlib
        importlib.reload(self.config)
        # If backend/.env has a real key, config should adopt it and leave mock off.
        if self.config.GEMINI_API_KEY != "your_gemini_api_key_here":
            self.assertFalse(self.config.USE_MOCK_LLM)
            self.assertIsNotNone(self.config.ENV_FILE_OVERRIDE_WARNING)
            self.assertIn("placeholder", self.config.ENV_FILE_OVERRIDE_WARNING.lower())
        else:
            self.skipTest("backend/.env has no real GEMINI_API_KEY to recover")


if __name__ == "__main__":
    unittest.main()
