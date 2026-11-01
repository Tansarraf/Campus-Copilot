# Data cleanup review (no deletions performed)

Inspected `backend/campus_copilot.db` before/during the auth foundation work.
**Nothing was deleted.** Confirm before any removal.

| Item | Status | Recommendation |
|------|--------|----------------|
| Schema / tables | Preserved | Keep |
| Admin user (`admin`) | Preserved | Keep — required for admin access |
| Legacy demo student user (`student`, no `student_profiles` row) | Preserved | Keep until you provision real demo students; then optionally remove |
| Seed documents (7 campus circulars) + chunks | Preserved | Keep for RAG demos |
| Extra document `Receipt-2775-3790.pdf` (Fees) | **Flagged** | Origin uncertain — confirm before delete |
| All chunk embeddings (`embedding_dim=128`) | Preserved | Mock vectors — **re-ingest** after real Gemini key; do not delete corpus blindly |
| `query_logs` / `feedback` | Empty | Nothing to clean |
| Mock mode code paths | Preserved | Still needed for offline/dev tests |
| Seed scripts | Preserved | `seed_users.py` now admin-only; student template added |

Database backup created before migration: `backend/campus_copilot.db.backup_*`
