import io
import csv
import json
import time
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from source.schemas import (
    Level1Bill,
    ChargeItem,
    TaxItem,
    clean_numeric,
    normalize_date,
    normalize_month,
)
from source.extractor import clean_json_response, BillExtractor
from source.explainer import BillExplainer
from source.csv_handler import (
    write_level1_csv,
    write_level2_csv,
    read_level1_template,
    read_level2_template,
    REQUIRED_L1_KEYS,
)
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


def test_kesc_0008_example_against_guide():
    """1. The KESC_0008 example against the guide's expected JSON."""
    bill = Level1Bill.model_validate(KESC_0008_GROUND_TRUTH)
    serialized = bill.to_submission_json()
    parsed = json.loads(serialized)

    assert parsed["provider"] == "KE"
    assert parsed["tariff"] == "A1-R"
    assert parsed["sanctioned_load_kw"] == 3
    assert parsed["bill_month"] == "2026-04"
    assert parsed["reading_date"] == "2026-04-03"
    assert parsed["issue_date"] == "2026-04-07"
    assert parsed["due_date"] == "2026-04-21"
    assert parsed["previous_reading"] == 8819
    assert parsed["current_reading"] == 8970
    assert parsed["units_consumed"] == 151
    assert parsed["total_charges"] == 2860.62
    assert parsed["total_taxes"] == 569.62
    assert parsed["current_bill"] == 3430.24
    assert parsed["arrears"] == -0.53
    assert parsed["payable_within_due_date"] == 3430
    assert parsed["payable_after_due_date"] == 3716
    assert len(parsed["charges"]) == 6
    assert len(parsed["taxes"]) == 3


def test_all_required_schema_keys_and_numeric_types():
    """2. All required schema keys and numeric types."""
    bill = Level1Bill.model_validate(KESC_0008_GROUND_TRUTH)
    serialized = bill.to_submission_json()
    parsed = json.loads(serialized)

    # Check key presence and order
    assert list(parsed.keys()) == REQUIRED_L1_KEYS

    # Verify numeric types (must be int or float, never quoted strings)
    numeric_keys = [
        "sanctioned_load_kw",
        "previous_reading",
        "current_reading",
        "units_consumed",
        "total_charges",
        "total_taxes",
        "current_bill",
        "arrears",
        "payable_within_due_date",
        "payable_after_due_date",
    ]
    for k in numeric_keys:
        val = parsed[k]
        assert isinstance(val, (int, float)), f"Key '{k}' must be int or float, got {type(val)}"

    for c in parsed["charges"]:
        assert isinstance(c["amount"], (int, float))
    for t in parsed["taxes"]:
        assert isinstance(t["amount"], (int, float))


def test_missing_hidden_fields_negative_credits_repeated_charges():
    """3. Missing/hidden fields, negative credits and repeated charge types."""
    # Hidden/unreadable fields must serialize to null
    partial_data = {
        "provider": "KE",
        "tariff": None,
        "sanctioned_load_kw": None,
        "bill_month": "2026-04",
        "reading_date": None,
        "issue_date": None,
        "due_date": None,
        "previous_reading": None,
        "current_reading": None,
        "units_consumed": 100,
        "charges": [
            {"type": "energy", "amount": 1000},
            {"type": "energy", "amount": 500},  # Repeated charge type
            {"type": "subsidy", "amount": 300},  # Must convert to negative
            {"type": "fixed", "amount": 0},      # Must be skipped
        ],
        "total_charges": 1200,
        "taxes": [],
        "total_taxes": None,
        "current_bill": 1200,
        "arrears": clean_numeric("54770CR"),     # Must be -54770
        "payable_within_due_date": -53570,
        "payable_after_due_date": None,
    }
    bill = Level1Bill.model_validate(partial_data)
    parsed = json.loads(bill.to_submission_json())

    # Check null preservation
    assert parsed["sanctioned_load_kw"] is None
    assert parsed["previous_reading"] is None
    assert parsed["due_date"] is None
    assert parsed["total_taxes"] is None

    # Check negative credit & subsidy
    assert parsed["arrears"] == -54770
    subsidy_charge = next(c for c in parsed["charges"] if c["type"] == "subsidy")
    assert subsidy_charge["amount"] == -300

    # Check repeated charges preserved & zero skipped
    energy_charges = [c for c in parsed["charges"] if c["type"] == "energy"]
    assert len(energy_charges) == 2
    assert not any(c["amount"] == 0 for c in parsed["charges"])


def test_correct_date_and_provider_normalization():
    """4. Correct date and provider normalization."""
    # Provider mapping
    assert Level1Bill.model_validate({"provider": "KESC"}).provider == "KE"
    assert Level1Bill.model_validate({"provider": "K-Electric"}).provider == "KE"
    assert Level1Bill.model_validate({"provider": "LESCO"}).provider == "LESCO"
    assert Level1Bill.model_validate({"provider": "IESCO"}).provider == "IESCO"

    # Date normalization
    assert normalize_date("22nd Sep 2026") == "2026-09-22"
    assert normalize_date("17 JUL 26") == "2026-07-17"
    assert normalize_date("03-Apr-26") == "2026-04-03"
    assert normalize_date("2026-04-21") == "2026-04-21"
    assert normalize_date("null") is None
    assert normalize_date(None) is None

    # Month normalization
    assert normalize_month("MAR 2026") == "2026-03"
    assert normalize_month("04/26") == "2026-04"
    assert normalize_month("Jun-26") == "2026-06"
    assert normalize_month("2026-09") == "2026-09"


