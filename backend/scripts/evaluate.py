"""
Campus Copilot evaluation v2 CLI.

Examples (from backend/):

  python scripts/evaluate.py --benchmark synthetic_v1
  python scripts/evaluate.py --benchmark synthetic_v1 --retrieval-only
  python scripts/evaluate.py --benchmark synthetic_v1 --k 1,3,5

Writes a new SQLite evaluation_runs row and evaluation/results/<run_id>.json.
Never overwrites prior runs.
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.evaluation.benchmark import list_packs
from app.evaluation.runner import print_summary, run_evaluation


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Campus Copilot deterministic evaluation (v2)")
    p.add_argument(
        "--benchmark",
        default="synthetic_v1",
        help="Benchmark pack name under evaluation/packs/ (default: synthetic_v1)",
    )
    p.add_argument(
        "--corpus",
        default=None,
        help="Corpus identity override (default: pack corpus_identity)",
    )
    p.add_argument(
        "--k",
        default="1,3,5",
        help="Comma-separated K values for Precision/Recall/HitRate (default: 1,3,5)",
    )
    p.add_argument(
        "--top-k",
        type=int,
        default=None,
        help="Retrieval depth (default: max(K, 10))",
    )
    p.add_argument(
        "--retrieval-only",
        action="store_true",
        help="Skip generation/abstention/citation scoring",
    )
    p.add_argument(
        "--retrieval-mode",
        choices=("hybrid", "vector", "keyword"),
        default=None,
        help="Override RETRIEVAL_MODE for this run (hybrid|vector|keyword)",
    )
    p.add_argument(
        "--no-persist",
        action="store_true",
        help="Do not write SQLite/JSON results (still prints summary)",
    )
    p.add_argument(
        "--list-packs",
        action="store_true",
        help="List available benchmark packs and exit",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.list_packs:
        packs = list_packs()
        print("Available packs:", ", ".join(packs) if packs else "(none)")
        return 0

    try:
        k_values = tuple(int(x.strip()) for x in args.k.split(",") if x.strip())
        if not k_values or any(k <= 0 for k in k_values):
            raise ValueError("--k must be a comma-separated list of positive integers")
    except ValueError as exc:
        print(f"Invalid --k: {exc}", file=sys.stderr)
        return 2

    try:
        result = run_evaluation(
            benchmark_pack=args.benchmark,
            corpus_identity=args.corpus,
            k_values=k_values,
            top_k=args.top_k,
            retrieval_only=args.retrieval_only,
            persist=not args.no_persist,
            progress=lambda m: print(m),
            retrieval_mode=args.retrieval_mode,
        )
    except Exception as exc:
        print(f"Evaluation failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print_summary(result)
    # Non-zero if hard failures dominated (API failures on all questions)
    summary = result["summary"]
    if summary["num_api_failures"] and summary["num_evaluated"] == 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
