"""
Generates the PDF and DOCX seed documents (the .md/.txt ones are checked in
directly under seed_data/). Kept as a script rather than committing binary
files so the whole seed corpus is reproducible from readable source.

Run from backend/: python scripts/generate_seed_documents.py
Requires: reportlab, python-docx (both in requirements.txt)
"""
import os

from docx import Document
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak

SEED_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "seed_data")


def _pdf_doc(filename, title, sections):
    """sections: list of (heading, paragraphs[]); each heading starts fresh
    content but NOT necessarily a new page -- page breaks are inserted to
    guarantee this document spans multiple pages, which is what makes
    page-level citation meaningful for the retrieval demo."""
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("H1", parent=styles["Heading1"], spaceAfter=12)
    h2 = ParagraphStyle("H2", parent=styles["Heading2"], spaceBefore=14, spaceAfter=8)
    body = ParagraphStyle("Body", parent=styles["BodyText"], spaceAfter=10, leading=15)

    path = os.path.join(SEED_DIR, filename)
    doc = SimpleDocTemplate(path, pagesize=A4, topMargin=2*cm, bottomMargin=2*cm,
                             leftMargin=2*cm, rightMargin=2*cm)
    story = [Paragraph(title, h1), Spacer(1, 6)]
    for i, (heading, paras) in enumerate(sections):
        if i > 0 and i % 2 == 0:
            story.append(PageBreak())
        story.append(Paragraph(heading, h2))
        for p in paras:
            story.append(Paragraph(p, body))
    doc.build(story)
    print(f"wrote {path}")


def make_fee_circular():
    sections = [
        ("Tuition Fee Structure", [
            "The tuition fee structure for the 2026-27 academic year is as follows. "
            "B.Tech programs: Rs. 1,85,000 per semester. M.Tech programs: Rs. 95,000 per semester. "
            "MBA program: Rs. 2,40,000 per semester. These amounts are exclusive of hostel and mess fees, "
            "which are billed separately by the Hostel Office.",
        ]),
        ("Payment Deadlines", [
            "Fees for the Odd Semester must be paid no later than August 15, 2026. "
            "Fees for the Even Semester must be paid no later than January 10, 2027. "
            "Payments can be made online via the student portal using net banking, UPI, or card payment, "
            "or in person at the Accounts Office during working hours.",
        ]),
        ("Late Fee Penalty", [
            "Students who miss the payment deadline will be charged a late fee of Rs. 500 per day, "
            "up to a maximum of 15 days past the deadline. Students who have not paid fees within 15 days "
            "of the deadline will have their semester registration cancelled and must apply for reinstatement "
            "through the Dean of Academic Affairs, subject to a reinstatement fee of Rs. 5,000.",
        ]),
        ("Refund Policy", [
            "Students who withdraw before the start of classes are eligible for a 90% refund of tuition fees paid. "
            "Students who withdraw within the first two weeks of classes are eligible for a 50% refund. "
            "No refund will be issued for withdrawal after the first two weeks of the semester. "
            "Hostel and mess fees follow a separate refund schedule published by the Hostel Office.",
        ]),
    ]
    _pdf_doc("fee_payment_circular.pdf", "Fee Payment Circular, Academic Year 2026-27", sections)


def make_exam_regulations():
    sections = [
        ("Attendance Requirement", [
            "A minimum of 75% attendance in each registered course is required to be eligible to sit for the "
            "End-Semester Examination in that course. Students with attendance between 65% and 75% may apply "
            "for condonation on medical grounds, supported by a certificate from a registered medical practitioner, "
            "submitted to the Head of Department within one week of the last day of classes. "
            "Students with attendance below 65% will not be permitted to sit for the examination under any circumstances.",
        ]),
        ("Grading Scale", [
            "The institute follows a letter grading system: O (Outstanding, 10 grade points), A+ (9), A (8), "
            "B+ (7), B (6), C (5), P (4, Pass), and F (0, Fail). The Cumulative Grade Point Average (CGPA) is "
            "computed as the credit-weighted average of grade points across all registered courses.",
        ]),
        ("Revaluation", [
            "Students who wish to have an End-Semester answer script re-evaluated may apply within 10 days of "
            "the declaration of results. The revaluation fee is Rs. 500 per paper, refundable only if the grade "
            "changes by one full grade point or more. Revaluation is not available for mid-semester examinations.",
        ]),
        ("Examination Malpractice", [
            "Any student found engaging in malpractice during an examination, including possession of unauthorized "
            "material, communicating with another candidate, or impersonation, will receive a Fail (F) grade in that "
            "course and will be referred to the Institute Disciplinary Committee, which may impose further penalties "
            "including suspension for one or more semesters.",
        ]),
    ]
    _pdf_doc("examination_regulations.pdf", "Examination Regulations, Academic Year 2026-27", sections)


def make_hostel_handbook():
    doc = Document()
    doc.add_heading("Hostel Rules Handbook, Academic Year 2026-27", level=1)

    doc.add_heading("Room Allotment", level=2)
    doc.add_paragraph(
        "Hostel rooms are allotted based on academic merit for new admissions and on a first-come, "
        "first-served basis for returning students renewing their hostel accommodation. Room change "
        "requests after allotment are considered only in the first two weeks of each semester and are "
        "subject to availability."
    )

    doc.add_heading("Hostel Timings", level=2)
    doc.add_paragraph(
        "The hostel gate closes at 10:30 PM on weekdays (Sunday to Thursday nights) and 11:30 PM on "
        "weekend nights (Friday and Saturday). Students returning after gate closing time must sign the "
        "late-entry register at the security desk and will be marked for review after three late entries "
        "in a semester."
    )

    doc.add_heading("Mess Fees and Services", level=2)
    doc.add_paragraph(
        "Mess fees are Rs. 28,000 per semester and are billed together with hostel fees at the start of "
        "each semester. The mess menu is published weekly on the hostel notice board and the student "
        "portal. Students with dietary restrictions may register with the Hostel Office for an alternate menu."
    )

    doc.add_heading("Visitors Policy", level=2)
    doc.add_paragraph(
        "Visitors are permitted only in the designated common room between 10:00 AM and 6:00 PM. Visitors "
        "are not permitted inside student rooms at any time. All visitors must register at the security "
        "desk with a valid photo ID."
    )

    doc.add_heading("Disciplinary Rules", level=2)
    doc.add_paragraph(
        "Violations of hostel rules are recorded as warnings. A student who accumulates three warnings in "
        "an academic year may be recommended for expulsion from the hostel by the Warden, subject to review "
        "by the Dean of Student Affairs. Possession of prohibited items (including electrical heaters, "
        "candles, or any banned substances) results in an immediate warning regardless of prior record."
    )

    path = os.path.join(SEED_DIR, "hostel_rules_handbook.docx")
    doc.save(path)
    print(f"wrote {path}")


if __name__ == "__main__":
    os.makedirs(SEED_DIR, exist_ok=True)
    make_fee_circular()
    make_exam_regulations()
    make_hostel_handbook()
