import time
import logging
from typing import Optional
from google import genai
from google.genai import types
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)
from .config import MODEL_NAME, API_KEY, validate_config

logger = logging.getLogger(__name__)


class GeminiClientWrapper:
    """
    Wrapper around the official Google Gen AI SDK client.
    Handles rate-limiting (respecting the 15 RPM free-tier limit) and retries with backoff.
    """

    def __init__(self, api_key: Optional[str] = None, model_name: Optional[str] = None):
        validate_config(require_api_key=True)
        self.api_key = api_key or API_KEY
        self.model_name = model_name or MODEL_NAME
        self.client = genai.Client(api_key=self.api_key)
        self.min_request_interval = 4.2  # Ensures <= 14.2 requests/minute to stay under 15 RPM
        self._last_request_time = 0.0

    def _wait_for_rate_limit(self):
        """Enforces spacing between calls to avoid hitting 15 RPM rate limits."""
        now = time.time()
        elapsed = now - self._last_request_time
        if elapsed < self.min_request_interval:
            sleep_time = self.min_request_interval - elapsed
            logger.debug(f"Rate limiting: sleeping for {sleep_time:.2f} seconds...")
            time.sleep(sleep_time)
        self._last_request_time = time.time()

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=2, min=4, max=30),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    def generate_content(
        self,
        contents: list,
        system_instruction: Optional[str] = None,
        response_mime_type: Optional[str] = None,
        temperature: float = 0.1,
    ) -> str:
        """
        Executes a call to the Gemini model with rate limit throttling and retries.
        """
        self._wait_for_rate_limit()

        config_args = {
            "temperature": temperature,
            "automatic_function_calling": types.AutomaticFunctionCallingConfig(disable=True),
        }
        if system_instruction:
            config_args["system_instruction"] = system_instruction
        if response_mime_type:
            config_args["response_mime_type"] = response_mime_type

        config = types.GenerateContentConfig(**config_args)

        response = self.client.models.generate_content(
            model=self.model_name,
            contents=contents,
            config=config,
        )

        if not response or not response.text:
            raise RuntimeError("Empty response received from Gemini model.")

        return response.text.strip()
