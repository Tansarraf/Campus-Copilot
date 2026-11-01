"""Deterministic IR / answerability / citation metrics for evaluation v2."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RankedItem:
    document_key: str | None
    chunk_key: str | None
    document_id: int | None = None
    chunk_id: int | None = None
    rank: int = 0


def precision_at_k(retrieved: list[str | None], relevant: set[str], k: int) -> float:
    """Fraction of top-k retrieved ids that are in the relevant set."""
    if k <= 0:
        return 0.0
    top = retrieved[:k]
    if not top:
        return 0.0
    hits = sum(1 for x in top if x is not None and x in relevant)
    return hits / k


def recall_at_k(retrieved: list[str | None], relevant: set[str], k: int) -> float | None:
    """
    Fraction of gold relevant items that appear in top-k.
    Returns None when there is no gold relevant set (undefined).
    """
    if not relevant:
        return None
    if k <= 0:
        return 0.0
    top = {x for x in retrieved[:k] if x is not None}
    return len(relevant & top) / len(relevant)


def hit_rate_at_k(retrieved: list[str | None], relevant: set[str], k: int) -> float | None:
    """1.0 if at least one relevant item is in top-k; None if no gold set."""
    if not relevant:
        return None
    if k <= 0:
        return 0.0
    top = {x for x in retrieved[:k] if x is not None}
    return 1.0 if relevant & top else 0.0


def reciprocal_rank(retrieved: list[str | None], relevant: set[str]) -> float | None:
    """Reciprocal rank of the first relevant item; None if no gold set."""
    if not relevant:
        return None
    for i, item in enumerate(retrieved, start=1):
        if item is not None and item in relevant:
            return 1.0 / i
    return 0.0


def citation_precision(cited: set[str], relevant: set[str]) -> float | None:
    if not cited:
        return None if relevant else 1.0
    return len(cited & relevant) / len(cited)


def citation_coverage(cited: set[str], relevant: set[str]) -> float | None:
    if not relevant:
        return None
    return len(cited & relevant) / len(relevant)


def normalize_text(value: str) -> str:
    return " ".join((value or "").lower().split())


def answer_contains_expected(answer: str, expected_answer: str | None) -> bool | None:
    """
    Objective containment check for short factual expected answers.
    Returns None if no expected_answer is provided.
    """
    if expected_answer is None or not str(expected_answer).strip():
        return None
    return normalize_text(expected_answer) in normalize_text(answer)


def percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    if len(s) == 1:
        return float(s[0])
    idx = min(len(s) - 1, max(0, int(round((pct / 100.0) * (len(s) - 1)))))
    return float(s[idx])
