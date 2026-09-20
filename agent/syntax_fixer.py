"""Syntax Fixer module: pre-compilation syntax validation and automated LLM repair.

Detects compiler syntax errors using PlatformIO Core (avr-g++), creates safety backups,
prompts Gemini to repair syntax issues (missing semicolons, braces, typos, type errors),
and re-tests compilation before proceeding to the test pipeline.
"""

import difflib
from pathlib import Path
import shutil
from typing import Any, Optional
from google import genai
from pydantic import BaseModel, Field

from agent.analyzer import add_line_numbers
from agent.builder import build_firmware
from agent.llm import generate_json


class SyntaxFixProposal(BaseModel):
    """Schema for LLM-generated syntax repair."""
    explanation: str = Field(description="Summary of syntax errors found and changes made to resolve them.")
    errors_addressed: list[str] = Field(description="List of specific compiler errors resolved (e.g. 'Missing semicolon on line 42').")
    fixed_code: str = Field(description="Complete, corrected C++ source code ready to compile.")


SYNTAX_FIX_PROMPT_TEMPLATE = """You are an expert embedded C/C++ firmware engineer and compiler diagnostics assistant.
The following Arduino/PlatformIO C++ firmware failed to compile with avr-g++.

COMPILER ERROR DIAGNOSTICS:
```
{compiler_log}
```

ORIGINAL SOURCE CODE (WITH LINE NUMBERS):
```cpp
{numbered_source}
```

TASK:
Analyze the compiler diagnostics and fix ALL syntax errors in the source code:
1. Fix missing semicolons (;), unmatched parentheses (()), brackets ([]), or curly braces ({{}}).
2. Fix typo identifiers, incorrect variable/function declarations, missing standard includes (e.g. <Arduino.h>), or incorrect parameter types.
3. PRESERVE ALL business logic, pin assignments, state machines, and hardware definitions. DO NOT rewrite algorithms or alter functionality.
4. Return ONLY valid JSON matching the SyntaxFixProposal schema containing `explanation`, `errors_addressed`, and the complete `fixed_code`.
"""


def check_firmware_syntax(firmware_dir: Path | str) -> tuple[bool, str]:
    """Compile firmware using PlatformIO to check for syntax and build errors.

    Returns:
        tuple[bool, str]: (is_clean, compiler_log_or_tail)
    """
    fw_dir = Path(firmware_dir).resolve()
    success, log_tail, _ = build_firmware(fw_dir)
    return success, log_tail


def restore_firmware_backup(firmware_dir: Path | str) -> bool:
    """Restore src/main.cpp from src/main.cpp.bak if backup exists."""
    fw_dir = Path(firmware_dir).resolve()
    src_file = fw_dir / "src" / "main.cpp"
    bak_file = fw_dir / "src" / "main.cpp.bak"
    if bak_file.is_file():
        shutil.copy2(bak_file, src_file)
        return True
    return False


def auto_fix_syntax_errors(
    firmware_dir: Path | str,
    client: Optional[genai.Client] = None,
    model: Optional[str] = None,
) -> dict[str, Any]:
    """Diagnose compiler syntax errors, invoke Gemini for repair, and verify compilation.

    Returns a dict with:
        - status: 'CLEAN' | 'FIXED' | 'FAILED'
        - message: str
        - diff: Optional[str]
        - explanation: Optional[str]
        - errors_addressed: Optional[list[str]]
        - error_log: Optional[str]
    """
    fw_dir = Path(firmware_dir).resolve()
    src_file = fw_dir / "src" / "main.cpp"
    bak_file = fw_dir / "src" / "main.cpp.bak"

    if not src_file.is_file():
        return {
            "status": "FAILED",
            "message": f"Source file not found at {src_file}",
            "error_log": "Missing source file",
        }

    # 1. Check initial syntax
    is_clean, initial_log = check_firmware_syntax(fw_dir)
    if is_clean:
        return {
            "status": "CLEAN",
            "message": "Firmware syntax is clean. Code compiles with 0 errors.",
            "diff": "",
            "explanation": "No syntax errors found.",
            "errors_addressed": [],
        }

    original_code = src_file.read_text(encoding="utf-8")

    # 2. Create safety backup
    shutil.copy2(src_file, bak_file)

    # 3. Prompt Gemini with compiler log and numbered source
    numbered = add_line_numbers(original_code)
    prompt = SYNTAX_FIX_PROMPT_TEMPLATE.format(
        compiler_log=initial_log,
        numbered_source=numbered,
    )

    try:
        proposal: SyntaxFixProposal = generate_json(
            prompt=prompt,
            schema_model=SyntaxFixProposal,
            client=client,
            model=model,
            use_cache=False,
        )
    except Exception as exc:
        restore_firmware_backup(fw_dir)
        return {
            "status": "FAILED",
            "message": f"AI syntax repair request failed: {type(exc).__name__}: {exc}",
            "error_log": str(exc),
        }

    fixed_code = proposal.fixed_code
    if not fixed_code or not fixed_code.strip():
        restore_firmware_backup(fw_dir)
        return {
            "status": "FAILED",
            "message": "AI returned empty code proposal. Original source preserved.",
            "error_log": "Empty code received from LLM",
        }

    # 4. Write fixed code to main.cpp
    src_file.write_text(fixed_code, encoding="utf-8")

    # 5. Verify compilation
    post_clean, post_log = check_firmware_syntax(fw_dir)
    if post_clean:
        diff_lines = list(
            difflib.unified_diff(
                original_code.splitlines(keepends=True),
                fixed_code.splitlines(keepends=True),
                fromfile="src/main.cpp (original)",
                tofile="src/main.cpp (repaired)",
            )
        )
        diff_str = "".join(diff_lines)
        return {
            "status": "FIXED",
            "message": "Syntax errors successfully resolved! Firmware now compiles cleanly.",
            "diff": diff_str,
            "explanation": proposal.explanation,
            "errors_addressed": proposal.errors_addressed,
            "fixed_code": fixed_code,
        }

    # If still failing, restore backup
    restore_firmware_backup(fw_dir)
    return {
        "status": "FAILED",
        "message": "AI-suggested repair still failed compilation. Restored original source from backup.",
        "error_log": post_log,
        "explanation": proposal.explanation,
    }