def test_csv_escaping_row_counts_ids_and_question_preservation(tmp_path):
    """5. CSV escaping, row counts, IDs and question preservation."""
    bill = Level1Bill.model_validate(KESC_0008_GROUND_TRUTH)
    bill_ids = ["KESC_0008", "IESCO_0002"]
    bills_dict = {"KESC_0008": bill, "IESCO_0002": bill}

    out_l1 = tmp_path / "level1.csv"
    write_level1_csv(out_l1, bill_ids, bills_dict)

    # Read back with standard csv reader to verify escaping
    with open(out_l1, "r", encoding="utf-8") as f:
        reader = list(csv.reader(f))
        assert reader[0] == ["bill_id", "json"]
        assert len(reader) == 3
        # JSON must be single-line and deserializable
        parsed_l1 = json.loads(reader[1][1])
        assert parsed_l1["provider"] == "KE"
        assert parsed_l1["units_consumed"] == 151

    # Level 2 CSV test
    out_l2 = tmp_path / "level2.csv"
    template_rows = [
        ("KESC_0008", "Q1", 'Question with "quotes" and, commas?'),
        ("KESC_0008", "Q2", "Second question?"),
    ]
    answers_dict = {
        ("KESC_0008", "Q1"): 'Answer with "quoted terms", and commas.',
        ("KESC_0008", "Q2"): "Direct answer.",
    }
    write_level2_csv(out_l2, template_rows, answers_dict)

    with open(out_l2, "r", encoding="utf-8") as f:
        reader = list(csv.reader(f))
        assert reader[0] == ["bill_id", "question_id", "question", "answer"]
        assert len(reader) == 3
        # Verify row 1 exact question and answer content preserved
        assert reader[1][0] == "KESC_0008"
        assert reader[1][1] == "Q1"
        assert reader[1][2] == 'Question with "quotes" and, commas?'
        assert reader[1][3] == 'Answer with "quoted terms", and commas.'


def test_api_rate_limits_timeouts_malformed_responses_and_retries():
    """6. API timeouts, rate limits, malformed responses and retries."""
    # Test rate limiter interval
    client = GeminiClientWrapper()
    t0 = time.time()
    client._wait_for_rate_limit()
    client._wait_for_rate_limit()
    t1 = time.time()
    # Second call should have waited min_request_interval
    assert (t1 - t0) >= (client.min_request_interval - 0.1)

    # Test malformed response recovery
    fenced_with_trailing_comma = '```json\n{"provider": "KE", "units_consumed": 150,}\n```'
    cleaned = clean_json_response(fenced_with_trailing_comma)
    parsed = json.loads(cleaned)
    assert parsed["provider"] == "KE"
    assert parsed["units_consumed"] == 150

    # Test retry on simulated transient failure
    call_count = 0

    def mock_flaky_call(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count < 2:
            raise RuntimeError("Transient 503 Service Unavailable")
        mock_resp = MagicMock()
        mock_resp.text = '{"provider": "KE"}'
        return mock_resp

    with patch.object(client.client.models, "generate_content", side_effect=mock_flaky_call):
        res = client.generate_content(contents=["test"])
        assert res == '{"provider": "KE"}'
        assert call_count == 2


def test_no_personal_identifiers_in_results_or_logs():
    """7. No personal identifiers in results or logs."""
    bill = Level1Bill.model_validate(KESC_0008_GROUND_TRUTH)
    serialized = bill.to_submission_json()

    forbidden_pii_keys = [
        "name",
        "consumer_name",
        "address",
        "consumer_address",
        "cnic",
        "account_no",
        "account_number",
        "meter_no",
        "meter_number",
        "consumer_no",
        "reference_no",
    ]
    for pii_key in forbidden_pii_keys:
        assert f'"{pii_key}"' not in serialized

    # Check explainer sanitizer strips CNIC
    explainer = BillExplainer()
    raw_answer = "Account for 42101-1234567-1 was billed PKR 3430."
    sanitized = explainer._sanitize_answer(raw_answer)
    assert "42101-1234567-1" not in sanitized
    assert "[REDACTED]" in sanitized


@pytest.mark.skipif(not API_KEY, reason="API key required for training bill checks")
def test_five_training_bills_extraction():
    """8. Use only the five training bills for training-stage checks."""
    train_dir = Path("data/train")
    training_images = [
        "IESCO_0004.jpg",
        "KESC_0004.png",
        "KESC_0008.png",
        "LESCO_0005.png",
        "LESCO_0006.png",
    ]

    extractor = BillExtractor()
    for img_name in training_images:
        img_path = train_dir / img_name
        if not img_path.exists():
            continue

        # Uses caching to avoid repeated API calls
        bill = extractor.extract(img_path, use_cache=True)
        assert bill.provider in ["KE", "LESCO", "IESCO"]
        assert bill.bill_month is not None
        assert isinstance(bill.charges, list)
        assert isinstance(bill.taxes, list)

        # Ensure serialized JSON contains all 18 keys
        parsed = json.loads(bill.to_submission_json())
        assert set(parsed.keys()) == set(REQUIRED_L1_KEYS)
