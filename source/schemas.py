import re
import json
from typing import Literal, List, Optional, Union, Dict, Any
from pydantic import BaseModel, Field, field_validator, model_validator

# Allowed charge types per guide section 5.4.1
ChargeType = Literal[
    "energy",
    "fixed",
    "fpa",
    "quarterly_adjustment",
    "surcharge",
    "meter_rent",
    "subsidy",
    "other",
]

# Allowed tax types per guide section 5.4.2
TaxType = Literal[
    "gst",
    "electricity_duty",
    "income_tax",
    "municipal_tax",
    "other_tax",
]

# Allowed providers per guide section 5.3
ProviderType = Literal["KE", "LESCO", "IESCO"]

MONTHS = {
    "jan": "01", "feb": "02", "mar": "03", "apr": "04", "may": "05", "jun": "06",
    "jul": "07", "aug": "08", "sep": "09", "oct": "10", "nov": "11", "dec": "12"
}


def clean_numeric(v: Any) -> Optional[Union[int, float]]:
    """Cleans numeric values, removes currency prefixes, and handles credits/negatives."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return v
    s = str(v).strip()
    if s.lower() in ["", "null", "none", "-", "n/a", "not to be paid"]:
        return None

    clean = s.replace("Rs.", "").replace("PKR", "").replace(",", "").strip()
    is_credit = "cr" in clean.lower()
    clean = re.sub(r"[Cc][Rr]", "", clean).strip()

    # Handle fractions (e.g. 39411 / 2)
    if "/" in clean:
        parts = clean.split("/")
        try:
            val = float(parts[0].strip()) / float(parts[1].strip())
            return int(val) if val.is_integer() else val
        except Exception:
            clean = parts[0].strip()

    try:
        num = float(clean)
        if is_credit and num > 0:
            num = -num
        return int(num) if num.is_integer() else num
    except (ValueError, TypeError):
        return None


def normalize_date(v: Any) -> Optional[str]:
    """Converts dates to strict YYYY-MM-DD format."""
    if not v or not str(v).strip():
        return None
    s = str(v).strip()
    if s.lower() in ["null", "none", "-", "n/a"]:
        return None
    if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        return s

    # Remove ordinals (st, nd, rd, th)
    clean = re.sub(r"(st|nd|rd|th)", "", s, flags=re.IGNORECASE)
    # Match patterns like: 22 Sep 2026, 17-JUL-26, 03-Apr-2026, 2026/09/25
    m = re.search(r"(\d{1,2})[-/\s]+([A-Za-z]{3,9})[-/\s]+(\d{2,4})", clean)
    if m:
        day, mon, yr = m.groups()
        mon_num = MONTHS.get(mon.lower()[:3])
        if len(yr) == 2:
            yr = "20" + yr
        if mon_num:
            return f"{yr}-{mon_num}-{int(day):02d}"

    # Match ISO-like with slash: 2026/09/25
    m_iso = re.search(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", s)
    if m_iso:
        yr, mon, day = m_iso.groups()
        return f"{yr}-{int(mon):02d}-{int(day):02d}"

    return None


def normalize_month(v: Any) -> Optional[str]:
    """Converts billing month to strict YYYY-MM format."""
    if not v or not str(v).strip():
        return None
    s = str(v).strip()
    if s.lower() in ["null", "none", "-", "n/a"]:
        return None
    if re.match(r"^\d{4}-\d{2}$", s):
        return s

    # E.g. MAR 2026, Jun-26, 04/26
    m = re.search(r"([A-Za-z]{3,9})[-/\s]+(\d{2,4})", s)
    if m:
        mon, yr = m.groups()
        mon_num = MONTHS.get(mon.lower()[:3])
        if len(yr) == 2:
            yr = "20" + yr
        if mon_num:
            return f"{yr}-{mon_num}"

    m2 = re.search(r"(\d{2,4})[-/\s]+([A-Za-z]{3,9})", s)
    if m2:
        yr, mon = m2.groups()
        mon_num = MONTHS.get(mon.lower()[:3])
        if len(yr) == 2:
            yr = "20" + yr
        if mon_num:
            return f"{yr}-{mon_num}"

    # E.g. 2026-04 or 04/26 or 04/2026
    m_num = re.search(r"(\d{1,2})[-/](\d{2,4})", s)
    if m_num:
        mon, yr = m_num.groups()
        if len(yr) == 2:
            yr = "20" + yr
        return f"{yr}-{int(mon):02d}"

    return None


class ChargeItem(BaseModel):
    type: ChargeType
    amount: Union[int, float]

    @field_validator("amount", mode="before")
    @classmethod
    def validate_amount(cls, v: Any) -> Union[int, float]:
        res = clean_numeric(v)
        if res is None:
            raise ValueError(f"Invalid charge amount: {v}")
        return res

    @model_validator(mode="after")
    def ensure_subsidy_negative(self) -> "ChargeItem":
        # Subsidies and relief lines must be negative per guide section 5.2
        if self.type == "subsidy" and self.amount > 0:
            self.amount = -self.amount
        return self


class TaxItem(BaseModel):
    type: TaxType
    amount: Union[int, float]

    @field_validator("amount", mode="before")
    @classmethod
    def validate_amount(cls, v: Any) -> Union[int, float]:
        res = clean_numeric(v)
        if res is None:
            raise ValueError(f"Invalid tax amount: {v}")
        return res


class Level1Bill(BaseModel):
    provider: ProviderType
    tariff: Optional[str] = None
    sanctioned_load_kw: Optional[Union[int, float]] = None
    bill_month: Optional[str] = None
    reading_date: Optional[str] = None
    issue_date: Optional[str] = None
    due_date: Optional[str] = None
    previous_reading: Optional[Union[int, float]] = None
    current_reading: Optional[Union[int, float]] = None
    units_consumed: Optional[Union[int, float]] = None
    charges: List[ChargeItem] = Field(default_factory=list)
    total_charges: Optional[Union[int, float]] = None
    taxes: List[TaxItem] = Field(default_factory=list)
    total_taxes: Optional[Union[int, float]] = None
    current_bill: Optional[Union[int, float]] = None
    arrears: Optional[Union[int, float]] = None
    payable_within_due_date: Optional[Union[int, float]] = None
    payable_after_due_date: Optional[Union[int, float]] = None

    @field_validator("provider", mode="before")
    @classmethod
    def validate_provider(cls, v: Any) -> str:
        s = str(v).strip().upper()
        if "KESC" in s or "KE" in s or "K-ELECTRIC" in s or "KARACHI" in s:
            return "KE"
        if "LESCO" in s or "LAHORE" in s:
            return "LESCO"
        if "IESCO" in s or "ISLAMABAD" in s:
            return "IESCO"
        return s

    @field_validator(
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
        mode="before",
    )
    @classmethod
    def clean_numerics(cls, v: Any) -> Optional[Union[int, float]]:
        return clean_numeric(v)

    @field_validator("reading_date", "issue_date", "due_date", mode="before")
    @classmethod
    def validate_dates(cls, v: Any) -> Optional[str]:
        return normalize_date(v)

    @field_validator("bill_month", mode="before")
    @classmethod
    def validate_month(cls, v: Any) -> Optional[str]:
        return normalize_month(v)

    @field_validator("charges", mode="before")
    @classmethod
    def clean_charges_list(cls, v: Any) -> List[Any]:
        if not isinstance(v, list):
            return []
        cleaned = []
        for item in v:
            if isinstance(item, dict):
                amt = clean_numeric(item.get("amount"))
                # Guide 5.3: Skip blank lines and lines printed as 0
                if amt is not None and amt != 0:
                    cleaned.append(item)
            elif isinstance(item, ChargeItem):
                if item.amount != 0:
                    cleaned.append(item)
        return cleaned

    @field_validator("taxes", mode="before")
    @classmethod
    def clean_taxes_list(cls, v: Any) -> List[Any]:
        if not isinstance(v, list):
            return []
        cleaned = []
        for item in v:
            if isinstance(item, dict):
                amt = clean_numeric(item.get("amount"))
                # Guide 5.3: Skip blank lines and lines printed as 0
                if amt is not None and amt != 0:
                    cleaned.append(item)
            elif isinstance(item, TaxItem):
                if item.amount != 0:
                    cleaned.append(item)
        return cleaned

    def to_submission_json(self) -> str:
        """
        Serializes model into exact Level 1 JSON format matching section 5.1 & 5.7.
        All fields are preserved, nulls are explicit, and output is on a single line.
        """
        data = self.model_dump(mode="json")
        ordered_keys = [
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
        ordered_dict = {k: data.get(k, None) for k in ordered_keys}
        return json.dumps(ordered_dict, separators=(",", ":"), ensure_ascii=False)
