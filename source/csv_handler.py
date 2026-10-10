import csv
import json
from pathlib import Path
from typing import Dict, List, Tuple, Union, Optional
from .schemas import Level1Bill

REQUIRED_L1_KEYS = [
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
]


def read_level1_template(template_path: Union[str, Path]) -> List[str]:
    """
    Reads level1.csv template and returns bill_ids preserving original row order.
    Checks for duplicate rows and invalid headers.
    """
    template_path = Path(template_path)
    if not template_path.exists():
        raise FileNotFoundError(f"level1.csv template not found: {template_path}")

    bill_ids: List[str] = []
    seen: set = set()

    with open(template_path, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if "bill_id" not in (reader.fieldnames or []):
            raise ValueError(
                f"Invalid level1.csv template: Missing 'bill_id' column. Found: {reader.fieldnames}"
            )

        for line_num, row in enumerate(reader, start=2):
            bid = row.get("bill_id", "").strip()
            if not bid:
                raise ValueError(f"Line {line_num} in {template_path}: Missing bill_id.")
            if bid in seen:
                raise ValueError(f"Line {line_num} in {template_path}: Duplicate bill_id '{bid}' found.")
            seen.add(bid)
            bill_ids.append(bid)

    if not bill_ids:
        raise ValueError(f"Template {template_path} is empty or contains no bill rows.")

    return bill_ids


def read_level2_template(
    template_path: Union[str, Path]
) -> List[Tuple[str, str, str]]:
    """
    Reads level2.csv template and returns list of (bill_id, question_id, question)
    preserving exact original row order.
    Checks for duplicate rows and missing fields.
    """
    template_path = Path(template_path)
    if not template_path.exists():
        raise FileNotFoundError(f"level2.csv template not found: {template_path}")

    rows: List[Tuple[str, str, str]] = []
    seen: set = set()

    with open(template_path, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        required_cols = {"bill_id", "question_id", "question"}
        if not required_cols.issubset(set(reader.fieldnames or [])):
            raise ValueError(
                f"Invalid level2.csv template: Missing required columns {required_cols}. "
                f"Found: {reader.fieldnames}"
            )

        for line_num, row in enumerate(reader, start=2):
            bid = row.get("bill_id", "").strip()
            qid = row.get("question_id", "").strip()
            qtext = row.get("question", "").strip()

            if not bid:
                raise ValueError(f"Line {line_num} in {template_path}: Missing bill_id.")
            if not qid:
                raise ValueError(f"Line {line_num} in {template_path}: Missing question_id.")
            if not qtext:
                raise ValueError(f"Line {line_num} in {template_path}: Missing question text.")

            key = (bid, qid)
            if key in seen:
                raise ValueError(
                    f"Line {line_num} in {template_path}: Duplicate ({bid}, {qid}) found."
                )
            seen.add(key)
            rows.append((bid, qid, qtext))

    if not rows:
        raise ValueError(f"Template {template_path} is empty or contains no question rows.")

    return rows


def write_level1_csv(
    output_path: Union[str, Path],
    bill_ids: List[str],
    bills_dict: Dict[str, Level1Bill],
) -> None:
    """
    Writes completed level1.csv maintaining exact column names and row order.
    Enforces:
    - Single-line JSON format.
    - Python standard CSV quote escaping (quotes doubled).
    - UTF-8 encoding.
    - Validation that every required JSON key is present.
    - Fails if any bill is missing or empty.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, quoting=csv.QUOTE_MINIMAL)
        writer.writerow(["bill_id", "json"])

        for bid in bill_ids:
            if bid not in bills_dict:
                raise ValueError(f"Missing Level 1 extraction for bill_id '{bid}'")

            bill = bills_dict[bid]
            json_str = bill.to_submission_json()

            if not json_str or not json_str.strip():
                raise ValueError(f"Empty JSON string generated for bill_id '{bid}'")

            # Validate that the JSON deserializes cleanly and has all required fields
            parsed = json.loads(json_str)
            missing = set(REQUIRED_L1_KEYS) - set(parsed.keys())
            if missing:
                raise ValueError(f"Bill '{bid}' JSON is missing required fields: {missing}")

            # Enforce single line strictly
            single_line_json = json_str.replace("\r", "").replace("\n", "").strip()
            writer.writerow([bid, single_line_json])


def write_level2_csv(
    output_path: Union[str, Path],
    template_rows: List[Tuple[str, str, str]],
    answers_dict: Dict[Tuple[str, str], str],
) -> None:
    """
    Writes completed level2.csv preserving exact original columns and order.
    Enforces:
    - Exactly matches template rows.
    - No empty or whitespace-only answers allowed.
    - UTF-8 encoding with standard RFC 4180 CSV escaping.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, quoting=csv.QUOTE_MINIMAL)
        writer.writerow(["bill_id", "question_id", "question", "answer"])

        for bid, qid, qtext in template_rows:
            key = (bid, qid)
            if key not in answers_dict:
                raise ValueError(f"Missing answer for required row: ({bid}, {qid})")

            ans = answers_dict[key].strip()
            if not ans:
                raise ValueError(f"Empty answer generated for row: ({bid}, {qid})")

            writer.writerow([bid, qid, qtext, ans])
