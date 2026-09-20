"""Firmware build wrapper using PlatformIO Core (pio run)."""

from pathlib import Path
import shutil
import subprocess
import sys


def find_pio_command() -> list[str]:
    """Locate the platformio invocation command."""
    pio_path = shutil.which("pio")
    if pio_path:
        return ["pio", "run"]
    return [sys.executable, "-m", "platformio", "run"]


def get_build_artifacts(project_dir: Path | str) -> dict[str, Path]:
    """Retrieve paths to built firmware artifacts (.hex and .elf)."""
    p_dir = Path(project_dir).resolve()
    build_dir = p_dir / ".pio" / "build" / "uno"
    artifacts = {}

    hex_file = build_dir / "firmware.hex"
    if hex_file.is_file():
        artifacts["hex"] = hex_file

    elf_file = build_dir / "firmware.elf"
    if elf_file.is_file():
        artifacts["elf"] = elf_file

    bin_file = build_dir / "firmware.bin"
    if bin_file.is_file():
        artifacts["bin"] = bin_file

    return artifacts


def build_firmware(
    project_dir: Path | str,
    timeout: int = 120,
) -> tuple[bool, str, dict[str, Path]]:
    """Compile firmware in the target project directory using PlatformIO.

    Args:
        project_dir: Directory containing platformio.ini and src/
        timeout: Maximum seconds to wait for build completion.

    Returns:
        tuple of (success: bool, log_tail: str, artifacts: dict[str, Path])
        where log_tail contains build logs or the last 20 lines on failure.
    """
    p_dir = Path(project_dir).resolve()
    if not p_dir.is_dir():
        return False, f"Project directory not found: {p_dir}", {}

    # Support Python/MicroPython firmwares (validate syntax without PlatformIO)
    py_candidate = None
    for cand in (p_dir / "src" / "main.py", p_dir / "main.py"):
        if cand.is_file():
            py_candidate = cand
            break
    if not py_candidate and not (p_dir / "platformio.ini").is_file():
        py_files = list((p_dir / "src").glob("*.py")) if (p_dir / "src").is_dir() else []
        if not py_files:
            py_files = list(p_dir.glob("*.py"))
        if py_files:
            py_candidate = py_files[0]

    if py_candidate and not (p_dir / "platformio.ini").is_file():
        import py_compile
        try:
            py_compile.compile(str(py_candidate), doraise=True)
            return True, f"Python syntax check passed ({py_candidate.name}).", {"py": py_candidate}
        except py_compile.PyCompileError as pe:
            return False, f"Python syntax error in {py_candidate.name}:\n{pe}", {}
        except Exception as exc:
            return False, f"Python validation error: {exc}", {}

    cmd = find_pio_command()

    try:
        proc = subprocess.run(
            cmd,
            cwd=str(p_dir),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        combined_log = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        artifacts = get_build_artifacts(p_dir)

        if proc.returncode == 0:
            return True, combined_log, artifacts

        # Failure: return last 20 log lines
        lines = combined_log.strip().splitlines()
        tail = "\n".join(lines[-20:]) if lines else "Build failed with no output."
        return False, tail, artifacts

    except subprocess.TimeoutExpired as te:
        tail = f"PlatformIO build timed out after {timeout} seconds."
        return False, tail, {}
    except Exception as exc:
        return False, f"Build invocation error: {type(exc).__name__}: {exc}", {}
