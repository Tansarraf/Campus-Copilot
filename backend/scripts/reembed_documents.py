"""
Safe, resumable re-embedding of existing Campus Copilot chunk rows.

Updates ONLY chunks.embedding + chunks.embedding_dim. Never deletes documents
or chunks, never changes document IDs / filenames / metadata.

Write-mode re-embedding is FULL-CORPUS ONLY (index consistency).
`--document-id` is allowed with `--dry-run` for inspection only.

Examples (run from backend/):

  # Inspect / validate only — no DB writes, no backup
  python scripts/reembed_documents.py --dry-run

  # Inspect one document (dry-run only)
  python scripts/reembed_documents.py --dry-run --document-id 3

  # Future real migration (AFTER configuring GEMINI_API_KEY and USE_MOCK_LLM=false).
  # Stop the backend first. Explicit opt-in required when changing mock↔real.
  python scripts/reembed_documents.py --allow-index-replacement

This script does NOT flip mock mode or edit .env.
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import config
from app.reembed import run_reembed


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Re-embed existing document chunks in place (no document deletion). "
            "Write mode always processes the FULL corpus; --document-id is "
            "dry-run inspection only."
        ),
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate and validate embeddings but do not modify the database.",
    )
    p.add_argument(
        "--document-id",
        type=int,
        default=None,
        help=(
            "Limit inspection to a single documents.id. Allowed ONLY with "
            "--dry-run. Write mode rejects this flag."
        ),
    )
    p.add_argument(
        "--db",
        default=None,
        help="Override SQLite path (default: configured DATABASE_PATH).",
    )
    p.add_argument(
        "--no-backup",
        action="store_true",
        help="Skip the verified SQLite online backup before writing (not recommended).",
    )
    p.add_argument(
        "--allow-index-replacement",
        action="store_true",
        help=(
            "Explicitly allow replacing an existing index when the configured "
            "embedder mode/provider/model differs from the stored index "
            "(e.g. mock→real or real→mock). Still creates a backup and uses a "
            "single transaction."
        ),
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    print("Campus Copilot — re-embed documents")
    print(f"  database : {args.db or config.DATABASE_PATH}")
    print(f"  dry_run  : {args.dry_run}")
    print(f"  document : {args.document_id if args.document_id is not None else 'ALL'}")
    print(f"  allow_index_replacement: {args.allow_index_replacement}")
    print(f"  mock_mode: {config.USE_MOCK_LLM}")
    print(
        f"  embedder : "
        f"{'mock/mock-hash-v1' if config.USE_MOCK_LLM else 'gemini/' + config.GEMINI_EMBEDDING_MODEL}"
    )
    if not args.dry_run:
        print(
            "\nNOTE: Stop the backend during write-mode migration so concurrent "
            "API writers do not race the index update.\n"
        )
    if config.USE_MOCK_LLM:
        print(
            "NOTE: mock mode is active. A write would store mock vectors.\n"
            "Configure a real GEMINI_API_KEY and USE_MOCK_LLM=false before a "
            "production Gemini migration, and pass --allow-index-replacement.\n"
        )

    result = run_reembed(
        db_path=args.db,
        document_id=args.document_id,
        dry_run=args.dry_run,
        create_backup=not args.no_backup,
        allow_index_replacement=args.allow_index_replacement,
    )

    print("\n--- report ---")
    print(f"chunks considered : {result.chunks_considered}")
    print(f"chunks validated  : {result.chunks_validated}")
    print(f"chunks updated    : {result.chunks_updated}")
    print(f"vector_dim        : {result.vector_dim}")
    print(f"mode              : {result.mode}")
    print(f"provider          : {result.provider}")
    print(f"model_name        : {result.model_name}")
    print(f"backup_path       : {result.backup_path}")
    if result.errors:
        print("errors:")
        for err in result.errors:
            print(f"  - {err}")
        return 1
    print("status            : OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
