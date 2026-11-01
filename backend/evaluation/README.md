# Evaluation Framework v2

Deterministic retrieval / answerability / citation evaluation for Campus Copilot.

## Corpus identities

| Identity | Meaning |
|----------|---------|
| `synthetic_v1` | Seven synthetic seed campus fixtures (development only). Excludes `Receipt-2775-3790.pdf` from the eval corpus without deleting it. |
| `university_v1` | Reserved for genuine university documents (empty until annotated). |

## Run

From `backend/`:

```bash
python scripts/evaluate.py --benchmark synthetic_v1
python scripts/evaluate.py --benchmark synthetic_v1 --retrieval-only
python scripts/evaluate.py --benchmark synthetic_v1 --k 1,3,5
python scripts/evaluate.py --list-packs
```

Results are appended as new rows in SQLite (`evaluation_runs` / `evaluation_question_results`) and mirrored under `evaluation/results/<run_id>.json`. Prior runs are never overwritten.

Mock mode is labeled on every run. Faithfulness / Gemini answer quality are not claimed under mock embeddings/generation.
