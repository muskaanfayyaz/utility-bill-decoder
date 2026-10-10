import csv
import json
import re
from pathlib import Path
from typing import List, Tuple, Set

REQUIRED_L1_KEYS = {
    "provider",
    "tariff",
    "sanctioned_load_kw",
    "bill_month",
    "reading_date",
    "issue_date",
    "due_date",
    "previous_reading",
    "current_reading",
    "units_consumed",
    "charges",
    "total_charges",
    "taxes",
    "total_taxes",
    "current_bill",
    "arrears",
    "payable_within_due_date",
    "payable_after_due_date",
}

VALID_PROVIDERS = {"KE", "LESCO", "IESCO"}
VALID_CHARGE_TYPES = {
    "energy",
    "fixed",
    "fpa",
    "quarterly_adjustment",
    "surcharge",
    "meter_rent",
    "subsidy",
    "other",
}
VALID_TAX_TYPES = {
    "gst",
    "electricity_duty",
    "income_tax",
    "municipal_tax",
    "other_tax",
}


def validate_level1_csv(csv_path: Path, expected_count: int = 10) -> List[str]:
    """Validates level1.csv formatting, schema conformance, and checks for empty cells."""
    errors: List[str] = []
    if not csv_path.exists():
        return [f"File does not exist: {csv_path}"]

    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != ["bill_id", "json"]:
            errors.append(f"Invalid column names in level1.csv: {reader.fieldnames}. Expected ['bill_id', 'json']")

        rows = list(reader)
        if len(rows) != expected_count:
            errors.append(f"Expected {expected_count} rows in level1.csv, but found {len(rows)}.")

        for idx, row in enumerate(rows, start=1):
            bid = row.get("bill_id", "")
            raw_json = row.get("json", "")

            if not bid:
                errors.append(f"Row {idx}: missing bill_id")
            if not raw_json or not raw_json.strip():
                errors.append(f"Row {idx} ({bid}): empty json cell")
                continue

            # Verify single-line
            if "\n" in raw_json or "\r" in raw_json:
                errors.append(f"Row {idx} ({bid}): JSON contains newline characters; must be single line.")

            try:
                data = json.loads(raw_json)
            except Exception as e:
                errors.append(f"Row {idx} ({bid}): Invalid JSON syntax: {e}")
                continue

            missing_keys = REQUIRED_L1_KEYS - set(data.keys())
            if missing_keys:
                errors.append(f"Row {idx} ({bid}): Missing required JSON keys: {missing_keys}")

            provider = data.get("provider")
            if provider not in VALID_PROVIDERS:
                errors.append(f"Row {idx} ({bid}): Invalid provider '{provider}'. Must be one of {VALID_PROVIDERS}")

            # Check charges
            charges = data.get("charges")
            if not isinstance(charges, list):
                errors.append(f"Row {idx} ({bid}): 'charges' must be a list")
            else:
                for c in charges:
                    if not isinstance(c, dict) or "type" not in c or "amount" not in c:
                        errors.append(f"Row {idx} ({bid}): Invalid charge item: {c}")
                    elif c["type"] not in VALID_CHARGE_TYPES:
                        errors.append(f"Row {idx} ({bid}): Invalid charge type: {c['type']}")
                    elif not isinstance(c["amount"], (int, float)):
                        errors.append(f"Row {idx} ({bid}): Charge amount must be a number: {c['amount']}")

            # Check taxes
            taxes = data.get("taxes")
            if not isinstance(taxes, list):
                errors.append(f"Row {idx} ({bid}): 'taxes' must be a list")
            else:
                for t in taxes:
                    if not isinstance(t, dict) or "type" not in t or "amount" not in t:
                        errors.append(f"Row {idx} ({bid}): Invalid tax item: {t}")
                    elif t["type"] not in VALID_TAX_TYPES:
                        errors.append(f"Row {idx} ({bid}): Invalid tax type: {t['type']}")
                    elif not isinstance(t["amount"], (int, float)):
                        errors.append(f"Row {idx} ({bid}): Tax amount must be a number: {t['amount']}")

            # Check date formats
            for date_key in ["reading_date", "issue_date", "due_date"]:
                val = data.get(date_key)
                if val is not None and not re.match(r"^\d{4}-\d{2}-\d{2}$", str(val)):
                    errors.append(f"Row {idx} ({bid}): {date_key} '{val}' does not match YYYY-MM-DD")

            bm = data.get("bill_month")
            if bm is not None and not re.match(r"^\d{4}-\d{2}$", str(bm)):
                errors.append(f"Row {idx} ({bid}): bill_month '{bm}' does not match YYYY-MM")

    return errors


def validate_level2_csv(csv_path: Path, expected_count: int = 120) -> List[str]:
    """Validates level2.csv formatting, non-empty answers, and columns."""
    errors: List[str] = []
    if not csv_path.exists():
        return [f"File does not exist: {csv_path}"]

    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != ["bill_id", "question_id", "question", "answer"]:
            errors.append(
                f"Invalid column names in level2.csv: {reader.fieldnames}. "
                "Expected ['bill_id', 'question_id', 'question', 'answer']"
            )

        rows = list(reader)
        if len(rows) != expected_count:
            errors.append(f"Expected {expected_count} rows in level2.csv, but found {len(rows)}.")

        for idx, row in enumerate(rows, start=1):
            bid = row.get("bill_id", "")
            qid = row.get("question_id", "")
            ans = row.get("answer", "")

            if not bid:
                errors.append(f"Row {idx}: missing bill_id")
            if not qid:
                errors.append(f"Row {idx}: missing question_id")
            if not ans or not ans.strip():
                errors.append(f"Row {idx} ({bid}, {qid}): empty answer cell")

    return errors


if __name__ == "__main__":
    import sys
    out_dir = Path("output")
    l1_errors = validate_level1_csv(out_dir / "level1.csv")
    l2_errors = validate_level2_csv(out_dir / "level2.csv")

    if l1_errors or l2_errors:
        print("Validation FAILED with errors:")
        for e in l1_errors + l2_errors:
            print(f"  - {e}")
        sys.exit(1)
    else:
        print("Validation PASSED: Both CSV files conform exactly to competition requirements.")
