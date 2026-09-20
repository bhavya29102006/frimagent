"""All prompt templates for analysis, test generation, follow-up, and root cause."""


ANALYZER_SYSTEM_INSTRUCTIONS = """You are an embedded firmware analysis expert.
Analyze the provided firmware source code (which has line numbers prefixed) and extract a structured technical profile.

RULES:
1. Examine the source code and any comment blocks at the top carefully.
2. If there is a SPECIFICATION block (e.g. R1, R2, ...), extract each rule with confidence "spec" and record the exact source line numbers in the code that implement or attempt to implement that rule.
3. If there is no specification block in the comments, infer the intended rules from the logic with confidence "inferred".
4. Extract hardware inputs (e.g. sensor type and pin), outputs (e.g. actuators, LEDs, serial baud rate), thresholds/constants, states, error handling routines, and communication messages.
5. Identify "risk_areas": specific areas in the code where implementation might deviate from the spec or best practices (e.g., comparison operators like strict > vs >=, missing hysteresis state tracking, missing NaN/error checks on sensor reads).
6. Output MUST strictly conform to the FirmwareAnalysis JSON schema.
"""


def make_analyzer_prompt(numbered_source: str) -> str:
    """Generate prompt for analyzing firmware source code."""
    return f"""{ANALYZER_SYSTEM_INSTRUCTIONS}

FIRMWARE SOURCE CODE (WITH LINE NUMBERS):
```
{numbered_source}
```

Extract the technical profile into the FirmwareAnalysis JSON schema."""


GENERATOR_SYSTEM_INSTRUCTIONS = """You are an automated embedded firmware test generation expert.
Generate between 12 and 20 targeted test cases based on the provided Firmware Analysis and numbered source code.

TEST SUITE RULES:
1. QUANTITY & CATEGORIES: Generate between 12 and 20 tests. You MUST cover ALL 7 of these categories:
   - "normal": standard operating conditions (e.g. room temp 25.0 °C -> fan OFF; hot temp 45.0 °C -> fan ON).
   - "boundary": temperatures exactly on or immediately adjacent to thresholds (at least 4 boundary tests required: 29.9 °C, 30.0 °C, 30.1 °C, 59.9 °C, 60.0 °C).
   - "abnormal": extreme valid DHT22 sensor readings (-40.0 °C, 80.0 °C) and rapid thermal changes (25.0 °C -> 45.0 °C -> 25.0 °C).
   - "sensor_failure": sensor disconnected test with sensor="disconnected", expecting fail-safe "[ERROR] SENSOR_FAIL" and "fan=ON".
   - "recovery": recovery from extreme thermal conditions (e.g. 65.0 °C overheat down to 25.0 °C normal).
   - "sequence": dynamic multi-step sequences verifying hysteresis (e.g. 31.0 °C -> 28.1 °C where fan stays ON; 31.0 °C -> 28.0 °C where fan turns OFF; 31.0 °C -> 27.9 °C where fan turns OFF).
   - "combination": multi-step transitions combining thresholds, alarms, and normal states.

2. SPEC IS THE ORACLE:
   - Expected values MUST come strictly from the specification rules, NEVER from current code implementation or planted bugs.
   - Example: if spec says fan ON at >= 30.0 °C, expected result for 30.0 °C MUST be fan=ON, even if the code currently checks `t > 30.0`.
   - Hysteresis rule R2 (per DECISIONS.md #9): with fan ON, at exactly 28.0 °C the fan turns OFF (<= 28.0). Above 28.0 °C (e.g. 28.1 °C) it stays ON.
   - If spec says sensor failure prints "[ERROR] SENSOR_FAIL" and fan ON, expect those even if code lacks isnan() checks.

3. MANDATORY TARGET TEST POINTS: You MUST include tests covering the following specific points:
   - Boundary at threshold: 29.9 °C (fan=OFF, spec R3), 30.0 °C (fan=ON, spec R1), 30.1 °C (fan=ON, spec R1).
   - Alarm boundary: 59.9 °C (fan=ON, no alarm), 60.0 °C (fan=ON, "[ALARM] OVERHEAT", spec R4).
   - Hysteresis sequence: 31.0 °C -> 28.1 °C (fan stays ON, spec R2).
   - Hysteresis sequence: 31.0 °C -> 28.0 °C (fan turns OFF at <= 28.0 C, spec R2 / DECISIONS.md #9).
   - Hysteresis boundary: 31.0 °C -> 27.9 °C (fan turns OFF, spec R2).
   - Temperature extremes: -40.0 °C (DHT22 min, fan=OFF, spec R3) and 80.0 °C (DHT22 max, fan=ON, "[ALARM] OVERHEAT", spec R4).
   - Rapid thermal change: 25.0 °C -> 45.0 °C -> 25.0 °C (normal rise and fall).
   - Sensor failure: sensor="disconnected" (expects "[ERROR] SENSOR_FAIL" and "fan=ON", spec R5).
   - DO NOT generate any test for sensor reconnect or rule R6 (sensor reconnect cannot be simulated in Wokwi, see DECISIONS.md).

4. HARDWARE & SERIAL CONSTRAINTS:
   - Temperatures MUST be within DHT22 range: -40.0 to 80.0, formatted to 1 decimal place (e.g. 30.0, -40.0).
   - Steps per test: 1 to 6 steps. Default wait_ms is 2500.
   - Serial format is exactly: "[DATA] temp=<x.x> fan=<ON|OFF>".
     Each expect.serial_contains must look like "temp=31.0 fan=ON" (one decimal, uppercase ON/OFF) or "[ALARM] OVERHEAT" or "[ERROR] SENSOR_FAIL".
   - Unique IDs: "T01", "T02", "T03", ... in sequential order.
   - Set round = 0 for all initial generated tests.
"""


