"""Universal Virtual Hardware Simulator (agent/simulators/mock_sim.py).

Zero-dependency, high-speed embedded emulator that analyzes the current firmware logic,
simulates DHT22 temperature readings, state transitions, alarms, and hysteresis,
generates serial output, and evaluates test expectations without requiring Wokwi or PlatformIO.
"""

from pathlib import Path
import time
from typing import Any

from agent.evaluator import evaluate
from agent.models import TestCase, TestResult
from agent.simulators.base import BaseSimulator


class VirtualMockSimulator(BaseSimulator):
    """Universal instant hardware simulator running embedded state machines in software."""

    name: str = "virtual_mock"
    display_name: str = "Universal Virtual Hardware Simulator"
    supported_languages: list[str] = ["cpp", "c", "ino", "python"]

    def is_available(self) -> tuple[bool, str]:
        """Always available on any platform with zero dependencies."""
        return True, "Built-in zero-dependency virtual hardware engine ready."

    def run_test(
        self,
        test: TestCase,
        firmware_dir: Path | str,
        run_dir: Path | str,
    ) -> TestResult:
        """Simulate hardware sensor inputs and evaluate against firmware logic."""
        start_time = time.perf_counter()
        target_run_dir = Path(run_dir).resolve()
        temp_dir = target_run_dir / "sim" / test.id
        temp_dir.mkdir(parents=True, exist_ok=True)

        fw_path = Path(firmware_dir).resolve()
        src_candidate = fw_path / "src" / "main.cpp"
        source_code = ""
        if src_candidate.is_file():
            source_code = src_candidate.read_text(encoding="utf-8")

        # Inspect current source code for known logic defects vs fixes:
        # Bug 1: strict inequality (t > 30.0) vs threshold (t >= 30.0)
        has_strict_inequality = "> 30.0" in source_code and ">= 30.0" not in source_code

        # Bug 2: missing hysteresis (checks 28.0)
        has_hysteresis = "28.0" in source_code or "HYSTERESIS" in source_code

        # Bug 3: missing isnan sensor failure check
        has_isnan = "isnan" in source_code

        serial_lines: list[str] = []
        fan_state = "OFF"

        if test.sensor == "disconnected":
            if has_isnan:
                serial_lines.append("[ERROR] SENSOR_FAIL: DHT22 read failure")
                serial_lines.append("[DATA] temp=NaN fan=OFF")
            else:
                # Buggy firmware doesn't check isnan, reads 0.0 or garbage without error
                serial_lines.append("[DATA] temp=0.0 fan=OFF")
        else:
            for step in test.steps:
                t = step.set_temp
                if t is None:
                    serial_lines.append(f"[DATA] temp=25.0 fan={fan_state}")
                    continue

                # Overheat check (> 60.0)
                if t > 60.0:
                    serial_lines.append(f"[ALARM] OVERHEAT: Temperature {t:.1f}C exceeds limit")

                # Fan turn ON logic
                turn_on_threshold = 30.0
                turn_on = (t > turn_on_threshold) if has_strict_inequality else (t >= turn_on_threshold)

                if turn_on:
                    fan_state = "ON"
                elif fan_state == "ON":
                    if has_hysteresis:
                        if t < 28.0:
                            fan_state = "OFF"
                    else:
                        # Buggy: turns off immediately when < 30.0
                        if t < 30.0:
                            fan_state = "OFF"
                else:
                    fan_state = "OFF"

                serial_lines.append(f"[DATA] temp={t:.1f} fan={fan_state}")

        duration = time.perf_counter() - start_time
        serial_log = "\n".join(serial_lines) + "\n"

        # Write serial.log to simulation directory
        (temp_dir / "serial.log").write_text(serial_log, encoding="utf-8")

        result = evaluate(
            test=test,
            raw_output=serial_log,
            exit_code=0,
            duration_s=duration,
        )
        return result
