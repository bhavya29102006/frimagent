"""Tests for agent/preflight.py using monkeypatch."""

from pathlib import Path
import subprocess
import pytest
from agent.preflight import CheckResult, run_preflight


@pytest.fixture(autouse=True)
def isolate_env(monkeypatch):
    """Prevent load_dotenv from overriding monkeypatched environment variables."""
    monkeypatch.setattr("agent.preflight.load_dotenv", lambda *args, **kwargs: None)


def _get_check(results: list[CheckResult], name: str) -> CheckResult:
    for item in results:
        if item.name == name:
            return item
    raise KeyError(f"Check '{name}' not found in results: {[r.name for r in results]}")


def test_preflight_all_present(monkeypatch, tmp_path):
    """When all tools, keys, and firmware are present, all checks pass."""
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-abc")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3.8-flash")
    monkeypatch.setenv("WOKWI_CLI_TOKEN", "test-token-123")

    # Mock wokwi-cli executable found
    monkeypatch.setattr("shutil.which", lambda cmd: "/usr/local/bin/" + cmd)

    # Create dummy firmware.hex in tmp_path
    hex_dir = tmp_path / "firmware" / "fan_controller" / ".pio" / "build" / "uno"
    hex_dir.mkdir(parents=True)
    hex_file = hex_dir / "firmware.hex"
    hex_file.write_text(":100000000C9434000C9451000C9451000C945100CA\n")

    results = run_preflight(project_root=tmp_path)
    assert len(results) == 6

    for r in results:
        assert r.ok is True, f"Check {r.name} failed unexpectedly"
        assert "test-key-abc" not in r.detail
        assert "test-key-abc" not in r.hint
        assert "test-token-123" not in r.detail
        assert "test-token-123" not in r.hint


def test_missing_gemini_api_key(monkeypatch, tmp_path):
    """When GEMINI_API_KEY is missing, check fails with a helpful hint."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3.8-flash")
    monkeypatch.setenv("WOKWI_CLI_TOKEN", "token")

    results = run_preflight(project_root=tmp_path)
    check = _get_check(results, "GEMINI_API_KEY")
    assert check.ok is False
    assert check.detail == "missing"
    assert "GEMINI_API_KEY" in check.hint


def test_empty_gemini_api_key(monkeypatch, tmp_path):
    """Whitespace-only GEMINI_API_KEY is treated as missing."""
    monkeypatch.setenv("GEMINI_API_KEY", "   ")
    results = run_preflight(project_root=tmp_path)
    check = _get_check(results, "GEMINI_API_KEY")
    assert check.ok is False
    assert check.detail == "missing"


def test_missing_gemini_model(monkeypatch, tmp_path):
    """When GEMINI_MODEL is missing, check fails."""
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    results = run_preflight(project_root=tmp_path)
    check = _get_check(results, "GEMINI_MODEL")
    assert check.ok is False
    assert check.detail == "missing"
    assert "GEMINI_MODEL" in check.hint


def test_missing_wokwi_cli_token(monkeypatch, tmp_path):
    """When WOKWI_CLI_TOKEN is missing, check fails."""
    monkeypatch.delenv("WOKWI_CLI_TOKEN", raising=False)
    results = run_preflight(project_root=tmp_path)
    check = _get_check(results, "WOKWI_CLI_TOKEN")
    assert check.ok is False
    assert check.detail == "missing"
    assert "WOKWI_CLI_TOKEN" in check.hint


def test_missing_wokwi_cli_binary(monkeypatch, tmp_path):
    """When wokwi-cli executable is not on PATH, check fails."""
    monkeypatch.setattr(
        "shutil.which",
        lambda cmd: None if cmd == "wokwi-cli" else "/bin/" + cmd,
    )
    results = run_preflight(project_root=tmp_path)
    check = _get_check(results, "wokwi-cli")
    assert check.ok is False
    assert check.detail == "missing"
    assert "Install Wokwi CLI" in check.hint


def test_pio_available_via_path(monkeypatch, tmp_path):
    """PlatformIO is recognized if pio is on PATH."""
    monkeypatch.setattr(
        "shutil.which",
        lambda cmd: "/usr/bin/pio" if cmd == "pio" else None,
    )
    results = run_preflight(project_root=tmp_path)
    check = _get_check(results, "PlatformIO (pio)")
    assert check.ok is True
    assert check.detail == "available"


def test_pio_available_via_python_module(monkeypatch, tmp_path):
    """PlatformIO is recognized if python -m platformio works even when pio is not on PATH."""
    monkeypatch.setattr("shutil.which", lambda cmd: None)

    def fake_subprocess_run(cmd, **kwargs):
        if "-m" in cmd and "platformio" in cmd:
            return subprocess.CompletedProcess(
                cmd, returncode=0, stdout="PlatformIO Core"
            )
        return subprocess.CompletedProcess(cmd, returncode=1, stdout="")

    monkeypatch.setattr("subprocess.run", fake_subprocess_run)

    results = run_preflight(project_root=tmp_path)
    check = _get_check(results, "PlatformIO (pio)")
    assert check.ok is True
    assert check.detail == "available"


def test_pio_missing(monkeypatch, tmp_path):
    """When neither pio executable nor platformio module works, check fails."""
    monkeypatch.setattr("shutil.which", lambda cmd: None)

    def fake_subprocess_run(cmd, **kwargs):
        raise FileNotFoundError("python not found")

    monkeypatch.setattr("subprocess.run", fake_subprocess_run)

    results = run_preflight(project_root=tmp_path)
    check = _get_check(results, "PlatformIO (pio)")
    assert check.ok is False
    assert check.detail == "missing"
    assert "pip install platformio" in check.hint


def test_firmware_hex_missing(monkeypatch, tmp_path):
    """When firmware.hex does not exist, check fails."""
    # tmp_path does not contain firmware.hex
    results = run_preflight(project_root=tmp_path)
    check = _get_check(results, "firmware.hex")
    assert check.ok is False
    assert check.detail == "missing"
    assert "pio run" in check.hint


def test_keys_never_leaked(monkeypatch, tmp_path):
    """Secret values are NEVER present in check results."""
    secret_key = "SECRET_API_KEY_99999"
    secret_token = "SECRET_TOKEN_88888"

    monkeypatch.setenv("GEMINI_API_KEY", secret_key)
    monkeypatch.setenv("WOKWI_CLI_TOKEN", secret_token)

    results = run_preflight(project_root=tmp_path)

    for item in results:
        assert secret_key not in item.name
        assert secret_key not in item.detail
        assert secret_key not in item.hint
        assert secret_token not in item.name
        assert secret_token not in item.detail
        assert secret_token not in item.hint
        # Verify str representation also doesn't contain the secret
        assert secret_key not in str(item)
        assert secret_token not in str(item)
