"""Unit tests for agent/syntax_fixer.py."""

from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from agent.syntax_fixer import (
    SyntaxFixProposal,
    auto_fix_syntax_errors,
    check_firmware_syntax,
    restore_firmware_backup,
)


def test_check_firmware_syntax_clean(tmp_path):
    """Clean firmware build returns (True, log)."""
    with patch("agent.syntax_fixer.build_firmware") as mock_build:
        mock_build.return_value = (True, "Compiling... Success", {"hex": tmp_path / "firmware.hex"})
        clean, log = check_firmware_syntax(tmp_path)
        assert clean is True
        assert "Success" in log


def test_auto_fix_syntax_errors_already_clean(tmp_path):
    """When firmware is already clean, auto_fix_syntax_errors returns status CLEAN."""
    src_dir = tmp_path / "src"
    src_dir.mkdir(parents=True)
    (src_dir / "main.cpp").write_text("void setup() {}\nvoid loop() {}", encoding="utf-8")

    with patch("agent.syntax_fixer.check_firmware_syntax") as mock_check:
        mock_check.return_value = (True, "Clean build")
        res = auto_fix_syntax_errors(tmp_path)
        assert res["status"] == "CLEAN"
        assert "clean" in res["message"].lower()


def test_auto_fix_syntax_errors_successful_repair(tmp_path):
    """When compiler syntax error occurs, LLM repair resolves it and returns status FIXED with diff."""
    src_dir = tmp_path / "src"
    src_dir.mkdir(parents=True)
    broken_code = "void setup() {\n  int x = 5\n}\nvoid loop() {}"
    fixed_code = "void setup() {\n  int x = 5;\n}\nvoid loop() {}"
    (src_dir / "main.cpp").write_text(broken_code, encoding="utf-8")

    proposal = SyntaxFixProposal(
        explanation="Added missing semicolon on line 2",
        errors_addressed=["Missing semicolon ';' before '}' token"],
        fixed_code=fixed_code,
    )

    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.text = proposal.model_dump_json()
    mock_client.models.generate_content.return_value = mock_resp

    # First check fails, second check (after repair) succeeds
    with patch("agent.syntax_fixer.check_firmware_syntax") as mock_check:
        mock_check.side_effect = [(False, "error: expected ';' before '}'"), (True, "Compiling... Success")]
        res = auto_fix_syntax_errors(tmp_path, client=mock_client, model="gemini-test")

        assert res["status"] == "FIXED"
        assert "successfully resolved" in res["message"].lower()
        assert "+  int x = 5;" in res["diff"]
        assert (src_dir / "main.cpp").read_text(encoding="utf-8") == fixed_code
        assert (src_dir / "main.cpp.bak").is_file()


def test_auto_fix_syntax_errors_rollback_on_failed_repair(tmp_path):
    """When LLM repair still fails compilation, original file is restored from backup."""
    src_dir = tmp_path / "src"
    src_dir.mkdir(parents=True)
    broken_code = "void setup() {\n  bad_syntax()\n}"
    bad_attempt = "void setup() {\n  bad_syntax();;\n}"
    (src_dir / "main.cpp").write_text(broken_code, encoding="utf-8")

    proposal = SyntaxFixProposal(
        explanation="Attempted syntax fix",
        errors_addressed=["syntax error"],
        fixed_code=bad_attempt,
    )

    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.text = proposal.model_dump_json()
    mock_client.models.generate_content.return_value = mock_resp

    # Both first and second checks fail
    with patch("agent.syntax_fixer.check_firmware_syntax") as mock_check:
        mock_check.side_effect = [(False, "error: undeclared function"), (False, "still failing")]
        res = auto_fix_syntax_errors(tmp_path, client=mock_client, model="gemini-test")

        assert res["status"] == "FAILED"
        # Verify rollback occurred
        assert (src_dir / "main.cpp").read_text(encoding="utf-8") == broken_code


def test_restore_firmware_backup(tmp_path):
    """Restoring from backup replaces main.cpp with main.cpp.bak."""
    src_dir = tmp_path / "src"
    src_dir.mkdir(parents=True)
    (src_dir / "main.cpp").write_text("modified", encoding="utf-8")
    (src_dir / "main.cpp.bak").write_text("original", encoding="utf-8")

    ok = restore_firmware_backup(tmp_path)
    assert ok is True
    assert (src_dir / "main.cpp").read_text(encoding="utf-8") == "original"
