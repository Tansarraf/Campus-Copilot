"""One-shot generator for synthetic_v1/benchmark.json (run from backend/)."""
from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).with_name("benchmark.json")


def q(
    question_id,
    question,
    category,
    expected_answer,
    expected_document_keys,
    expected_chunk_keys,
    answerability="answerable",
    difficulty="easy",
    evaluation_notes="",
    legacy_query=None,
):
    item = {
        "question_id": question_id,
        "question": question,
        "category": category,
        "expected_answer": expected_answer,
        "expected_document_keys": expected_document_keys,
        "expected_chunk_keys": expected_chunk_keys,
        "answerability": answerability,
        "difficulty": difficulty,
        "evaluation_notes": evaluation_notes,
    }
    if legacy_query is not None:
        item["legacy_query"] = legacy_query
    return item


def main():
    questions = []

    # --- Original 31 (preserved; wording kept via legacy_query when lightly clarified) ---
    questions += [
        q("calendar-odd-start-001", "When do odd semester classes begin in 2026?", "Academic Calendar",
          "August 3, 2026", ["academic_calendar"], ["academic_calendar:odd_semester_2026"],
          evaluation_notes="Legacy #1", legacy_query="When do odd semester classes begin in 2026?"),
        q("calendar-odd-end-exam-001", "What are the dates for the end-semester examinations in the odd semester?",
          "Academic Calendar", "December 7, 2026 to December 19, 2026",
          ["academic_calendar"], ["academic_calendar:odd_semester_2026"],
          evaluation_notes="Legacy #2", difficulty="easy",
          legacy_query="What are the dates for the end-semester examinations in the odd semester?"),
        q("calendar-winter-break-001", "When does winter break start?", "Academic Calendar",
          "December 20, 2026", ["academic_calendar"], ["academic_calendar:odd_semester_2026"],
          evaluation_notes="Legacy #3", legacy_query="When does winter break start?"),
        q("calendar-even-start-001", "When do even semester classes begin in 2027?", "Academic Calendar",
          "January 5, 2027", ["academic_calendar"], ["academic_calendar:even_semester_2027"],
          evaluation_notes="Legacy #4", legacy_query="When do even semester classes begin in 2027?"),
        q("calendar-holi-001", "When is the Holi break scheduled?", "Academic Calendar",
          "March 13, 2027 to March 15, 2027", ["academic_calendar"], ["academic_calendar:even_semester_2027"],
          evaluation_notes="Legacy #5", legacy_query="When is the Holi break scheduled?"),

        q("fees-tuition-btech-001", "What is the tuition fee for a B.Tech program per semester?", "Fees",
          "Rs. 1,85,000 per semester", ["fee_payment_circular"], ["fee_payment_circular:tuition_structure"],
          evaluation_notes="Legacy #6", legacy_query="What is the tuition fee for a B.Tech program per semester?"),
        q("fees-deadline-odd-001", "What is the deadline to pay fees for the odd semester?", "Fees",
          "August 15, 2026", ["fee_payment_circular"], ["fee_payment_circular:payment_deadlines"],
          evaluation_notes="Legacy #7", legacy_query="What is the deadline to pay fees for the odd semester?"),
        q("fees-late-fee-001", "What is the late fee penalty for missing the fee payment deadline?", "Fees",
          "Rs. 500 per day", ["fee_payment_circular"], ["fee_payment_circular:late_fee"],
          evaluation_notes="Legacy #8; source states Rs. 500 per day up to 15 days",
          legacy_query="What is the late fee penalty for missing the fee payment deadline?"),
        q("fees-refund-before-classes-001",
          "What percentage of tuition fee is refunded if a student withdraws before classes start?", "Fees",
          "90%", ["fee_payment_circular"], ["fee_payment_circular:refund_policy"],
          evaluation_notes="Legacy #9",
          legacy_query="What percentage of tuition fee is refunded if a student withdraws before classes start?"),
        q("fees-tuition-mba-001", "What is the MBA tuition fee per semester?", "Fees",
          "Rs. 2,40,000 per semester", ["fee_payment_circular"], ["fee_payment_circular:tuition_structure"],
          evaluation_notes="Legacy #10", legacy_query="What is the MBA tuition fee per semester?"),

        q("hostel-gate-weekday-001", "What time does the hostel gate close on weekdays?", "Hostel",
          "10:30 PM", ["hostel_rules_handbook"], ["hostel_rules_handbook:hostel_timings"],
          evaluation_notes="Legacy #11", legacy_query="What time does the hostel gate close on weekdays?"),
        q("hostel-mess-fee-001", "What is the mess fee per semester in the hostel?", "Hostel",
          "Rs. 28,000 per semester", ["hostel_rules_handbook"], ["hostel_rules_handbook:mess_fees_and_services"],
          evaluation_notes="Legacy #12", legacy_query="What is the mess fee per semester in the hostel?"),
        q("hostel-visitors-001", "When are visitors allowed to meet students in the hostel?", "Hostel",
          "10:00 AM and 6:00 PM", ["hostel_rules_handbook"], ["hostel_rules_handbook:visitors_policy"],
          evaluation_notes="Legacy #13; common room only between these hours",
          legacy_query="When are visitors allowed to meet students in the hostel?"),
        q("hostel-warnings-expulsion-001",
          "How many warnings before a student can be expelled from the hostel?", "Hostel",
          "three warnings", ["hostel_rules_handbook"], ["hostel_rules_handbook:disciplinary_rules"],
          evaluation_notes="Legacy #14",
          legacy_query="How many warnings before a student can be expelled from the hostel?"),
        q("hostel-room-allotment-001", "How is hostel room allotment decided for new students?", "Hostel",
          "academic merit", ["hostel_rules_handbook"], ["hostel_rules_handbook:room_allotment"],
          evaluation_notes="Legacy #15",
          legacy_query="How is hostel room allotment decided for new students?"),

        q("scholarship-merit-cgpa-001", "What CGPA is required to be eligible for the merit scholarship?",
          "Scholarships", "9.0", ["scholarship_notice"], ["scholarship_notice:merit_scholarship"],
          evaluation_notes="Legacy #16",
          legacy_query="What CGPA is required to be eligible for the merit scholarship?"),
        q("scholarship-merit-cover-001", "What percentage of tuition does the merit scholarship cover?",
          "Scholarships", "50%", ["scholarship_notice"], ["scholarship_notice:merit_scholarship"],
          evaluation_notes="Legacy #17",
          legacy_query="What percentage of tuition does the merit scholarship cover?"),
        q("scholarship-need-income-001", "What is the family income limit for need-based financial aid?",
          "Scholarships", "Rs. 3,00,000", ["scholarship_notice"], ["scholarship_notice:need_based_financial_aid"],
          evaluation_notes="Legacy #18",
          legacy_query="What is the family income limit for need-based financial aid?"),
        q("scholarship-deadline-001", "What is the deadline to apply for scholarships this year?",
          "Scholarships", "September 30, 2026", ["scholarship_notice"],
          ["scholarship_notice:general_application_instructions"],
          evaluation_notes="Legacy #19",
          legacy_query="What is the deadline to apply for scholarships this year?"),
        q("scholarship-sports-amount-001", "How much is the sports scholarship worth per year?",
          "Scholarships", "Rs. 50,000 per year", ["scholarship_notice"], ["scholarship_notice:sports_scholarship"],
          evaluation_notes="Legacy #20",
          legacy_query="How much is the sports scholarship worth per year?"),

        q("placement-cgpa-001", "What CGPA is required to register with the placement cell?", "Placements",
          "6.0", ["placement_guidelines"], ["placement_guidelines:eligibility_criteria"],
          evaluation_notes="Legacy #21",
          legacy_query="What CGPA is required to register with the placement cell?"),
        q("placement-one-offer-001", "What is the one offer policy for campus placements?", "Placements",
          "once a student accepts a job offer through campus placements, they are not permitted to sit for further placement drives",
          ["placement_guidelines"], ["placement_guidelines:one_offer_policy"],
          evaluation_notes="Legacy #22; Dream Company exception exists", difficulty="medium",
          legacy_query="What is the one offer policy for campus placements?"),
        q("placement-dress-001", "What is the dress code for placement interviews?", "Placements",
          "Formal business attire", ["placement_guidelines"], ["placement_guidelines:dress_code"],
          evaluation_notes="Legacy #23",
          legacy_query="What is the dress code for placement interviews?"),
        q("placement-confidential-001",
          "What happens if a student shares confidential interview questions?", "Placements",
          "barred from placements", ["placement_guidelines"], ["placement_guidelines:code_of_conduct"],
          evaluation_notes="Legacy #24",
          legacy_query="What happens if a student shares confidential interview questions?"),

        q("exam-attendance-001", "What is the minimum attendance required to be eligible to sit for exams?",
          "Examinations", "75%", ["examination_regulations"], ["examination_regulations:attendance"],
          evaluation_notes="Legacy #25",
          legacy_query="What is the minimum attendance required to be eligible to sit for exams?"),
        q("exam-revaluation-fee-001", "What is the revaluation fee per paper?", "Examinations",
          "Rs. 500 per paper", ["examination_regulations"], ["examination_regulations:revaluation"],
          evaluation_notes="Legacy #26",
          legacy_query="What is the revaluation fee per paper?"),
        q("exam-malpractice-001",
          "What happens if a student is caught with unauthorized material during an exam?", "Examinations",
          "Fail (F) grade", ["examination_regulations"], ["examination_regulations:malpractice"],
          evaluation_notes="Legacy #27",
          legacy_query="What happens if a student is caught with unauthorized material during an exam?"),
        q("exam-o-grade-001", "How many grade points does an O grade carry?", "Examinations",
          "10 grade points", ["examination_regulations"], ["examination_regulations:grading_scale"],
          evaluation_notes="Legacy #28",
          legacy_query="How many grade points does an O grade carry?"),

        q("library-ug-borrow-001",
          "How many books can an undergraduate student borrow at a time from the library?", "Library",
          "4 books", ["library_circular"], ["library_circular:borrowing_limits"],
          evaluation_notes="Legacy #29",
          legacy_query="How many books can an undergraduate student borrow at a time from the library?"),
        q("library-fine-001", "What is the library fine per day for an overdue book?", "Library",
          "Rs. 2 per day", ["library_circular"], ["library_circular:fines"],
          evaluation_notes="Legacy #30",
          legacy_query="What is the library fine per day for an overdue book?"),
        q("library-reference-borrow-001",
          "Can books in the reference section be borrowed from the library?", "Library",
          "may not be borrowed", ["library_circular"], ["library_circular:reference_section"],
          evaluation_notes="Legacy #31",
          legacy_query="Can books in the reference section be borrowed from the library?"),
    ]

    # --- Paraphrase variants ---
    questions += [
        q("fees-tuition-btech-para-001",
          "How much tuition does a B.Tech student pay each semester?", "Fees",
          "Rs. 1,85,000 per semester", ["fee_payment_circular"], ["fee_payment_circular:tuition_structure"],
          difficulty="easy", evaluation_notes="Paraphrase of fees-tuition-btech-001"),
        q("hostel-gate-weekday-para-001",
          "At what time is the hostel gate closed on weekdays?", "Hostel",
          "10:30 PM", ["hostel_rules_handbook"], ["hostel_rules_handbook:hostel_timings"],
          difficulty="easy", evaluation_notes="Paraphrase of hostel-gate-weekday-001"),
        q("exam-attendance-para-001",
          "What attendance percentage is needed to appear for end-semester exams?", "Examinations",
          "75%", ["examination_regulations"], ["examination_regulations:attendance"],
          difficulty="easy", evaluation_notes="Paraphrase of exam-attendance-001"),
        q("scholarship-merit-cgpa-para-001",
          "Minimum CGPA for the merit scholarship?", "Scholarships",
          "9.0", ["scholarship_notice"], ["scholarship_notice:merit_scholarship"],
          difficulty="easy", evaluation_notes="Paraphrase of scholarship-merit-cgpa-001"),
        q("library-fine-para-001",
          "How much is charged daily for returning a library book late?", "Library",
          "Rs. 2 per day", ["library_circular"], ["library_circular:fines"],
          difficulty="easy", evaluation_notes="Paraphrase of library-fine-001"),
    ]

    # --- Multi-document ---
    questions += [
        q("multi-fees-mess-001",
          "What is the B.Tech tuition fee and the hostel mess fee per semester?", "Multi-Document",
          "Rs. 1,85,000 per semester",  # primary check substring; notes mention both
          ["fee_payment_circular", "hostel_rules_handbook"],
          ["fee_payment_circular:tuition_structure", "hostel_rules_handbook:mess_fees_and_services"],
          difficulty="medium",
          evaluation_notes="Multi-doc; expected_answer checks tuition; mess Rs. 28,000 also required in answer for full credit notes"),
        q("multi-cgpa-merit-placement-001",
          "What CGPA is required for the merit scholarship, and what CGPA is required to register with the placement cell?",
          "Multi-Document", "9.0",
          ["scholarship_notice", "placement_guidelines"],
          ["scholarship_notice:merit_scholarship", "placement_guidelines:eligibility_criteria"],
          difficulty="medium",
          evaluation_notes="Multi-doc; also expects placement CGPA 6.0 in a complete answer"),
        q("multi-calendar-exam-attendance-001",
          "When do odd-semester end-semester exams run, and what minimum attendance is required to sit for exams?",
          "Multi-Document", "December 7, 2026",
          ["academic_calendar", "examination_regulations"],
          ["academic_calendar:odd_semester_2026", "examination_regulations:attendance"],
          difficulty="hard",
          evaluation_notes="Multi-doc; attendance 75% also expected in a complete answer"),
    ]

    # --- Partial ---
    questions += [
        q("partial-hostel-mess-refund-001",
          "What is the refund schedule for hostel and mess fees after withdrawal?", "Fees",
          None,
          ["fee_payment_circular"],
          ["fee_payment_circular:refund_policy"],
          answerability="partial", difficulty="medium",
          evaluation_notes="Fee circular states hostel/mess refunds follow a separate Hostel Office schedule; full schedule not in corpus"),
        q("partial-convocation-date-001",
          "What is the exact date of the annual convocation in 2027?", "Academic Calendar",
          None,
          ["academic_calendar"],
          ["academic_calendar:convocation"],
          answerability="partial", difficulty="medium",
          evaluation_notes="Only tentative first week of August 2027; exact date not published"),
    ]

    # --- Unanswerable (not in synthetic corpus) ---
    unanswerable = [
        ("unans-phd-stipend-001", "What is the monthly PhD stipend for research scholars?", "Research"),
        ("unans-bus-route-001", "What time does the campus shuttle leave the hostel for the main gate?", "Transport"),
        ("unans-wifi-password-001", "What is the default student Wi-Fi password?", "IT Services"),
        ("unans-parking-fee-001", "How much is the annual two-wheeler parking fee on campus?", "Facilities"),
        ("unans-medical-insurance-001", "What is the student medical insurance premium for 2026-27?", "Health"),
        ("unans-canteen-price-001", "What is the price of a standard thali in the main canteen?", "Facilities"),
        ("unans-faculty-phone-001", "What is the phone number of the Dean of Academic Affairs?", "Administration"),
        ("unans-calendar-2024-001", "When did odd semester classes begin in 2024?", "Academic Calendar"),
        ("unans-sports-complex-hours-001", "What are the weekday opening hours of the sports complex?", "Sports"),
        ("unans-mba-offcampus-hostel-001",
         "Are MBA students living off campus required to pay hostel mess fees?", "Hostel"),
    ]
    for qid, question, category in unanswerable:
        questions.append(q(
            qid, question, category, None, [], [],
            answerability="unanswerable", difficulty="medium",
            evaluation_notes="Out of synthetic corpus scope; correct behaviour is abstention",
        ))

    # Normalize unanswerable/partial expected_answer to null
    for item in questions:
        if item["answerability"] in ("unanswerable", "partial") and not item.get("expected_answer"):
            item["expected_answer"] = None

    legacy = [x for x in questions if x.get("legacy_query")]
    assert len(legacy) == 31, len(legacy)

    pack = {
        "pack": "synthetic_v1",
        "version": "2.0.0",
        "corpus_identity": "synthetic_v1",
        "description": (
            "Development evaluation pack over seven synthetic seed campus documents. "
            "Not a genuine university corpus."
        ),
        "questions": questions,
    }
    OUT.write_text(json.dumps(pack, indent=2), encoding="utf-8")
    print(f"wrote {OUT} with {len(questions)} questions ({len(legacy)} legacy)")


if __name__ == "__main__":
    main()
