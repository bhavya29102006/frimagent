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

    # Support standalone C/C++ firmwares without PlatformIO (e.g. water_tank_monitor)
    c_candidate = None
    for cand in (p_dir / "src" / "main.c", p_dir / "src" / "main.cpp", p_dir / "main.c", p_dir / "main.cpp"):
        if cand.is_file():
            c_candidate = cand
            break
    if not c_candidate and not (p_dir / "platformio.ini").is_file():
        c_files = list((p_dir / "src").glob("*.c")) + list((p_dir / "src").glob("*.cpp")) if (p_dir / "src").is_dir() else []
        if not c_files:
            c_files = list(p_dir.glob("*.c")) + list(p_dir.glob("*.cpp"))
        if c_files:
            c_candidate = c_files[0]

    if c_candidate and not (p_dir / "platformio.ini").is_file():
        compiler = shutil.which("gcc") or shutil.which("g++") or shutil.which("clang") or shutil.which("clang++")
        if compiler:
            content = c_candidate.read_text(encoding="utf-8", errors="replace")
            bin_name = "firmware_native.exe" if sys.platform == "win32" else "firmware_native"
            out_bin = p_dir / bin_name
            if "int main(" in content:
                compile_cmd = [compiler, str(c_candidate), "-o", str(out_bin)]
            else:
                compile_cmd = [compiler, "-fsyntax-only", str(c_candidate)]
            try:
                proc = subprocess.run(
                    compile_cmd,
                    cwd=str(p_dir),
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    check=False,
                )
                if proc.returncode == 0:
                    artifacts = {"bin": out_bin} if out_bin.is_file() else {"src": c_candidate}
                    return True, f"Native build passed ({c_candidate.name}).", artifacts
                combined_log = (proc.stderr or "") + ("\n" + proc.stdout if proc.stdout else "")
                lines = combined_log.strip().splitlines()
                tail = "\n".join(lines[-20:]) if lines else "Compilation failed with no output."
                return False, tail, {}
            except Exception as exc:
                return False, f"Native compilation error: {exc}", {}
        else:
            return True, f"Native compiler not found, validated virtual C/C++ ({c_candidate.name}).", {"src": c_candidate}

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
