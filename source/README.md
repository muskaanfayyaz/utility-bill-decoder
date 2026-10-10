# WTQ Utility Bill Decoder

AI-powered assistant that reads Pakistani electricity bills (K-Electric, LESCO, IESCO), extracts exact billing details, and answers customer questions with grounded explanations.

Built for the Women Tech Quest (WTQ) Build Track.

---

## Runtime & Environment

- **Runtime:** Python 3.13
- **Primary Model:** Gemini 3.5 Flash-Lite (`gemini-3.5-flash-lite`) via Google AI Studio API
- **SDK:** Official `google-genai` SDK (v2.20.0)

---

## Project Structure

```text
source/
├── __init__.py
├── config.py         # Environment configuration and model authorization checks
├── schemas.py        # Strict Pydantic models for Level 1 JSON schema
├── client.py         # Official Google Gen AI SDK client with rate limiting and retry logic
├── calculator.py     # Deterministic calculations for verified billing metrics
├── extractor.py      # Multimodal Level 1 bill extraction engine with few-shot guidance
├── explainer.py      # Grounded Level 2 question answering engine
├── csv_handler.py    # Robust CSV reading and RFC-4180 compliant writer
├── runner.py         # End-to-end command line pipeline
├── validate.py       # Pre-submission verification script
├── requirements.txt  # Pinned exact package versions
├── .env.example      # Example environment configuration
└── README.md         # Instructions and documentation
```

---

## Setup Instructions

### 1. Install Dependencies

Ensure Python 3.11+ is installed. Install pinned dependencies from `requirements.txt`:

```bash
pip install -r source/requirements.txt
```

### 2. Configure Environment Variables

Copy `.env.example` to `.env` in the project root or `source/` folder and insert your Google AI Studio API key:

```bash
cp source/.env.example .env
```

Edit `.env`:
```env
MODEL_PROVIDER=google
MODEL_NAME=gemini-3.5-flash-lite
API_KEY=your-actual-gemini-api-key-here
```

*Note: Per competition guidelines, the approved models are `gemini-3.5-flash-lite` and `gemini-3.1-flash-lite`. Never commit your real `.env` file.*

---

## Running the Pipeline

### Full Execution on Test Data

To generate both `output/level1.csv` and `output/level2.csv` from test images and templates:

```bash
python -m source.runner --bills-dir data/test/bills --template-dir data/test/csv --output-dir output
```

### Run Extraction Only (Level 1)

```bash
python -m source.runner --bills-dir data/test/bills --template-dir data/test/csv --output-dir output --level1-only
```

### Validate Output CSV Files

To run automated checks on generated CSV files:

```bash
python -m source.validate
```

---

## AI Usage Disclosure

Per Section 7.4 of the WTQ Competition Guide:

- **AI Models called by solution:**
  - `gemini-3.5-flash-lite` (Google AI Studio API)
- **AI APIs and Cloud Services:**
  - Google AI Studio (Gemini API)
- **AI Coding Assistants used to write code:**
  - Antigravity Coding Assistant (DeepMind)
- **Invoice/Receipt Extraction Agents or Azure Services:**
  - none (no prohibited services used; strictly follows competition rules)
- **Other AI tools:**
  - none
