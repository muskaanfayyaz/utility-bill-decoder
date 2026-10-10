import json
import pytest
from pathlib import Path
from source.schemas import (
    Level1Bill,
    ChargeItem,
    TaxItem,
    clean_numeric,
    normalize_date,
    normalize_month,
)
from source.extractor import clean_json_response, BillExtractor
from source.client import GeminiClientWrapper
from source.config import API_KEY

# Ground truth from WTQ Guide Section 5.7
KESC_0008_GROUND_TRUTH = {
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


def test_kesc_0008_regression_schema():
    """Verifies that the Level1Bill model validates and serializes KESC_0008 exactly as required."""
    bill = Level1Bill.model_validate(KESC_0008_GROUND_TRUTH)
    assert bill.provider == "KE"
    assert bill.tariff == "A1-R"
    assert bill.sanctioned_load_kw == 3
    assert bill.bill_month == "2026-04"
    assert bill.reading_date == "2026-04-03"
    assert bill.issue_date == "2026-04-07"
    assert bill.due_date == "2026-04-21"
    assert bill.previous_reading == 8819
    assert bill.current_reading == 8970
    assert bill.units_consumed == 151
    assert len(bill.charges) == 6
    assert len(bill.taxes) == 3
    assert bill.total_charges == 2860.62
    assert bill.total_taxes == 569.62
    assert bill.current_bill == 3430.24
    assert bill.arrears == -0.53
    assert bill.payable_within_due_date == 3430
    assert bill.payable_after_due_date == 3716

    # Verify single-line JSON serialization
    serialized = bill.to_submission_json()
    assert "\n" not in serialized
    parsed = json.loads(serialized)
    assert parsed["provider"] == "KE"
    assert parsed["arrears"] == -0.53
    assert len(parsed["charges"]) == 6


def test_provider_mapping():
    """Ensures KESC, K-Electric variants map to 'KE', and other providers remain valid."""
    assert Level1Bill.model_validate({"provider": "KESC"}).provider == "KE"
    assert Level1Bill.model_validate({"provider": "K-Electric"}).provider == "KE"
    assert Level1Bill.model_validate({"provider": "LESCO"}).provider == "LESCO"
    assert Level1Bill.model_validate({"provider": "IESCO"}).provider == "IESCO"


def test_credits_and_subsidies_negative():
    """Ensures credits (CR) and subsidies are stored as negative numbers."""
    assert clean_numeric("38209CR") == -38209
    assert clean_numeric("54770CR") == -54770
    assert clean_numeric("-0.53") == -0.53

    # Subsidy line items must be negative
    item = ChargeItem(type="subsidy", amount=3332)
    assert item.amount == -3332


def test_skip_zero_charges():
    """Ensures charges and taxes with 0 amounts are skipped per section 5.3."""
    bill_data = {
        "provider": "KE",
        "charges": [
            {"type": "fixed", "amount": 500},
            {"type": "meter_rent", "amount": 0},
            {"type": "other", "amount": 0.0},
        ],
        "taxes": [
            {"type": "gst", "amount": 100},
            {"type": "electricity_duty", "amount": 0},
        ],
    }
    bill = Level1Bill.model_validate(bill_data)
    assert len(bill.charges) == 1
    assert bill.charges[0].type == "fixed"
    assert len(bill.taxes) == 1
    assert bill.taxes[0].type == "gst"


def test_date_and_month_normalizers():
    """Tests date normalization for common bill formats."""
    assert normalize_date("22nd Sep 2026") == "2026-09-22"
    assert normalize_date("17 JUL 26") == "2026-07-17"
    assert normalize_date("03-Apr-26") == "2026-04-03"
    assert normalize_date("2026-04-21") == "2026-04-21"
    assert normalize_date("invalid") is None

    assert normalize_month("MAR 2026") == "2026-03"
    assert normalize_month("Jun-26") == "2026-06"
    assert normalize_month("2026-04") == "2026-04"
    assert normalize_month("04/26") == "2026-04"


def test_clean_json_response_fences_and_commas():
    """Tests JSON response cleaning for code fences and trailing commas."""
    fenced = '```json\n{"provider": "KE", "current_bill": 3430,}\n```'
    cleaned = clean_json_response(fenced)
    parsed = json.loads(cleaned)
    assert parsed["provider"] == "KE"
    assert parsed["current_bill"] == 3430


def test_no_pii_in_json():
    """Verifies that no personal identifiers are present in output keys."""
    bill = Level1Bill.model_validate(KESC_0008_GROUND_TRUTH)
    out_json = bill.to_submission_json()
    forbidden = ["name", "address", "cnic", "consumer_no", "meter_no", "account_no"]
    for word in forbidden:
        assert f'"{word}"' not in out_json


@pytest.mark.skipif(not API_KEY, reason="API key required for live multimodal test")
def test_live_extraction_kesc_0008():
    """Tests live Gemini extraction on training bill KESC_0008.png."""
    client = GeminiClientWrapper()
    extractor = BillExtractor(client=client)
    img_path = Path("data/train/KESC_0008.png")
    if not img_path.exists():
        pytest.skip("data/train/KESC_0008.png not found")

    bill = extractor.extract(img_path)
    assert bill.provider == "KE"
    assert bill.bill_month == "2026-04"
    assert bill.units_consumed == 151
    assert abs(bill.total_charges - 2860.62) < 1.0
    assert abs(bill.total_taxes - 569.62) < 1.0
    assert abs(bill.current_bill - 3430.24) < 1.0
    assert abs(bill.payable_after_due_date - 3716) < 1.0
