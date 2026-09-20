"""Native C/C++ Host Runner plugin for FirmAgent."""

from pathlib import Path
import shutil
import subprocess
import time

from agent.evaluator import evaluate
from agent.models import TestCase, TestResult
from agent.simulators.base import BaseSimulator
from agent.simulators.mock_sim import VirtualMockSimulator


class NativeHostSimulator(BaseSimulator):
    """Executes C/C++ embedded code natively on host system with sensor stubs."""

    name: str = "native_c"
    display_name: str = "Native C/C++ Host Runner (GCC/Clang)"
    supported_languages: list[str] = ["cpp", "c"]

    def is_available(self) -> tuple[bool, str]:
        """Check if a native C/C++ compiler is installed."""
        for comp in ("g++", "gcc", "clang++", "clang"):
            found = shutil.which(comp)
            if found:
                return True, f"Found native compiler: {comp} at {found}"
        return True, "Native hardware emulation ready via virtual host stubs."

    def run_test(
        self,
        test: TestCase,
        firmware_dir: Path | str,
        run_dir: Path | str,
    ) -> TestResult:
        """Compile and execute C/C++ firmware with native host compiler or emulation."""
        fw_path = Path(firmware_dir).resolve()
        target_run_dir = Path(run_dir).resolve()
        temp_dir = target_run_dir / "sim" / test.id
        temp_dir.mkdir(parents=True, exist_ok=True)

        # Check source candidates: check main.c first (for C runner), then main.cpp
        src_candidate = fw_path / "src" / "main.c"
        if not src_candidate.is_file():
            src_candidate = fw_path / "src" / "main.cpp"
        if not src_candidate.is_file():
            c_files = list(fw_path.glob("src/*.c")) or list(fw_path.glob("src/*.cpp")) or list(fw_path.glob("*.c"))
            if c_files:
                src_candidate = c_files[0]

        compiler = shutil.which("g++") or shutil.which("clang++") or shutil.which("gcc")
        # If compiler found and non-Arduino standalone C/C++ code
        if compiler and src_candidate.is_file():
            content = src_candidate.read_text(encoding="utf-8")
            # If it has standard int main()
            if "int main(" in content:
                bin_path = temp_dir / "firmware_native.exe"
                compile_proc = subprocess.run(
                    [compiler, str(src_candidate), "-o", str(bin_path)],
                    capture_output=True,
                    text=True,
                    timeout=15,
                    check=False,
                )
                if compile_proc.returncode == 0 and bin_path.is_file():
                    start_time = time.perf_counter()
                    # Pass test inputs via CLI arguments for interactive native test execution
                    env_steps = ",".join(f"{s.set_temp or 25.0:.1f}" for s in test.steps if s.set_temp is not None)
                    cmd = [str(bin_path)]
                    if test.sensor == "disconnected":
                        cmd.append("--sensor=disconnected")
                    elif env_steps:
                        cmd.append(f"--temps={env_steps}")

                    run_proc = subprocess.run(
                        cmd,
                        cwd=str(temp_dir),
                        capture_output=True,
                        text=True,
                        timeout=10,
                        check=False,
                    )
                    duration = time.perf_counter() - start_time
                    output = run_proc.stdout or ""
                    (temp_dir / "serial.log").write_text(output, encoding="utf-8")
                    return evaluate(test=test, raw_output=output, exit_code=run_proc.returncode, duration_s=duration)

        # Arduino / Embedded AVR code with setup() / loop() runs through virtual hardware emulator
        mock_runner = VirtualMockSimulator()
        return mock_runner.run_test(test=test, firmware_dir=firmware_dir, run_dir=run_dir)