def make_generator_prompt(analysis_json: str, numbered_source: str) -> str:
    """Generate prompt for test case generation."""
    return f"""{GENERATOR_SYSTEM_INSTRUCTIONS}

FIRMWARE ANALYSIS:
```json
{analysis_json}
```

FIRMWARE SOURCE CODE (WITH LINE NUMBERS):
```
{numbered_source}
```

Generate EXACTLY 16 test cases (T01 through T16) conforming to the TestList JSON schema (containing the 'tests' array), ensuring complete category coverage:
- normal (at least 1)
- boundary (at least 4: including 29.9, 30.0, 30.1, 59.9, 60.0)
- abnormal (at least 1: extremes -40.0, 80.0)
- sensor_failure (at least 1: sensor disconnected)
- recovery (at least 1)
- sequence (at least 1: hysteresis at 28.1, 28.0, 27.9 after being ON)
- combination (at least 1: rapid change 25 -> 45 -> 25)
Total must be EXACTLY 16 tests."""


def make_generator_topup_prompt(
    analysis_json: str,
    numbered_source: str,
    missing_categories: list[str],
    boundary_needed: int,
    existing_count: int,
) -> str:
    """Generate prompt asking for ONLY missing categories/tests to achieve complete coverage."""
    items = []
    if missing_categories:
        items.append(
            f"Missing categories requiring at least 1 test each: {', '.join(missing_categories)}"
        )
    if boundary_needed > 0:
        items.append(f"Additional 'boundary' tests needed: {boundary_needed}")

    requirements_text = "\n".join(f"- {item}" for item in items)
    start_id = existing_count + 1

    return f"""{GENERATOR_SYSTEM_INSTRUCTIONS}

TOP-UP COVERAGE REQUEST:
The test suite is missing coverage for specific categories. Generate ONLY the test cases specified below to fill the gaps:
{requirements_text}

CONSTRAINTS:
- Generate ONLY the required test cases to satisfy the missing categories above.
- Number test IDs sequentially starting from T{start_id:02d}.
- Expected serial strings must strictly reflect the specification rules.
- Set round = 0.
- Return valid JSON matching the TestList schema.

FIRMWARE ANALYSIS:
```json
{analysis_json}
```

FIRMWARE SOURCE CODE (WITH LINE NUMBERS):
```
{numbered_source}
```"""


def make_generator_repair_prompt(
    previous_json: str, validation_errors: list[str]
) -> str:
    """Generate repair prompt when test suite fails Python validation."""
    error_list = "\n".join(f"- {err}" for err in validation_errors)
    return f"""The generated test suite had validation errors that violate test constraints:

VALIDATION ERRORS:
{error_list}

PREVIOUS OUTPUT:
```json
{previous_json}
```

Please fix all validation errors and return a corrected TestList JSON with EXACTLY 16 tests (T01 to T16)."""


ROOTCAUSE_SYSTEM_INSTRUCTIONS = """You are an expert embedded firmware debugging and root-cause analysis assistant.
Your job is to analyze failed simulation tests against the firmware specification rules and the numbered firmware source code.

DIAGNOSIS RULES:
1. EXAMINE FAILURES: Review each failed test case, its test category, expected serial outputs, and observed serial output.
2. GROUP BY ROOT CAUSE: If multiple failed tests stem from the same root software defect (e.g., boundary tests failed due to a strict inequality check like `t > 30.0` instead of `>= 30.0`), GROUP them into a single Finding. List all relevant test IDs in `failed_tests`.
3. PINPOINT SUSPECT LINES: Identify the exact line numbers (1-indexed) in the numbered source code responsible for the defect or where missing checks/logic should be located.
4. SPEC REFERENCE: Link each finding to the violated specification rule ID (e.g. "R1", "R2", "R5").
5. SUGGEST A FIX: Provide a concrete, precise code fix or replacement code in C/C++ that resolves the bug.
6. SEVERITY:
   - "high": Safety hazards, missing fail-safes (e.g. missing NaN sensor error handling), or hardware damage risks.
   - "medium": State tracking issues (e.g. missing hysteresis), boundary violations, or logic flaws.
   - "low": Minor timing or cosmetic reporting discrepancies.
7. OUTPUT: Return valid JSON strictly matching the FindingList schema (containing a 'findings' array of Finding objects).
"""


