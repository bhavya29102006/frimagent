"""Unit tests for agent/builder.py."""

from pathlib import Path
import subprocess
from unittest.mock import MagicMock, patch
import pytest

from agent.builder import build_firmware, find_pio_command, get_build_artifacts


def test_find_pio_command():
    """find_pio_command returns a valid command list."""
    cmd = find_pio_command()
    assert isinstance(cmd, list)
    assert len(cmd) >= 1
    # Either ['pio'] or [python_executable, '-m', 'platformio']
    assert cmd[0] == "pio" or "python" in cmd[0].lower()


def test_get_build_artifacts(tmp_path):
    """get_build_artifacts correctly locates firmware.hex, firmware.elf, and firmware.bin."""
    pio_dir = tmp_path / ".pio" / "build" / "uno"
    pio_dir.mkdir(parents=True)

    hex_file = pio_dir / "firmware.hex"
    elf_file = pio_dir / "firmware.elf"
    bin_file = pio_dir / "firmware.bin"
    hex_file.write_bytes(b"HEX DATA")
    elf_file.write_bytes(b"ELF DATA")
    bin_file.write_bytes(b"BIN DATA")

    artifacts = get_build_artifacts(tmp_path)
    assert "hex" in artifacts
    assert "elf" in artifacts
    assert "bin" in artifacts
    assert artifacts["hex"] == hex_file
    assert artifacts["elf"] == elf_file
    assert artifacts["bin"] == bin_file


def test_build_firmware_success(tmp_path):
    """build_firmware calls pio with expected args and returns True on 0 exit code."""
    # Create fake project directory with artifacts
    pio_dir = tmp_path / ".pio" / "build" / "uno"
    pio_dir.mkdir(parents=True)
    (pio_dir / "firmware.hex").write_bytes(b"HEX")
    (pio_dir / "firmware.elf").write_bytes(b"ELF")
    (pio_dir / "firmware.bin").write_bytes(b"BIN")

    mock_res = MagicMock()
    mock_res.returncode = 0
    mock_res.stdout = "Building...\nLinking .pio/build/uno/firmware.elf\nSUCCESS"
    mock_res.stderr = ""

    with patch("subprocess.run", return_value=mock_res) as mock_run:
        ok, log_tail, artifacts = build_firmware(tmp_path)

        assert ok is True
        assert "SUCCESS" in log_tail
        assert "elf" in artifacts
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        # Command must contain 'run'
        assert "run" in call_args
        assert mock_run.call_args[1]["cwd"] == str(tmp_path)


def test_build_firmware_failure_captures_log_tail(tmp_path):
    """build_firmware returns False and captures the last 20 lines on failure."""
    lines = [f"Compile error on line {i}" for i in range(1, 35)]
    mock_res = MagicMock()
    mock_res.returncode = 1
    mock_res.stdout = "Building...\n"
    mock_res.stderr = "\n".join(lines)

    with patch("subprocess.run", return_value=mock_res):
        ok, log_tail, artifacts = build_firmware(tmp_path)

        assert ok is False
        assert artifacts == {}
        # Ensure only the tail (<= 20 lines) is returned
        tail_lines = log_tail.strip().splitlines()
        assert len(tail_lines) <= 20
        assert "Compile error on line 34" in log_tail
        # Line 1 should have been truncated out of the 20-line tail
        assert "Compile error on line 1\n" not in log_tail


def test_build_firmware_handles_exception(tmp_path):
    """build_firmware handles execution exceptions gracefully."""
    with patch("subprocess.run", side_effect=FileNotFoundError("pio not found")):
        ok, log_tail, artifacts = build_firmware(tmp_path)
        assert ok is False
        assert artifacts == {}
        assert "pio not found" in log_tail


def test_build_firmware_standalone_c(tmp_path):
    """build_firmware succeeds for standalone C projects without platformio.ini."""
    src_dir = tmp_path / "src"
    src_dir.mkdir(parents=True)
    c_file = src_dir / "main.c"
    c_file.write_text("int main(void) { return 0; }\n", encoding="utf-8")

    ok, log, artifacts = build_firmware(tmp_path)
    assert ok is True
    assert "Native build passed" in log or "validated virtual C/C++" in log

