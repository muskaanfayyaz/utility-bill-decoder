import pytest
from pathlib import Path
from source.schemas import Level1Bill
from source.calculator import compute_derived_metrics, format_metrics_summary
from source.explainer import BillExplainer
from source.config import API_KEY

SAMPLE_KESC_BILL = {
    "provider": "KE",
    "tariff": "A1-R",
    "sanctioned_load_kw": 3,
    "bill_month": "2026-04",
    "reading_date": "2026-04-03",
    "issue_date": "2026-04-07",
    "due_date": "2026-04-21",
    "previous_reading": 8819,
    "current_reading": 8970,
    "units_consumed": 151,
    "charges": [
        {"type": "fixed", "amount": 900},
        {"type": "energy", "amount": 1054},
        {"type": "energy", "amount": 663.51},
        {"type": "quarterly_adjustment", "amount": 52.91},
        {"type": "fpa", "amount": 125.27},
        {"type": "surcharge", "amount": 64.93},
    ],
    "total_charges": 2860.62,
    "taxes": [
        {"type": "electricity_duty", "amount": 29.41},
        {"type": "gst", "amount": 520.21},
        {"type": "municipal_tax", "amount": 20},
    ],
    "total_taxes": 569.62,
    "current_bill": 3430.24,
    "arrears": -0.53,
    "payable_within_due_date": 3430,
    "payable_after_due_date": 3716,
}


def test_derived_metrics_kesc_0008():
    bill = Level1Bill.model_validate(SAMPLE_KESC_BILL)
    metrics = compute_derived_metrics(bill)

    assert metrics["sum_charges"] == 2860.62
    assert metrics["sum_taxes"] == 569.62
    assert metrics["tax_percentage_of_current_bill"] == 16.61
    assert metrics["charges_percentage_of_current_bill"] == 83.39
    assert metrics["late_payment_difference"] == 286
    assert metrics["meter_difference"] == 151

    summary = format_metrics_summary(bill, metrics)
    assert "PKR 569.62 (16.61% of current bill)" in summary
    assert "PKR 286" in summary


def test_sanitize_answer():
    explainer = BillExplainer()
    assert explainer._sanitize_answer("") == "This information is not specified on the bill."

    text_with_cnic = "The consumer CNIC 42101-1234567-1 was billed."
    sanitized = explainer._sanitize_answer(text_with_cnic)
    assert "42101-1234567-1" not in sanitized
    assert "[REDACTED]" in sanitized


@pytest.mark.skipif(not API_KEY, reason="API key required for live multimodal test")
def test_live_explainer_batch_answers():
    explainer = BillExplainer()
    img_path = Path("data/train/KESC_0008.png")
    if not img_path.exists():
        pytest.skip("data/train/KESC_0008.png not found")

    bill = Level1Bill.model_validate(SAMPLE_KESC_BILL)
    questions = [
        ("Q1", "How much of my bill is taxes?"),
        ("Q2", "What is the late payment surcharge if paid after the due date?"),
        ("Q3", "How many units were billed for the current month?"),
    ]

    answers = explainer.answer_questions_batch(img_path, bill, questions)

    assert "Q1" in answers and len(answers["Q1"].strip()) > 10
    assert "Q2" in answers and len(answers["Q2"].strip()) > 10
    assert "Q3" in answers and len(answers["Q3"].strip()) > 10

    # Q1 should mention taxes amount or percentage
    assert "569" in answers["Q1"] or "16" in answers["Q1"] or "tax" in answers["Q1"].lower()
    # Q2 should mention 286 or 3,716
    assert "286" in answers["Q2"] or "3716" in answers["Q2"] or "3,716" in answers["Q2"]
    # Q3 should mention 151
    assert "151" in answers["Q3"]
