import re
import json
import logging
from pathlib import Path
from typing import Union, Optional, Dict, Any
from google.genai import types

from .client import GeminiClientWrapper
from .schemas import Level1Bill

logger = logging.getLogger(__name__)

LEVEL1_SYSTEM_INSTRUCTION = """You are a senior forensic utility bill data extraction specialist for Pakistani electricity bills (K-Electric / KE, LESCO, IESCO).
Your task is to accurately extract billing details from scanned images, tilted photos, or screenshots into a single strict JSON object.

CRITICAL INSTRUCTIONS & SCHEMA RULES:
1. PROVIDER:
   - Must be exactly one of: "KE", "LESCO", "IESCO".
   - K-Electric bills (or images with filename starting with KESC) must ALWAYS be assigned provider "KE".
   - Lahore Electric Supply Company bills are "LESCO".
   - Islamabad Electric Supply Company bills are "IESCO".

2. TILTED, SKEWED & LOW QUALITY IMAGES:
   - Bills may be photographed at an angle, folded, slightly blurry, or shadow-covered.
   - Mentally rotate and correct perspective to read all text, tables, and numeric boxes accurately.

3. URDU AND BILINGUAL TERMS:
   Bills frequently contain Urdu headings alongside English. Common mappings:
   - "سابقہ ریڈنگ" = previous_reading
   - "موجودہ ریڈنگ" = current_reading
   - "یونٹس" = units_consumed
   - "کل چارجز" / "کل بجلی چارجز" = total_charges
   - "رعایت" = subsidy (record as NEGATIVE amount in charges)
   - "ٹیکس" / "قابل ادا ٹیکس" = taxes / total_taxes
   - "موجودہ بل" = current_bill
   - "گزشتہ بقایا جات" / "بقایا جات" = arrears
   - "مقررہ تاریخ تک واجب الادا" = payable_within_due_date
   - "مقررہ تاریخ کے بعد واجب الادا" = payable_after_due_date

4. GREY BOXES & ZERO PII:
   - Grey boxes conceal redacted personal identifiers.
   - NEVER extract names, addresses, CNICs, consumer IDs, reference numbers, or meter numbers.
   - If any required field is covered by a grey box, blank, or unreadable, return null. Never guess or invent.

5. NUMERICS & SIGNS:
   - Extract numbers as numeric values (not strings, no "Rs.", "PKR", no commas).
   - Credits and subsidies are NEGATIVE. E.g., '38209CR' becomes -38209; '54770CR' becomes -54770.
   - Subsidies or relief lines must have negative amounts and type "subsidy".
   - Extract printed values exactly as shown. Do not recalculate, round, or correct amounts.

6. CHARGES SECTION:
   - Allowed types: "energy", "fixed", "fpa", "quarterly_adjustment", "surcharge", "meter_rent", "subsidy", "other".
   - Use "fpa" for both FPA and FCA.
   - Use "quarterly_adjustment" for QTA or Uniform Quarterly Adjustment.
   - PRESERVE MULTIPLE CHARGE LINES OF THE SAME TYPE: If multiple energy slabs or multiple quarterly adjustments appear, keep each non-zero line as a separate entry.
   - SKIP BLANK AND ZERO LINES: Do not include lines printed with 0 or blank amounts.
   - If only a total/combined charge amount is printed without individual line items (common on some LESCO bills), return [] for charges and put that amount in total_charges. Never invent fictional charge breakdown items.
   - total_charges: The printed charges subtotal, or null if no subtotal is printed.

7. TAXES SECTION:
   - Classify a line by its printed section, not its name.
   - Allowed types: "gst", "electricity_duty", "income_tax", "municipal_tax", "other_tax".
   - Use "electricity_duty" for Electricity Duty (ED).
   - Use "municipal_tax" for local/municipal taxes (e.g. KE MUCT / KMC).
   - If only a combined tax subtotal is printed without line items (e.g. "Taxes: 1,723.51"), return [] for taxes and put that amount in total_taxes.
   - total_taxes: The printed tax subtotal, or null if no subtotal is printed.

8. ARREARS & PAYABLE AMOUNTS:
   - arrears: Previous dues carried forward. Keep printed sign (negative if credit). Return null if blank.
   - payable_within_due_date: The amount payable by the due date.
   - payable_after_due_date: The amount payable after the due date. If multiple late-payment dates/amounts are shown, use the highest.

9. EXACT DATE FORMATS:
   - bill_month: 'YYYY-MM' (e.g., '2026-04' for APR 2026 or 04/26).
   - reading_date, issue_date, due_date: 'YYYY-MM-DD' (e.g., '2026-04-21').

WORKED REFERENCE EXAMPLE (KESC_0008):
{
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
    {"type": "surcharge", "amount": 64.93}
  ],
  "total_charges": 2860.62,
  "taxes": [
    {"type": "electricity_duty", "amount": 29.41},
    {"type": "gst", "amount": 520.21},
    {"type": "municipal_tax", "amount": 20}
  ],
  "total_taxes": 569.62,
  "current_bill": 3430.24,
  "arrears": -0.53,
  "payable_within_due_date": 3430,
  "payable_after_due_date": 3716
}
"""


