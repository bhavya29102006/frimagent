"""Gemini LLM wrapper using google-genai with JSON output, validation, retry, and disk caching."""

from pathlib import Path
from typing import TypeVar
import hashlib
import json
import os
import time
from dotenv import load_dotenv
from google import genai
from google.genai import types
from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)

DEFAULT_CACHE_DIR = Path(__file__).resolve().parent.parent / "runs" / "cache"


def get_gemini_config() -> tuple[str, str]:
    """Retrieve Gemini API key and model from environment (.env).

    Raises:
        ValueError: If GEMINI_API_KEY is not set or empty.
    """
    load_dotenv()
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash").strip()
    if not api_key:
        raise ValueError("GEMINI_API_KEY is not set. Please configure it in .env.")
    return api_key, model


def _strip_json_fences(text: str) -> str:
    """Remove markdown code blocks if the LLM wrapped the JSON output in backticks."""
    s = text.strip()
    if s.startswith("```json"):
        s = s[7:]
    elif s.startswith("```"):
        s = s[3:]
    if s.endswith("```"):
        s = s[:-3]
    return s.strip()


def _is_retryable_error(exc: Exception) -> bool:
    """Check whether an exception is a transient error (429, 503, or timeout)."""
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return True
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    if code in (429, 503):
        return True
    err_str = str(exc).lower()
    retryable_terms = (
        "503",
        "service unavailable",
        "unavailable",
        "429",
        "resource_exhausted",
        "rate limit",
        "quota",
        "timeout",
        "timed out",
        "connection reset",
        "connection error",
        "connection closed",
    )
    return any(term in err_str for term in retryable_terms)


def _call_gemini_with_backoff(
    client: genai.Client,
    model: str,
    prompt: str,
    max_attempts: int = 5,
) -> str:
    """Invoke Gemini with response_mime_type='application/json' and exponential backoff.

    Backoff sequence: 2s, 4s, 8s, 16s (max 5 attempts) for 503, 429, and timeouts.
    If GEMINI_FALLBACK_MODEL is set, switches to that model after 3 failed attempts.
    Prints a short status message on each retry (never API keys).
    """
    load_dotenv()
    fallback_model = os.environ.get("GEMINI_FALLBACK_MODEL", "").strip() or None
    current_model = model
    delays = [2, 4, 8, 16]

    for attempt in range(max_attempts):
        if attempt >= 3 and fallback_model:
            current_model = fallback_model

        try:
            config = types.GenerateContentConfig(
                response_mime_type="application/json",
            )
            response = client.models.generate_content(
                model=current_model,
                contents=prompt,
                config=config,
            )
            if not response.text:
                raise ValueError("Empty response received from Gemini.")
            return response.text
        except Exception as exc:
            if _is_retryable_error(exc) and attempt < max_attempts - 1:
                delay = delays[attempt] if attempt < len(delays) else 16
                next_attempt = attempt + 2
                print(f"Gemini busy, retry {next_attempt}/{max_attempts} in {delay}s")
                time.sleep(delay)
                continue
            raise


def generate_json(
    prompt: str,
    schema_model: type[T],
    client: genai.Client | None = None,
    model: str | None = None,
    use_cache: bool = True,
    cache_dir: Path | None = None,
) -> T:
    """Generate structured JSON from Gemini and validate against schema_model.

    Features:
    - Injects schema_model.model_json_schema() into prompt.
    - Uses response_mime_type='application/json' without passing response_schema
      (avoiding additionalProperties errors on Developer API mode).
    - Strips markdown code fences if present, then parses and validates with Pydantic.
    - Disk cache in runs/cache/ keyed by SHA-256 hash of prompt + schema.
    - One automatic repair retry containing the Pydantic validation error.
    - Exponential backoff (2s, 4s, 8s, 16s, max 5 attempts) on 503, 429, timeouts.
    - Optional fallback model after 3 failures via GEMINI_FALLBACK_MODEL.
    - Never prints or leaks API keys.

    Args:
        prompt: Prompt instructions sent to the model.
        schema_model: Target Pydantic model class for validation.
        client: Optional pre-configured genai.Client (used for testing).
        model: Model name string. If omitted, read from GEMINI_MODEL env var.
        use_cache: Whether to check/store responses in the disk cache.
        cache_dir: Cache directory path (defaults to runs/cache/).

    Returns:
        Validated instance of schema_model.
    """
    target_cache_dir = cache_dir if cache_dir is not None else DEFAULT_CACHE_DIR

    # 1. Build prompt with embedded JSON schema
    schema_json_str = json.dumps(schema_model.model_json_schema(), indent=2)
    full_prompt = (
        f"{prompt}\n\n"
        f"JSON SCHEMA:\n"
        f"{schema_json_str}\n\n"
        f"Return ONLY valid JSON matching this schema. No markdown."
    )

    # 2. Check disk cache (includes schema in the hash key)
    schema_key_str = json.dumps(schema_model.model_json_schema(), sort_keys=True)
    cache_payload = f"{prompt}\n{schema_key_str}"
    prompt_hash = hashlib.sha256(cache_payload.encode("utf-8")).hexdigest()
    cache_file = target_cache_dir / f"{prompt_hash}.json"

    if use_cache and cache_file.is_file():
        try:
            cached_text = cache_file.read_text(encoding="utf-8")
            return schema_model.model_validate_json(cached_text)
        except Exception:
            # Corrupted cache file, proceed with live call
            pass

    # 3. Prepare client and model
    if client is None or model is None:
        env_key, env_model = get_gemini_config()
        if client is None:
            client = genai.Client(api_key=env_key)
        if model is None:
            model = env_model

    # 4. Call Gemini
    raw_text = _call_gemini_with_backoff(
        client=client,
        model=model,
        prompt=full_prompt,
    )
    cleaned = _strip_json_fences(raw_text)

    # 5. Validate with Pydantic; repair retry if validation fails
    try:
        validated = schema_model.model_validate_json(cleaned)
    except (ValidationError, ValueError) as val_err:
        repair_prompt = (
            f"{full_prompt}\n\n"
            f"PREVIOUS ATTEMPT OUTPUT:\n{raw_text}\n\n"
            f"VALIDATION ERROR:\n{val_err}\n\n"
            f"Please fix the error and return ONLY valid JSON matching the schema. No markdown."
        )
        repaired_raw = _call_gemini_with_backoff(
            client=client,
            model=model,
            prompt=repair_prompt,
        )
        repaired_cleaned = _strip_json_fences(repaired_raw)
        validated = schema_model.model_validate_json(repaired_cleaned)

    # 6. Store in disk cache
    if use_cache:
        target_cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(validated.model_dump_json(indent=2), encoding="utf-8")

    return validated
