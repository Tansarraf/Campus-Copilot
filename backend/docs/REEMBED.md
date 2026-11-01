# Embedding re-index (re-embed) guide

## Purpose

Replace stored chunk embedding BLOBs in place when migrating between mock and
real Gemini embeddings (`models/gemini-embedding-001` by default), without deleting document
or chunk rows.

## Hard rules

- **Write mode is full-corpus only.** `--document-id` is rejected unless
  combined with `--dry-run` (inspection).
- **Mode/model transitions require** `--allow-index-replacement`.
- A verified **SQLite Online Backup** is created before any write (unless
  `--no-backup`).
- All replacement vectors are generated and validated **before** the update
  transaction. Failures roll back; originals are kept.
- Ordinary document upload/ingestion **cannot** silently create a mixed index
  or overwrite `embedding_index_meta`.

## Operational recommendation

**Stop the backend** (`uvicorn`) before a write-mode migration so concurrent
API writers do not race the index transaction. The backup uses SQLite’s Online
Backup API (consistent snapshot), but migration safety is highest with the API
idle.

## Commands

```bash
cd backend

# Safe inspection (no writes)
python scripts/reembed_documents.py --dry-run
python scripts/reembed_documents.py --dry-run --document-id 1

# Future Gemini migration (after real GEMINI_API_KEY + USE_MOCK_LLM=false):
# 1) stop uvicorn
# 2) dry-run
# 3) write with explicit replacement opt-in
python scripts/reembed_documents.py --dry-run
python scripts/reembed_documents.py --allow-index-replacement
```

## Metadata

Table `embedding_index_meta` (single row) stores `provider`, `model_name`,
`vector_dim`, `mode`, and `last_indexed_at`. It is written only after a
successful **full-corpus** re-embed (or the first ingest into a previously empty
chunk store). Retrieval compares the configured embedder identity to this row
and returns HTTP 409 on mismatch.