def get_image_mime_type(image_path: Union[str, Path]) -> str:
    ext = Path(image_path).suffix.lower()
    if ext in [".jpg", ".jpeg"]:
        return "image/jpeg"
    elif ext == ".png":
        return "image/png"
    elif ext == ".webp":
        return "image/webp"
    return "application/octet-stream"


def clean_json_response(raw_text: str) -> str:
    """Strips markdown code fences and extraneous text."""
    s = raw_text.strip()
    if s.startswith("```json"):
        s = s[7:]
    elif s.startswith("```"):
        s = s[3:]
    if s.endswith("```"):
        s = s[:-3]
    s = s.strip()

    # Find boundaries of the outermost JSON object
    start_idx = s.find("{")
    end_idx = s.rfind("}")
    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
        s = s[start_idx : end_idx + 1]

    # Clean trailing commas before closing braces/brackets
    s = re.sub(r",\s*([}\]])", r"\1", s)
    return s


class BillExtractor:
    """Extracts Level 1 structured bill data from bill images using Gemini."""

    def __init__(self, client: Optional[GeminiClientWrapper] = None):
        self.client = client or GeminiClientWrapper()

    def _repair_json(self, malformed_text: str) -> Dict[str, Any]:
        """Prompts the model to repair malformed JSON syntax without altering values."""
        repair_prompt = (
            "The following output was intended to be a valid Level 1 JSON object for an electricity bill, "
            "but contains syntax errors. Fix only the syntax to return valid JSON. Do not alter any values, numbers, or keys:\n\n"
            f"{malformed_text}"
        )
        repaired_text = self.client.generate_content(
            contents=[repair_prompt],
            response_mime_type="application/json",
            temperature=0.0,
        )
        cleaned = clean_json_response(repaired_text)
        return json.loads(cleaned)

    def extract(self, image_path: Union[str, Path]) -> Level1Bill:
        image_path = Path(image_path)
        if not image_path.exists():
            raise FileNotFoundError(f"Bill image not found: {image_path}")

        mime_type = get_image_mime_type(image_path)
        with open(image_path, "rb") as f:
            image_bytes = f.read()

        image_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)

        filename_upper = image_path.stem.upper()
        prompt_hint = ""
        if "KESC" in filename_upper or "KE_" in filename_upper:
            prompt_hint = " Note: K-Electric bill; provider must be KE."
        elif "LESCO" in filename_upper:
            prompt_hint = " Note: LESCO bill; provider must be LESCO."
        elif "IESCO" in filename_upper:
            prompt_hint = " Note: IESCO bill; provider must be IESCO."

        prompt = (
            f"Extract all Level 1 fields from this utility bill image ({image_path.name}).{prompt_hint} "
            "Follow all schema constraints, classify lines by section, skip 0 amounts, "
            "preserve negative credits/subsidies, and return ONLY the JSON object."
        )

        response_text = self.client.generate_content(
            contents=[image_part, prompt],
            system_instruction=LEVEL1_SYSTEM_INSTRUCTION,
            response_mime_type="application/json",
            temperature=0.0,
        )

        cleaned_json = clean_json_response(response_text)

        try:
            raw_data = json.loads(cleaned_json)
        except json.JSONDecodeError as e:
            logger.warning(f"Initial JSON decode failed ({e}). Attempting syntax repair...")
            try:
                raw_data = self._repair_json(cleaned_json)
            except Exception as repair_err:
                raise RuntimeError(
                    f"Failed to parse and repair JSON response from model for {image_path.name}: {repair_err}"
                ) from repair_err

        # Enforce provider mapping for KESC filenames
        if "KESC" in filename_upper:
            raw_data["provider"] = "KE"
        elif "LESCO" in filename_upper:
            raw_data["provider"] = "LESCO"
        elif "IESCO" in filename_upper:
            raw_data["provider"] = "IESCO"

        # Validate with strict Pydantic model
        bill = Level1Bill.model_validate(raw_data)
        return bill
