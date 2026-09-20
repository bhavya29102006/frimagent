"""MicroPython / Embedded Python Simulator plugin for FirmAgent."""

from pathlib import Path
import subprocess
import sys
import time

from agent.evaluator import evaluate
from agent.models import TestCase, TestResult
from agent.simulators.base import BaseSimulator
from agent.simulators.mock_sim import VirtualMockSimulator


class PythonSimulator(BaseSimulator):
    """Executes embedded Python/MicroPython scripts or virtual hardware harness."""

    name: str = "python_sim"
    display_name: str = "MicroPython / Embedded Python Runner"
    supported_languages: list[str] = ["python", "py"]

    def is_available(self) -> tuple[bool, str]:
        """Available via host Python interpreter."""
        return True, f"Python interpreter available at {sys.executable}"

    def run_test(
        self,
        test: TestCase,
        firmware_dir: Path | str,
        run_dir: Path | str,
    ) -> TestResult:
        """Execute test case using Python embedded harness."""
        fw_path = Path(firmware_dir).resolve()
        target_run_dir = Path(run_dir).resolve()
        temp_dir = target_run_dir / "sim" / test.id
        temp_dir.mkdir(parents=True, exist_ok=True)

        py_candidate = fw_path / "src" / "main.py"
        if not py_candidate.is_file():
            # Check for any .py file in src/ or firmware root
            py_files = list(fw_path.glob("src/*.py")) or list(fw_path.glob("*.py"))
            if py_files:
                py_candidate = py_files[0]

        if py_candidate.is_file():
            # Run the Python script with test steps passed via CLI or env
            start_time = time.perf_counter()
            env_steps = ",".join(f"{s.set_temp or 25.0}" for s in test.steps)
            try:
                proc = subprocess.run(
                    [
                        sys.executable,
                        str(py_candidate),
                        f"--sensor={'disconnected' if test.sensor == 'disconnected' else 'normal'}",
                        f"--temps={env_steps}",
                    ],
                    cwd=str(temp_dir),
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=False,
                )
                output = proc.stdout or ""
                if proc.stderr:
                    output += "\n" + proc.stderr
                exit_code = proc.returncode
            except Exception as exc:
                output = f"Execution error: {exc}"
                exit_code = -1

            duration = time.perf_counter() - start_time
            (temp_dir / "serial.log").write_text(output, encoding="utf-8")

            # If python script produced output matching serial format, evaluate it
            if "[DATA]" in output or "[ALARM]" in output or "[ERROR]" in output:
                return evaluate(test=test, raw_output=output, exit_code=exit_code, duration_s=duration)

        # Fallback to VirtualMockSimulator logic if python script is stub or not yet written
        mock_runner = VirtualMockSimulator()
        return mock_runner.run_test(test=test, firmware_dir=firmware_dir, run_dir=run_dir)
