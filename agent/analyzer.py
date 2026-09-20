"""Firmware analyzer module: source with line numbers -> FirmwareAnalysis."""

from pathlib import Path
from google import genai
from agent.llm import generate_json
from agent.models import FirmwareAnalysis
from agent.prompts import make_analyzer_prompt


def add_line_numbers(source_code: str) -> str:
    """Prefix source code with 1-based line numbers.

    Example output:
      1: /*
      2:  * FAN CONTROLLER FIRMWARE
    """
    lines = source_code.splitlines()
    return "\n".join(f"{idx + 1:3d}: {line}" for idx, line in enumerate(lines))


def analyze_firmware(
    source_code: str,
    client: genai.Client | None = None,
    model: str | None = None,
    use_cache: bool = True,
    cache_dir: Path | None = None,
) -> FirmwareAnalysis:
    """Analyze firmware source code and return a structured FirmwareAnalysis.

    Security & Scope:
    - Receives ONLY the numbered source code. Never passes docs/, .env, or secrets.
    - Spec rules are extracted from specification comments with confidence='spec'.
    - If no specification is present, rules are inferred with confidence='inferred'.
    - Maps rule implementations to suspect or target source lines.
    - Identifies risk areas where logic may diverge from specification.
    """
    numbered_source = add_line_numbers(source_code)
    prompt = make_analyzer_prompt(numbered_source)

    analysis: FirmwareAnalysis = generate_json(
        prompt=prompt,
        schema_model=FirmwareAnalysis,
        client=client,
        model=model,
        use_cache=use_cache,
        cache_dir=cache_dir,
    )
    return analysis
