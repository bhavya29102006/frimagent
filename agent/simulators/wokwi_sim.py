"""Wokwi Hardware Simulator plugin for FirmAgent."""

import os
from pathlib import Path
import shutil
import subprocess
import time
from dotenv import load_dotenv

from agent.compiler import compile_test
from agent.evaluator import evaluate
from agent.models import TestCase, TestResult
from agent.runner import find_wokwi_cli, strip_ansi
from agent.simulators.base import BaseSimulator


class WokwiSimulator(BaseSimulator):
    """Wokwi virtual circuit hardware simulator using wokwi-cli."""

    name: str = "wokwi"
    display_name: str = "Wokwi Hardware Simulator (Arduino Uno + Circuit)"
    supported_languages: list[str] = ["cpp", "c", "ino"]

    def is_available(self) -> tuple[bool, str]:
        """Check if wokwi-cli executable and auth token are configured."""
        try:
            find_wokwi_cli()
            load_dotenv()
            token = os.environ.get("WOKWI_CLI_TOKEN")
            if not token:
                return False, "WOKWI_CLI_TOKEN not set in environment or .env"
            return True, "Wokwi CLI and token detected."
        except Exception as exc:
            return False, str(exc)

    def run_test(
        self,
        test: TestCase,
        firmware_dir: Path | str,
        run_dir: Path | str,
    ) -> TestResult:
        """Run test in Wokwi simulator."""
        fw_path = Path(firmware_dir).resolve()
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
            (temp_dir / "serial.log").write_text(last_serial_log, encoding="utf-8")

            last_result = evaluate(
                test=test,
                raw_output=last_serial_log,
                exit_code=last_exit_code,
                duration_s=last_duration,
            )

            # Intelligent Fallback: if Wokwi cloud quota is exhausted or API fails, auto-route to virtual hardware
            if any(
                term in last_serial_log
                for term in (
                    "API Error",
                    "monthly CI minute quota",
                    "used up your Free plan",
                    "Please upgrade to a paid plan",
                )
            ):
                from agent.simulators.mock_sim import VirtualMockSimulator
                mock_sim = VirtualMockSimulator()
                fallback_res = mock_sim.run_test(test=test, firmware_dir=firmware_dir, run_dir=run_dir)
                fallback_res.serial_log = (
                    f"[WARN] Wokwi CI quota exhausted. Auto-routed seamlessly to Universal Virtual Hardware Simulator.\n"
                    f"{fallback_res.serial_log}"
                )
                return fallback_res

            if last_result.status != "ERROR" or attempt == max_runs - 1:
                return last_result

        return last_result
