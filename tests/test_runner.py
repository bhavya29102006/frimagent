"""Unit tests for agent/runner.py simulation runner."""

from pathlib import Path
from unittest.mock import MagicMock
import pytest

from agent.models import Expectation, TestCase, TestResult, TestStep
from agent.runner import extract_observed_lines, find_wokwi_cli, run_test, strip_ansi


@pytest.fixture(autouse=True)
def isolate_env(monkeypatch):
    """Prevent load_dotenv from overriding monkeypatched environment variables."""
    monkeypatch.setattr("agent.runner.load_dotenv", lambda *args, **kwargs: None)


def test_strip_ansi():
    """ANSI color escape sequences are stripped cleanly."""
    raw = "\x1b[32m[INFO] BOOT\x1b[0m\r\n\x1b[31m[ERROR] SENSOR_FAIL\x1b[0m"
    clean = strip_ansi(raw)
    assert clean == "[INFO] BOOT\r\n[ERROR] SENSOR_FAIL"


def test_extract_observed_lines():
    """Extracts only lines containing protocol tags."""
    log = (
        "Wokwi CLI v0.15.0\n"
        "[INFO] BOOT\n"
        "Some internal debug info\n"
        "[DATA] temp=25.0 fan=OFF\n"
        "[ALARM] OVERHEAT\n"
        "Scenario completed successfully\n"
    )
    observed = extract_observed_lines(log)
    assert observed == [
        "[INFO] BOOT",
        "[DATA] temp=25.0 fan=OFF",
        "[ALARM] OVERHEAT",
    ]


def test_find_wokwi_cli_from_env(monkeypatch, tmp_path):
    """WOKWI_CLI_PATH takes first precedence if the file exists."""
    fake_cli = tmp_path / "wokwi-cli.exe"
    fake_cli.write_text("binary", encoding="utf-8")
    monkeypatch.setenv("WOKWI_CLI_PATH", str(fake_cli))

    found = find_wokwi_cli()
    assert found == fake_cli


def test_find_wokwi_cli_from_which(monkeypatch, tmp_path):
    """shutil.which is used if WOKWI_CLI_PATH is not set."""
    monkeypatch.delenv("WOKWI_CLI_PATH", raising=False)
    fake_which = tmp_path / "wokwi-cli"
    fake_which.write_text("binary", encoding="utf-8")

    monkeypatch.setattr("shutil.which", lambda cmd: str(fake_which))
    found = find_wokwi_cli()
    assert found == fake_which


def _make_dummy_test() -> TestCase:
    return TestCase(
        id="T01",
        name="Dummy Test",
        category="normal",
        steps=[TestStep(set_temp=25.0)],
        expect=[Expectation(serial_contains="temp=25.0 fan=OFF")],
        rationale="Testing",
    )


def test_run_test_pass(monkeypatch, tmp_path):
    """Exit code 0 yields status PASS and does not retry."""
    test = _make_dummy_test()

    # Create dummy firmware directory
    fw_dir = tmp_path / "firmware"
    fw_build = fw_dir / ".pio" / "build" / "uno"
    fw_build.mkdir(parents=True)
    (fw_build / "firmware.hex").write_text("hex", encoding="utf-8")
    (fw_build / "firmware.elf").write_text("elf", encoding="utf-8")
    (fw_dir / "diagram.json").write_text("{}", encoding="utf-8")

    mock_cli = tmp_path / "fake_wokwi"
    mock_cli.write_text("", encoding="utf-8")
    monkeypatch.setattr("agent.runner.find_wokwi_cli", lambda: mock_cli)

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.stdout = (
        "[INFO] BOOT\n[DATA] temp=25.0 fan=OFF\nScenario completed successfully"
    )
    mock_proc.stderr = ""

    mock_subprocess = MagicMock(return_value=mock_proc)
    monkeypatch.setattr("subprocess.run", mock_subprocess)

    result = run_test(
        test=test, firmware_dir=fw_dir, run_dir=tmp_path / "run"
    )

    assert isinstance(result, TestResult)
    assert result.status == "PASS"
    assert result.exit_code == 0
    assert mock_subprocess.call_count == 1
    assert any("temp=25.0 fan=OFF" in line for line in result.observed_lines)


def test_run_test_fail_exit_42_no_retry(monkeypatch, tmp_path):
    """Exit code 42 yields status FAIL and NEVER retries."""
    test = _make_dummy_test()

    fw_dir = tmp_path / "firmware"
    fw_build = fw_dir / ".pio" / "build" / "uno"
    fw_build.mkdir(parents=True)
    (fw_build / "firmware.hex").write_text("hex", encoding="utf-8")
    (fw_build / "firmware.elf").write_text("elf", encoding="utf-8")
    (fw_dir / "diagram.json").write_text("{}", encoding="utf-8")

    mock_cli = tmp_path / "fake_wokwi"
    mock_cli.write_text("", encoding="utf-8")
    monkeypatch.setattr("agent.runner.find_wokwi_cli", lambda: mock_cli)

    mock_proc = MagicMock()
    mock_proc.returncode = 42
    mock_proc.stdout = "[INFO] BOOT\nTimeout: simulation did not finish in 20000ms"
    mock_proc.stderr = ""

    mock_subprocess = MagicMock(return_value=mock_proc)
    monkeypatch.setattr("subprocess.run", mock_subprocess)

    result = run_test(
        test=test, firmware_dir=fw_dir, run_dir=tmp_path / "run"
    )

    assert result.status == "FAIL"
    assert result.exit_code == 42
    assert mock_subprocess.call_count == 1


def test_run_test_error_retries_once(monkeypatch, tmp_path):
    """Exit code other than 0 or 42 is ERROR; runner retries once."""
    test = _make_dummy_test()

    fw_dir = tmp_path / "firmware"
    fw_build = fw_dir / ".pio" / "build" / "uno"
    fw_build.mkdir(parents=True)
    (fw_build / "firmware.hex").write_text("hex", encoding="utf-8")
    (fw_build / "firmware.elf").write_text("elf", encoding="utf-8")
    (fw_dir / "diagram.json").write_text("{}", encoding="utf-8")

    mock_cli = tmp_path / "fake_wokwi"
    mock_cli.write_text("", encoding="utf-8")
    monkeypatch.setattr("agent.runner.find_wokwi_cli", lambda: mock_cli)

    # 1st attempt: ERROR (code 1)
    # 2nd attempt: PASS (code 0)
    mock_err = MagicMock(returncode=1, stdout="Generic crash", stderr="")
    mock_pass = MagicMock(
        returncode=0, stdout="[INFO] BOOT\n[DATA] temp=25.0 fan=OFF", stderr=""
    )

    mock_subprocess = MagicMock(side_effect=[mock_err, mock_pass])
    monkeypatch.setattr("subprocess.run", mock_subprocess)

    result = run_test(
        test=test, firmware_dir=fw_dir, run_dir=tmp_path / "run"
    )

    assert result.status == "PASS"
    assert mock_subprocess.call_count == 2
