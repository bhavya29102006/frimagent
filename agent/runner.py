"""Simulator runner: temp project isolation, wokwi-cli execution, log capture."""

from pathlib import Path
import os
import re
import shutil
import subprocess
import sys
import time
from dotenv import load_dotenv
from agent.compiler import compile_test
from agent.evaluator import evaluate
from agent.models import TestCase, TestResult

ANSI_ESCAPE_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")


def strip_ansi(text: str) -> str:
    """Remove ANSI escape codes from simulator console output."""
    return ANSI_ESCAPE_RE.sub("", text)


def find_wokwi_cli() -> Path:
    """Find wokwi-cli executable.

    Search order:
    1. WOKWI_CLI_PATH environment variable
    2. shutil.which("wokwi-cli")
    3. ~/.wokwi/bin/wokwi-cli(.exe)
    """
    load_dotenv()
    env_path = os.environ.get("WOKWI_CLI_PATH")
    if env_path and Path(env_path).is_file():
        return Path(env_path)

    which_path = shutil.which("wokwi-cli")
    if which_path and Path(which_path).is_file():
        return Path(which_path)

    home_bin = Path.home() / ".wokwi" / "bin"
    candidates = [
        home_bin / "wokwi-cli.exe",
        home_bin / "wokwi-cli",
    ]
    for c in candidates:
        if c.is_file():
            return c

    raise FileNotFoundError(
        "wokwi-cli executable not found. Please set WOKWI_CLI_PATH or install wokwi-cli."
    )


def extract_observed_lines(log: str) -> list[str]:
    """Extract relevant [DATA], [ALARM], [ERROR], or [INFO] lines from serial log."""
    lines: list[str] = []
    for raw_line in log.splitlines():
        line = raw_line.strip()
        if any(
            tag in line for tag in ("[DATA]", "[ALARM]", "[ERROR]", "[INFO]")
        ):
            lines.append(line)
    return lines


def run_test(
    test: TestCase,
    firmware_dir: Path | str,
    run_dir: Path | str,
    simulator_name: str = "wokwi",
) -> TestResult:
    """Execute a TestCase in an isolated temporary simulation folder.

    Supports pluggable simulators: 'wokwi', 'virtual_mock', 'native_c', 'python_sim'.
    Defaults to 'wokwi'.
    """
    fw_path = Path(firmware_dir).resolve()
    hex_src = fw_path / ".pio" / "build" / "uno" / "firmware.hex"

    # Intelligent Compatibility Guard:
    # Wokwi requires compiled AVR binary (firmware.hex). If Wokwi is selected for Python, C,
    # or firmware without compiled binaries, auto-route to native runtime or virtual hardware.
    effective_sim = simulator_name or "wokwi"
    if effective_sim == "wokwi":
        is_python = any((fw_path / "src").glob("*.py")) if (fw_path / "src").is_dir() else any(fw_path.glob("*.py"))
        is_c = any((fw_path / "src").glob("*.c")) if (fw_path / "src").is_dir() else any(fw_path.glob("*.c"))

        if is_python:
            effective_sim = "python_sim"
        elif is_c and not hex_src.is_file():
            effective_sim = "native_c"
        elif not hex_src.is_file():
            effective_sim = "virtual_mock"

    if effective_sim != "wokwi":
        from agent.simulators.registry import get_simulator
        sim = get_simulator(effective_sim)
        return sim.run_test(test=test, firmware_dir=firmware_dir, run_dir=run_dir)

    target_run_dir = Path(run_dir).resolve()
    temp_dir = target_run_dir / "sim" / test.id
    temp_dir.mkdir(parents=True, exist_ok=True)

    # 1. Copy compiled binaries into temp project dir
    hex_src = fw_path / ".pio" / "build" / "uno" / "firmware.hex"
    elf_src = fw_path / ".pio" / "build" / "uno" / "firmware.elf"

    if hex_src.is_file():
        shutil.copy2(hex_src, temp_dir / "firmware.hex")
    if elf_src.is_file():
        shutil.copy2(elf_src, temp_dir / "firmware.elf")

    # 2. Compile scenario and diagram variant into temp project dir
    compile_test(test=test, project_dir=fw_path, out_dir=temp_dir)

    # 3. Locate wokwi-cli
    wokwi_bin = find_wokwi_cli()

    # 4. Prepare environment with token
    load_dotenv()
    env = os.environ.copy()
    wokwi_token = os.environ.get("WOKWI_CLI_TOKEN")
    if wokwi_token:
        env["WOKWI_CLI_TOKEN"] = wokwi_token

    cmd = [
        str(wokwi_bin),
        str(temp_dir),
        "--scenario",
        "scenario.test.yaml",
        "--timeout",
        "20000",
    ]

    # 5. Run simulation (with one retry on ERROR only, never on FAIL)
    last_result: TestResult | None = None
    max_runs = 2

    for attempt in range(max_runs):
        start_time = time.perf_counter()
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(temp_dir),
                capture_output=True,
                text=True,
                timeout=25,
                env=env,
                check=False,
            )
            raw_stdout = proc.stdout or ""
            raw_stderr = proc.stderr or ""
            raw_log = raw_stdout + ("\n" + raw_stderr if raw_stderr else "")
            last_exit_code = proc.returncode
        except subprocess.TimeoutExpired as te:
            raw_stdout = te.stdout or ""
            raw_stderr = te.stderr or ""
            raw_log = (
                raw_stdout
                + ("\n" + raw_stderr if raw_stderr else "")
                + "\nTimeout: simulation did not finish in 20000ms"
            )
            last_exit_code = 42
        except Exception as exc:
            raw_log = f"Execution error: {type(exc).__name__}: {exc}"
            last_exit_code = -1

        last_duration = time.perf_counter() - start_time
        last_serial_log = strip_ansi(raw_log)

        # Save serial.log
        (temp_dir / "serial.log").write_text(
            last_serial_log, encoding="utf-8"
        )

        last_result = evaluate(
            test=test,
            raw_output=last_serial_log,
            exit_code=last_exit_code,
            duration_s=last_duration,
        )

        # One retry only on ERROR, never on FAIL or PASS
        if last_result.status != "ERROR" or attempt == max_runs - 1:
            return last_result

    return last_result  # type: ignore
