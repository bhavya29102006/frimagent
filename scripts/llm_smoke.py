"""Smoke test script for Gemini LLM wrapper (TASK-004).

Asks Gemini for {"ok": true} and prints the validated Pydantic object.
Run with: python scripts/llm_smoke.py
"""

import sys
from pathlib import Path

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pydantic import BaseModel
from agent.llm import generate_json


class SmokeResponse(BaseModel):
    ok: bool
    message: str = "Connected to Gemini"


def main() -> None:
    print("Connecting to Gemini via agent.llm.generate_json...")
    try:
        response = generate_json(
            prompt="Respond in JSON format with 'ok' set to true and a short greeting in 'message'.",
            schema_model=SmokeResponse,
            use_cache=False,  # Bypass cache to test live connection
        )
        print("Success! Validated response:")
        print(response.model_dump_json(indent=2))
    except Exception as exc:
        # Note: Do not print sensitive API keys
        print(f"Smoke test failed: {type(exc).__name__}: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
