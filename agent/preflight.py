"""Preflight checks: tool availability (pio, wokwi-cli) and environment keys (Gemini, Wokwi)."""

from dataclasses import dataclass
from pathlib import Path
import os
import shutil
import subprocess
import sys
from dotenv import load_dotenv


@dataclass
class CheckResult:
    """Result of a single preflight check."""

    name: str
    ok: bool
    detail: str
    hint: str


def run_preflight(project_root: Path | None = None) -> list[CheckResult]:
    """Run all preflight checks and return their results.

    NEVER prints or returns key values; detail for secrets is only 'set' or 'missing'.
    """
    load_dotenv()

    if project_root is None:
        project_root = Path(__file__).resolve().parent.parent

    results: list[CheckResult] = []

    # 1. GEMINI_API_KEY
    gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if gemini_key:
        results.append(
            CheckResult(
                name="GEMINI_API_KEY",
                ok=True,
                detail="set",
                hint="",
            )
        )
    else:
        results.append(
            CheckResult(
                name="GEMINI_API_KEY",
                ok=False,
                detail="missing",
                hint="Add GEMINI_API_KEY to .env (from Google AI Studio)",
            )
        )

    # 2. GEMINI_MODEL
    gemini_model = os.environ.get("GEMINI_MODEL", "").strip()
    if gemini_model:
        results.append(
            CheckResult(
                name="GEMINI_MODEL",
                ok=True,
                detail="set",
                hint="",
            )
        )
    else:
        results.append(
            CheckResult(
                name="GEMINI_MODEL",
                ok=False,
                detail="missing",
                hint="Add GEMINI_MODEL to .env (e.g. gemini-3.8-flash)",
            )
        )

    # 3. WOKWI_CLI_TOKEN
    wokwi_token = os.environ.get("WOKWI_CLI_TOKEN", "").strip()
    if wokwi_token:
        results.append(
            CheckResult(
                name="WOKWI_CLI_TOKEN",
                ok=True,
                detail="set",
                hint="",
            )
        )
    else:
        results.append(
            CheckResult(
                name="WOKWI_CLI_TOKEN",
                ok=False,
                detail="missing",
                hint="Add WOKWI_CLI_TOKEN to .env (from wokwi.com/ci)",
            )
        )

    # 4. wokwi-cli on PATH
    wokwi_path = shutil.which("wokwi-cli")
    if wokwi_path:
        results.append(
            CheckResult(
                name="wokwi-cli",
                ok=True,
                detail="found",
                hint="",
            )
        )
    else:
        results.append(
            CheckResult(
                name="wokwi-cli",
                ok=False,
                detail="missing",
                hint="Install Wokwi CLI (iwr https://wokwi.com/ci/install.ps1 -useb | iex)",
            )
        )

    # 5. pio on PATH or python -m platformio works
    pio_path = shutil.which("pio")
    pio_ok = bool(pio_path)
    if not pio_ok:
        try:
            res = subprocess.run(
                [sys.executable, "-m", "platformio", "--version"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            pio_ok = res.returncode == 0
        except Exception:
            pio_ok = False

    if pio_ok:
        results.append(
            CheckResult(
                name="PlatformIO (pio)",
                ok=True,
                detail="available",
                hint="",
            )
        )
    else:
        results.append(
            CheckResult(
                name="PlatformIO (pio)",
                ok=False,
                detail="missing",
                hint="Install PlatformIO Core (pip install platformio)",
            )
        )

    # 6. firmware/fan_controller/.pio/build/uno/firmware.hex exists
    hex_path = (
        project_root
        / "firmware"
        / "fan_controller"
        / ".pio"
        / "build"
        / "uno"
        / "firmware.hex"
    )
    if hex_path.is_file():
        results.append(
            CheckResult(
                name="firmware.hex",
                ok=True,
                detail="found",
                hint="",
            )
        )
    else:
        results.append(
            CheckResult(
                name="firmware.hex",
                ok=False,
                detail="missing",
                hint="Build firmware: cd firmware/fan_controller && pio run",
            )
        )

    return results
