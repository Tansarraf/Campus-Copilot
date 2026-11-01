"""
Ingests every file in seed_data/ into the knowledge base, using the same
loader -> chunker -> embed -> store pipeline the /documents/upload API
endpoint uses (see app/routers/documents_router.py). Run this once after
seeding users and generating the PDF/DOCX seed documents.

Run from backend/: python scripts/ingest_seed_docs.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import get_conn, init_db, now_iso
from app.ingestion.chunker import chunk_units
from app.ingestion.loaders import load_document
from app.retrieval import index_document_chunks

SEED_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "seed_data")

# filename -> (title, category, department, academic_year)
CATALOG = {
    "academic_calendar_2026_27.md": (
        "Academic Calendar 2026-27", "Academic Calendar", None, "2026-27"),
    "fee_payment_circular.pdf": (
        "Fee Payment Circular, Academic Year 2026-27", "Fees", None, "2026-27"),
    "hostel_rules_handbook.docx": (
        "Hostel Rules Handbook, Academic Year 2026-27", "Hostel", None, "2026-27"),
    "scholarship_notice.md": (
        "Scholarship and Financial Aid Notice, Academic Year 2026-27", "Scholarships", None, "2026-27"),
    "placement_guidelines.txt": (
        "Placement Cell Guidelines, 2026-27 Placement Season", "Placements", None, "2026-27"),
    "examination_regulations.pdf": (
        "Examination Regulations, Academic Year 2026-27", "Examinations", None, "2026-27"),
    "library_circular.txt": (
        "Central Library Circular: Borrowing Rules and Services", "Library", None, "2026-27"),
}


def main():
    init_db()
    with get_conn() as conn:
        admin = conn.execute("SELECT id FROM users WHERE role = 'admin' LIMIT 1").fetchone()
    if admin is None:
        print("No admin user found. Run scripts/seed_users.py first.")
        return
    admin_id = admin["id"]

    for filename, (title, category, department, academic_year) in CATALOG.items():
        path = os.path.join(SEED_DIR, filename)
        if not os.path.exists(path):
            print(f"skip (missing, run scripts/generate_seed_documents.py first): {filename}")
            continue

        with get_conn() as conn:
            existing = conn.execute("SELECT id FROM documents WHERE filename = ?", (filename,)).fetchone()
        if existing:
            print(f"skip (already ingested): {filename}")
            continue

        ext = os.path.splitext(filename)[1].lower()
        units, _load_meta = load_document(path)
        chunks = chunk_units(units)

        with get_conn() as conn:
            cur = conn.execute(
                """INSERT INTO documents (filename, title, category, department, academic_year,
                                           file_type, uploaded_by, uploaded_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (filename, title, category, department, academic_year,
                 ext.lstrip("."), admin_id, now_iso()),
            )
            document_id = cur.lastrowid

        n = index_document_chunks(document_id, chunks)
        print(f"ingested: {filename} -> {n} chunks (doc_id={document_id})")


if __name__ == "__main__":
    main()
