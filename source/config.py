import os
from pathlib import Path
from dotenv import load_dotenv

# Search for .env in current directory and parent directory
env_path = Path(".env")
if not env_path.exists():
    env_path = Path(__file__).resolve().parent / ".env"
if not env_path.exists():
    env_path = Path(__file__).resolve().parent.parent / ".env"

if env_path.exists():
    load_dotenv(dotenv_path=env_path)
else:
    load_dotenv()

# Allowed models per WTQ Guide Section 9.1
ALLOWED_GEMINI_MODELS = {
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
}

MODEL_PROVIDER = os.getenv("MODEL_PROVIDER", "google").strip().lower()
MODEL_NAME = os.getenv("MODEL_NAME", "gemini-3.5-flash-lite").strip()
API_KEY = os.getenv("API_KEY", os.getenv("GEMINI_API_KEY", "")).strip()


def validate_config(require_api_key: bool = True) -> None:
    """Validates model provider, model name, and API key against competition rules."""
    if MODEL_PROVIDER != "google":
        raise ValueError(
            f"Invalid MODEL_PROVIDER='{MODEL_PROVIDER}'. "
            f"Only Google Gemini models ('google') are configured for this solution."
        )

    if MODEL_NAME not in ALLOWED_GEMINI_MODELS:
        raise ValueError(
            f"Disallowed MODEL_NAME='{MODEL_NAME}'. Per WTQ Competition Rules Section 9.1, "
            f"allowed Gemini models are: {sorted(list(ALLOWED_GEMINI_MODELS))}. "
            "Using unapproved LLMs leads to disqualification."
        )

    if require_api_key and not API_KEY:
        raise ValueError(
            "API_KEY is not set in environment or .env file. "
            "Please configure API_KEY with your Google AI Studio key."
        )
