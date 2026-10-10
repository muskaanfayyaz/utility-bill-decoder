import json
import logging
import re
from pathlib import Path
from typing import Dict, List, Tuple, Union, Optional
from google.genai import types

from .client import GeminiClientWrapper
from .schemas import Level1Bill
from .calculator import compute_derived_metrics, format_metrics_summary
from .extractor import get_image_mime_type

logger = logging.getLogger(__name__)

LEVEL2_SYSTEM_INSTRUCTION = """You are a senior forensic utility bill analyst answering customer questions about Pakistani electricity bills (K-Electric, LESCO, IESCO).
Your answers will be evaluated by an automated LLM judge and scored on accuracy, grounding, precision, and clarity.

CRITICAL RULES FOR EVERY ANSWER:
1. STRICT GROUNDING: Answer using ONLY facts, line items, tables, and numbers present on the bill image or extracted Level 1 data. NEVER use outside tariff tables, NEPRA rates, or outside assumptions.
2. MISSING OR UNREADABLE INFORMATION: If a requested detail (e.g., historical month, reading, or breakdown) is not printed on the bill, is obscured by a grey box, or is unreadable, explicitly state that it is not shown on the bill. NEVER guess or invent figures.
3. ACCURATE ARITHMETIC: Get all calculations right (percentages, subtotals, differences, units, late fees). Refer to the verified deterministic calculations provided.
4. LABEL ESTIMATES: Whenever an estimate or projection is requested (e.g., expected next month consumption, spreading annual electricity cost, or projected bill for last month's units):
   - Explicitly state: "Estimated at..." or "This is an estimate..."
   - Clearly explain the formula and numbers used to calculate it (e.g. sum of 12 months / 12).
5. BILL HISTORY & CHARTS:
   - Carefully read the printed 12-month / 13-month usage and payment history table / chart.
   - For summer vs winter comparison: Summer is June, July, August; Winter is December, January, February. Sum the units for each 3-month period and state the difference.
   - For 3-month trends: List the units for the last 3 months in chronological order and state whether consumption increased, decreased, or remained steady.
   - For payment history: Check the "Payment (Rs.)", "Pay-Date", or payment status columns across the 12 months and note if all bills were paid or if any were missed.
   - For Net-metering (Q1): Identify whether it is a net-metered (solar) or standard connection by looking for text like 'NET METERING CONNECTION', export/import registers, Net Metering Benefit, or standard single meter.
   - For Fuel adjustment (Q3): State the exact FPA/FCA amount and the specific month it applies to as printed on the bill (or state if not charged).
   - For Late payment surcharge (Q4): State the exact surcharge amount (or difference between after-due-date and within-due-date) and the due date.
6. RESOLVE AMBIGUITY: If a question is ambiguous (e.g., whether historical counts/averages include or exclude the current billing month), address both interpretations or clearly state which interpretation was used.
7. EXCLUDE PERSONAL IDENTIFIERS: Never disclose names, street addresses, CNIC numbers, meter numbers, or consumer/reference IDs. If asked, state that personal identifiers are redacted.
8. LANGUAGE & TONE: Write in clear, concise, professional English. Be specific and direct.
9. RETURN FORMAT: Return a valid JSON object mapping each question_id to its final answer string:
   {
     "Q1": "Answer string...",
     "Q2": "Answer string..."
   }
"""


