# WTQ Utility Bill Decoder - Solution Guide

An AI-powered assistant designed for the Women Tech Quest (WTQ) Build Track to decode, extract, and explain Pakistani electricity bills (K-Electric, LESCO, IESCO).

---

## 1. Runtime & Environment

- **Python Version:** Python 3.13 (Python 3.11+ compliant)
- **Primary LLM:** Google Gemini 3.5 Flash-Lite (`gemini-3.5-flash-lite`) via Google AI Studio API
- **Official SDK:** `google-genai` (v2.20.0)
- **Validation Framework:** `pydantic` (v2.13.5)

---

## 2. Architecture & File Structure

The project is structured modularly under `source/`:

```text
source/
├── __init__.py           # Package marker
├── config.py             # Loads .env; verifies approved model (gemini-3.5-flash-lite / gemini-3.1-flash-lite)
├── schemas.py            # Strict Pydantic models for Level 1 JSON schema with numeric & date cleaning
├── client.py             # Official Google Gen AI SDK client with 15 RPM rate limiting & exponential retry
├── calculator.py         # Deterministic calculations in Python (percentages, units diff, surcharge, subtotals)
├── extractor.py          # Multimodal Level 1 bill extractor with few-shot KESC_0008 guidance & JSON repair
├── explainer.py          # Grounded Level 2 QA engine (batching, fallback guarantee, zero outside assumptions)
├── csv_handler.py        # Template readers, duplicate checkers, and RFC-4180 compliant CSV writers
├── runner.py             # Main CLI pipeline supporting smart path resolution and progress summary
├── validate.py           # Pre-submission verification script checking all guide rules and non-empty cells
├── requirements.txt      # Pinned exact package dependencies
├── .env.example          # Environment variable template with placeholders
├── README.md             # This comprehensive solution documentation
└── tests/                # Comprehensive automated test suite
    ├── test_audit.py     # 8 end-to-end competition audit tests
    ├── test_extraction.py# Level 1 regression and normalization tests
    └── test_explainer.py # Level 2 grounded QA and calculation tests
```

---

## 3. Setup & Installation

### Step 1: Install Dependencies

From the project root:

```bash
pip install -r source/requirements.txt
```

Pinned dependencies in `source/requirements.txt`:
- `google-genai==2.20.0`
- `pydantic==2.13.5`
- `python-dotenv==1.2.3`
- `tenacity==9.1.4`
- `pytest==9.1.1`

### Step 2: Configure Environment Variables

Copy `source/.env.example` to `.env` in the root workspace:

```bash
cp source/.env.example .env
```

Set your Google AI Studio API key in `.env`:
```env
MODEL_PROVIDER=google
MODEL_NAME=gemini-3.5-flash-lite
API_KEY=your-actual-gemini-api-key-here
```

*Note: Per competition rules, `.env` and real API keys are never included in the submission archive.*

---

## 4. Exact Run Commands

### End-to-End Execution (Test Dataset)

To run the complete pipeline on the 10 test bills and generate both `output/level1.csv` and `output/level2.csv`:

```bash
python run.py
```

*(Alternatively, via module with explicit paths):*
```bash
python -m source.runner --test-dir data/test --output-dir output
```

### Run Extraction Only (Level 1)

```bash
python run.py --level1-only
```

### Validate Output CSV Files

To run automated checks on the generated CSV files:

```bash
python -m source.validate
```

### Run the Automated Test Suite

```bash
python -m pytest tests/ -v
```

### Build Submission ZIP Archive

```bash
python package_submission.py
```

---

## 5. Output Formats

### Level 1: `output/level1.csv`
- Exactly 10 rows (one row per test bill).
- Columns: `bill_id,json`.
- Each `json` cell contains a single-line JSON string representing all 18 required fields:
  `provider`, `tariff`, `sanctioned_load_kw`, `bill_month`, `reading_date`, `issue_date`, `due_date`, `previous_reading`, `current_reading`, `units_consumed`, `charges`, `total_charges`, `taxes`, `total_taxes`, `current_bill`, `arrears`, `payable_within_due_date`, `payable_after_due_date`.
- Values are printed numbers (not strings, no currency symbols).
- Credits and subsidies are negative numbers.
- Missing, covered, or unreadable values are explicit `null`.
- Single-line JSON with standard RFC-4180 CSV quote doubling (`""`).

### Level 2: `output/level2.csv`
- Exactly 120 rows (12 questions per bill across 10 bills).
- Columns: `bill_id,question_id,question,answer`.
- Preserves the exact original row order and question text from the template.
- Plain English answers strictly grounded in the bill.
- Estimates are explicitly labeled (e.g., `"Estimated at..."`) with the formula used.
- All 120 answer cells are non-empty.

---

## 6. Error Handling & Robustness

1. **Rate Limit Throttling (15 RPM):**
   - The free tier rate limit is 15 requests per minute.
   - `GeminiClientWrapper` enforces a minimum 4.2-second delay between calls.
   - Level 2 questions are batched into 1 multimodal call per bill (10 calls total instead of 120), keeping execution well below rate limits.
2. **Transient Error Backoff:**
   - Decorated with `tenacity` exponential backoff retrying on HTTP 429, 503, and transient network errors.
3. **JSON Syntax Auto-Repair:**
   - `clean_json_response` strips markdown fences and repairs trailing commas.
   - If syntax errors occur, a fallback model repair pass fixes the syntax without modifying values.
4. **Deterministic Arithmetic:**
   - `calculator.py` computes percentages, reading differences, and late surcharges in Python, providing verified figures to prevent arithmetic hallucinations.
5. **PII Redaction:**
   - Prompts strictly forbid extracting names, addresses, CNICs, or meter numbers.
   - Answers pass through regex sanitization redacting potential CNIC sequences.
6. **Zero-Empty Guarantee & Clear Failure:**
   - If a batch query misses any question, an individual question fallback is invoked.
   - If any required image or row fails, the pipeline fails clearly rather than substituting fake answers.

---

## 7. AI Usage Disclosure

Per Section 7.4 of the WTQ Competition Guide:

- **AI Models called by solution:**
  - `gemini-3.5-flash-lite` (Google AI Studio API)
- **AI APIs and Cloud Services:**
  - Google AI Studio (Gemini API)
- **AI Coding Assistants used to write code:**
  - Antigravity Coding Assistant (DeepMind)
- **Invoice/Receipt Extraction Agents or Azure Services:**
  - none (strictly prohibited; none used)
- **Other AI tools:**
  - none