def make_rootcause_prompt(
    numbered_source: str,
    spec_rules_summary: str,
    failed_tests_summary: str,
) -> str:
    """Generate prompt for root-cause diagnosis of failed tests."""
    return f"""{ROOTCAUSE_SYSTEM_INSTRUCTIONS}

SPECIFICATION RULES:
{spec_rules_summary}

FAILED SIMULATION TEST RESULTS:
{failed_tests_summary}

FIRMWARE SOURCE CODE (WITH LINE NUMBERS):
```
{numbered_source}
```

Perform root-cause analysis and return all findings conforming to the FindingList JSON schema."""


FOLLOWUP_SYSTEM_INSTRUCTIONS = """You are an expert autonomous firmware test generation assistant.
Your job is to generate focused follow-up test cases (probing tests) to investigate failed tests from the initial simulation run.

FOLLOW-UP RULES:
1. TARGETED PROBING:
   - For a failed boundary threshold (e.g. 30.0 °C), generate tests immediately adjacent: 29.9 °C, 30.1 °C.
   - For a failed hysteresis sequence (e.g. 31.0 °C -> 29.0 °C), probe intermediate points: 31.0 °C -> 28.0 °C, 31.0 °C -> 27.9 °C.
   - For a sensor disconnect failure, test variations in timing or recovery.
2. CONSTRAINTS:
   - Generate between 2 and 6 focused test cases.
   - Set category to "followup" for all generated tests.
   - Test IDs must start with 'F' (e.g. "F01", "F02", "F03").
   - Set round to the requested follow-up round (e.g. 1).
   - Temperatures must be valid DHT22 numbers (-40.0 to 80.0, 1 decimal place).
   - Serial format must follow firmware specification: "[DATA] temp=<x.x> fan=<ON|OFF>".
3. OUTPUT: Return valid JSON strictly matching the TestList schema (containing a 'tests' array of TestCase objects).
"""


def make_followup_prompt(
    failed_tests_summary: str,
    analysis_json: str,
    numbered_source: str,
    round_num: int = 1,
) -> str:
    """Generate prompt for creating probing follow-up tests around failures."""
    return f"""{FOLLOWUP_SYSTEM_INSTRUCTIONS}

ROUND NUMBER: {round_num}

FAILED INITIAL TEST CASES:
{failed_tests_summary}

FIRMWARE SPECIFICATION & ANALYSIS:
```json
{analysis_json}
```

FIRMWARE SOURCE CODE (WITH LINE NUMBERS):
```
{numbered_source}
```

Generate 2 to 6 targeted follow-up test cases conforming to the TestList JSON schema (category='followup', ids starting with 'F01')."""


PATCH_SYSTEM_INSTRUCTIONS = """You are an expert embedded firmware bug-fixing assistant.
Your task is to propose minimal, robust code patches (in C/C++) to fix the software bugs identified in the provided root-cause findings and failed simulation tests.

STRICT CONSTRAINTS:
1. MINIMAL CHANGE: Make the smallest necessary change that completely resolves the defects.
2. LIMITS: At most 3 hunks and at most 25 changed lines total across all hunks.
3. PROTECTED RANGES:
   - NEVER touch or modify the top SPECIFICATION comment block (from line 1 to the line containing '*/').
   - NEVER touch or modify '#include' or '#define' lines.
4. EXACT ORIGINAL CODE & LINE BOUNDS:
   - For every hunk, 'original_code' must be copied EXACTLY as it appears in the numbered source between 'start_line' and 'end_line' (without line numbers).
   - 'start_line' and 'end_line' are 1-indexed line numbers in the original source code.
   - 'end_line' MUST equal 'start_line + (number of lines in original_code) - 1'. Remember that blank lines also count as lines! For instance, lines 39 to 41 is 3 lines.
5. TESTS FIXED:
   - In each hunk, list the exact test IDs it resolves in 'fixes_tests' (e.g. ["T02", "T03"]).
6. OUTPUT: Return valid JSON strictly conforming to the PatchProposal schema (containing 'hunks' array and a 'summary').
"""


def make_patch_prompt(
    numbered_source: str,
    failed_tests_summary: str,
    findings_summary: str,
) -> str:
    """Generate prompt for proposing a code patch."""
    return f"""{PATCH_SYSTEM_INSTRUCTIONS}

ROOT-CAUSE FINDINGS:
{findings_summary}

FAILED SIMULATION TEST RESULTS:
{failed_tests_summary}

FIRMWARE SOURCE CODE (WITH LINE NUMBERS):
```
{numbered_source}
```

Propose a patch that resolves these defects conforming to the PatchProposal JSON schema."""