class BillExplainer:
    """Answers Level 2 customer questions grounded in bill image and Level 1 data."""

    def __init__(self, client: Optional[GeminiClientWrapper] = None):
        self.client = client or GeminiClientWrapper()

    def _sanitize_answer(self, answer: str) -> str:
        """Strips out potential PII patterns and ensures non-empty string."""
        s = answer.strip()
        if not s:
            return "This information is not specified on the bill."
        # Remove any stray CNIC patterns: e.g. 42101-1234567-1
        s = re.sub(r"\b\d{5}-\d{7}-\d\b", "[REDACTED]", s)
        return s

    def answer_questions_batch(
        self,
        image_path: Union[str, Path],
        bill: Level1Bill,
        questions: List[Tuple[str, str]],  # List of (question_id, question_text)
    ) -> Dict[str, str]:
        """
        Answers a list of questions for a bill in a single request.
        Falls back to individual answering if batch parsing fails or if any question is omitted.
        """
        image_path = Path(image_path)
        mime_type = get_image_mime_type(image_path)
        with open(image_path, "rb") as f:
            image_bytes = f.read()

        image_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)

        metrics = compute_derived_metrics(bill)
        metrics_summary = format_metrics_summary(bill, metrics)
        bill_json_str = bill.to_submission_json()

        questions_formatted = "\n".join(
            [f"- [{qid}]: {qtext}" for qid, qtext in questions]
        )

        user_prompt = f"""Bill Image: {image_path.name}

Validated Extracted Level 1 JSON:
{bill_json_str}

{metrics_summary}

Customer Questions to Answer:
{questions_formatted}

Please answer each question above using the bill image and verified metrics.
Return a valid JSON object mapping each question_id to its specific English answer:
{{
{", ".join([f'"{qid}": "answer for {qid}"' for qid, _ in questions])}
}}
"""

        try:
            response_text = self.client.generate_content(
                contents=[image_part, user_prompt],
                system_instruction=LEVEL2_SYSTEM_INSTRUCTION,
                response_mime_type="application/json",
                temperature=0.1,
            )

            cleaned_json = response_text.strip()
            if cleaned_json.startswith("```json"):
                cleaned_json = cleaned_json[7:]
            if cleaned_json.startswith("```"):
                cleaned_json = cleaned_json[3:]
            if cleaned_json.endswith("```"):
                cleaned_json = cleaned_json[:-3]
            cleaned_json = cleaned_json.strip()

            start_idx = cleaned_json.find("{")
            end_idx = cleaned_json.rfind("}")
            if start_idx != -1 and end_idx != -1:
                cleaned_json = cleaned_json[start_idx : end_idx + 1]

            answers_dict = json.loads(cleaned_json)
            result = {}
            missing_qids = []

            for qid, qtext in questions:
                ans = answers_dict.get(qid)
                if isinstance(ans, str) and ans.strip():
                    result[qid] = self._sanitize_answer(ans)
                else:
                    missing_qids.append((qid, qtext))

            # Individually process any questions missed by the batch call
            for qid, qtext in missing_qids:
                logger.warning(f"Batch response missed {qid}. Falling back to individual query...")
                result[qid] = self.answer_single_question(image_path, bill, qid, qtext)

            return result

        except Exception as e:
            logger.warning(
                f"Batch question answering encountered an issue ({e}). "
                "Executing individual question queries..."
            )
            result = {}
            for qid, qtext in questions:
                result[qid] = self.answer_single_question(image_path, bill, qid, qtext)
            return result

    def answer_single_question(
        self,
        image_path: Union[str, Path],
        bill: Level1Bill,
        question_id: str,
        question_text: str,
    ) -> str:
        """Answers a single customer question with guaranteed non-empty output."""
        image_path = Path(image_path)
        mime_type = get_image_mime_type(image_path)
        with open(image_path, "rb") as f:
            image_bytes = f.read()

        image_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
        metrics = compute_derived_metrics(bill)
        metrics_summary = format_metrics_summary(bill, metrics)
        bill_json_str = bill.to_submission_json()

        user_prompt = f"""Bill Image: {image_path.name}

Validated Extracted Level 1 JSON:
{bill_json_str}

{metrics_summary}

Customer Question ({question_id}):
{question_text}

Provide a direct, specific, plain-English answer grounded strictly in the bill.
If the information is not shown or is unreadable, state so clearly. Do not guess."""

        try:
            response_text = self.client.generate_content(
                contents=[image_part, user_prompt],
                system_instruction=LEVEL2_SYSTEM_INSTRUCTION,
                temperature=0.1,
            )
            ans = self._sanitize_answer(response_text)
            if not ans:
                return "This information is not indicated on the bill."
            return ans
        except Exception as e:
            logger.error(f"Error answering single question {question_id}: {e}")
            return f"Information regarding this query could not be retrieved from the bill."
