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
   - "boundary": temperatures exactly on or immediately adjacent to thresholds (30.0 °C, 29.9 °C, 30.1 °C).
   - "abnormal": extreme valid DHT22 sensor readings (-40.0 °C, 80.0 °C) or rapid shifts.
   - "sensor_failure": sensor disconnected test with sensor="disconnected", expecting fail-safe "[ERROR] SENSOR_FAIL" and "fan=ON".
   - "recovery": recovery from extreme thermal conditions (e.g. 65.0 °C overheat down to 25.0 °C normal).
   - "sequence": dynamic multi-step sequences, especially verifying hysteresis (e.g. 31.0 °C -> 29.0 °C where fan must stay ON; 31.0 °C -> 28.0 °C where fan stays ON; 31.0 °C -> 27.9 °C where fan turns OFF).
   - "combination": multi-step transitions combining thresholds, alarms, and normal states.

2. SPEC IS THE ORACLE:
   - Expected values MUST come from the specification rules, NEVER from buggy code behavior.
   - Example: if spec says fan ON at >= 30.0 °C, expected result for 30.0 °C MUST be fan=ON, even if the code currently checks `t > 30.0`.
   - If spec says hysteresis stays ON until <= 28.0 °C, 31.0 -> 29.0 MUST expect fan=ON.
   - If spec says sensor failure prints "[ERROR] SENSOR_FAIL" and fan ON, expect those even if code lacks isnan() checks.

3. MANDATORY TESTS: You MUST include at least the following test cases:
   - Boundary: temp 30.0 °C (fan=ON, spec R1)
   - Boundary: temp 29.9 °C (fan=OFF)
   - Boundary: temp 30.1 °C (fan=ON)
   - Hysteresis sequence: 31.0 °C then 29.0 °C (fan stays ON, spec R2)
   - Hysteresis sequence: 31.0 °C then 28.0 °C (fan stays ON until <= 28.0, spec R2)
   - Hysteresis boundary: 31.0 °C then 27.9 °C (fan turns OFF, spec R2)
   - Overheat: 60.0 °C (expects "[ALARM] OVERHEAT" and "fan=ON", spec R4)
   - Normal low: 25.0 °C (fan=OFF, spec R3)
   - Normal high: 45.0 °C (fan=ON, spec R1)
   - Thermal recovery: 65.0 °C then 25.0 °C (recovers from overheat to room temp, fan=OFF)
   - Sensor failure: sensor="disconnected" (expects "[ERROR] SENSOR_FAIL" and "fan=ON", spec R5)
   - DO NOT generate any test for sensor reconnect / rule R6 (sensor reconnect cannot be simulated in Wokwi).

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

Generate 12 to 20 test cases conforming to the TestList JSON schema (containing the 'tests' array)."""


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

Please fix all validation errors and return a corrected TestList JSON with 12 to 20 tests."""
