"""Test evaluator: deterministic pass/fail decision based on exit codes and serial logs."""

import re
from agent.models import TestCase, TestResult

ANSI_ESCAPE_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
FIRMWARE_PREFIXES = ("[INFO]", "[DATA]", "[ALARM]", "[ERROR]")


def strip_ansi(text: str) -> str:
    """Remove ANSI escape codes from raw text."""
    return ANSI_ESCAPE_RE.sub("", text)


def extract_firmware_lines(raw_output: str) -> list[str]:
    """Extract only genuine firmware serial output lines.

    Excludes all simulator control output (e.g. 'Expected text matched',
    'Scenario completed successfully', 'Timeout:', 'Wokwi CLI', 'Connected to',
    'Starting simulation').
    """
    clean_text = strip_ansi(raw_output)
    firmware_lines: list[str] = []
    for raw_line in clean_text.splitlines():
        line = raw_line.strip()
        if any(line.startswith(prefix) for prefix in FIRMWARE_PREFIXES):
            firmware_lines.append(line)
    return firmware_lines


def collapse_firmware_lines(firmware_lines: list[str]) -> list[str]:
    """Format and collapse consecutive identical firmware lines with counts.

    Strips [DATA] prefix for clean display while preserving [ALARM], [ERROR], [INFO].
    Example:
        ['[DATA] temp=30.0 fan=OFF', '[DATA] temp=30.0 fan=OFF']
        -> ['temp=30.0 fan=OFF (x2)']
    """
    if not firmware_lines:
        return []

    cleaned: list[str] = []
    for line in firmware_lines:
        if line.startswith("[DATA] "):
            cleaned.append(line[7:].strip())
        else:
            cleaned.append(line)

    collapsed: list[str] = []
    current_line = cleaned[0]
    count = 1

    for line in cleaned[1:]:
        if line == current_line:
            count += 1
        else:
            if count > 1:
                collapsed.append(f"{current_line} (x{count})")
            else:
                collapsed.append(current_line)
            current_line = line
            count = 1

    if count > 1:
        collapsed.append(f"{current_line} (x{count})")
    else:
        collapsed.append(current_line)

    return collapsed


def evaluate(
    test: TestCase,
    raw_output: str,
    exit_code: int,
    duration_s: float = 0.0,
) -> TestResult:
    """Evaluate test outcome deterministically from simulator output and exit code.

    Verdict rules:
    - exit 0 and no test.must_not string in firmware lines -> PASS
    - exit 0 but a must_not string appears -> FAIL (fills violated_must_not)
    - exit 42 -> FAIL (Wokwi scenario expectation timeout)
    - any other exit code or subprocess crash -> ERROR with error_message
    - Safety check: if exit is 0 but none of the expected strings appear in the
      firmware lines, return ERROR "inconsistent: exit 0 but expected text not seen".
    """
    firmware_lines = extract_firmware_lines(raw_output)
    collapsed_observed = collapse_firmware_lines(firmware_lines)

    # Check for must_not violations
    violated_must_not: list[str] = []
    if test.must_not:
        for forbidden in test.must_not:
            if any(forbidden in line for line in firmware_lines):
                violated_must_not.append(forbidden)

    # Check which expected strings were observed in firmware lines
    expected_strings = [e.serial_contains for e in test.expect]
    seen_expected = [
        exp
        for exp in expected_strings
        if any(exp in line for line in firmware_lines)
    ]
    missing_expected = [
        exp for exp in expected_strings if exp not in seen_expected
    ]

    status: str
    error_message: str | None = None

    if exit_code == 0:
        if "Scenario completed successfully" in raw_output and expected_strings and not seen_expected:
            # Safety check: Wokwi claimed scenario success, but expected serial was never actually printed
            status = "ERROR"
            error_message = (
                "inconsistent: exit 0 but expected text not seen in firmware output"
            )
        elif not firmware_lines and expected_strings:
            # Firmware exited 0 but produced no valid serial lines at all
            status = "ERROR"
            error_message = (
                "inconsistent: exit 0 but no firmware serial lines were output"
            )
        elif missing_expected:
            status = "FAIL"
            error_message = (
                f"Expected serial output not observed: {missing_expected}"
            )
        elif violated_must_not:
            status = "FAIL"
            error_message = (
                f"Violated forbidden must_not string(s): {violated_must_not}"
            )
        else:
            status = "PASS"
    elif exit_code == 42:
        status = "FAIL"
        error_message = (
            "Simulation timed out waiting for expected serial text (exit code 42)"
        )
    else:
        status = "ERROR"
        error_message = f"Simulation failed with exit code {exit_code}"

    return TestResult(
        test_id=test.id,
        status=status,  # type: ignore
        exit_code=exit_code,
        duration_s=round(duration_s, 2),
        expected=expected_strings,
        observed_lines=collapsed_observed,
        serial_log=raw_output,
        violated_must_not=violated_must_not,
        missing_expected=missing_expected,
        error_message=error_message,
    )
