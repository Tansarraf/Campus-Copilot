#!/usr/bin/env python3
"""Read-only inventory check for Campus Copilot SQLite databases."""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

EXPECTED = {
    "documents": 20,
    "chunks": 56,
    "users": 4,
    "academic_events": 8,
    "evaluation_runs": 2,
}


def counts(db_path: Path) -> dict[str, int]:
    conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    try:
        cur = conn.cursor()
        out: dict[str, int] = {}
        for table in EXPECTED:
            out[table] = cur.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        return out
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("db", type=Path, help="Path to campus_copilot.db")
    parser.add_argument(
        "--expect-baseline",
        action="store_true",
        help="Fail unless counts match the known pre-Docker baseline",
    )
    args = parser.parse_args()
    if not args.db.is_file():
        print(f"MISSING {args.db}", file=sys.stderr)
        return 2
    got = counts(args.db)
    print(f"DB {args.db}")
    for k, v in got.items():
        print(f"  {k}: {v}")
    if args.expect_baseline and got != EXPECTED:
        print(f"MISMATCH expected {EXPECTED}", file=sys.stderr)
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
