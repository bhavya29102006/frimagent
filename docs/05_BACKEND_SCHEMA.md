# 05 — Backend Schema

There is **no database and no login**. Data lives as JSON files on disk, one folder per run. The "schema" below is the set of Pydantic models that every module uses.

## 1. Entities
| Entity | Meaning |
|--------|---------|
| RunManifest | One execution of the whole pipeline |
| FirmwareAnalysis | What the agent understood about the firmware |
| SpecRule | One rule of intended behaviour (R1, R2…) |
| TestCase | One generated test (steps + expected behaviour) |
| TestResult | Outcome of executing one TestCase |
| Finding | Explanation of one failure (cause, lines, fix) |
| Report | Final summary built from all of the above |

## 2. Folder layout per run
```
runs/<run_id>/            # run_id = YYYYMMDD-HHMMSS
├── manifest.json
├── firmware_source.txt   # the exact code that was analysed
├── analysis.json
├── tests.json            # all tests, tagged round 0 (initial) or 1..2 (follow-up)
├── results.json
├── findings.json
├── report.md
├── report.html
└── sim/<test_id>/        # temp Wokwi project, scenario.yaml, serial.log
runs/golden/              # a saved perfect run used by Replay mode
```

## 3. Pydantic models (copy into `agent/models.py`)
```python
from typing import Literal, Optional
from pydantic import BaseModel, Field

Category = Literal["normal", "boundary", "abnormal", "sensor_failure",
                   "recovery", "sequence", "combination", "followup"]

class SpecRule(BaseModel):
    id: str                       # "R1"
    text: str                     # plain-English rule
    source_lines: list[int] = []  # firmware lines that implement it
    confidence: Literal["spec", "inferred"] = "spec"

class FirmwareAnalysis(BaseModel):
    summary: str
    inputs: list[str]             # e.g. "DHT22 temperature on pin 2"
    outputs: list[str]            # e.g. "Fan LED on pin 13", "Serial logs"
    constants: dict[str, str]     # thresholds e.g. {"ON_THRESHOLD": "30.0"}
    states: list[str]
    error_handling: list[str]
    communication: list[str]
    spec_rules: list[SpecRule]
    risk_areas: list[str]         # places bugs are likely

class TestStep(BaseModel):
    set_temp: Optional[float] = None   # DHT22 temperature to apply
    wait_ms: int = 2500                # how long to wait after the change

class Expectation(BaseModel):
    serial_contains: str               # matched in order using wait-serial
    spec_ref: Optional[str] = None     # "R1"

class TestCase(BaseModel):
    id: str                            # "T01", follow-ups "F01"
    name: str
    category: Category
    sensor: Literal["normal", "disconnected"] = "normal"
    steps: list[TestStep]              # max 6
    expect: list[Expectation]          # at least 1
    must_not: list[str] = []           # strings that must NEVER appear in serial
    rationale: str
    round: int = 0                     # 0 = initial, 1..2 = follow-up

class TestResult(BaseModel):
    test_id: str
    status: Literal["PASS", "FAIL", "ERROR"]
    exit_code: Optional[int] = None
    duration_s: float = 0.0
    expected: list[str]
    observed_lines: list[str]          # relevant serial lines
    serial_log: str
    violated_must_not: list[str] = []
    error_message: Optional[str] = None

class Finding(BaseModel):
    id: str                            # "FIND-1"
    title: str
    failed_tests: list[str]
    spec_ref: Optional[str] = None
    expected: str
    observed: str
    likely_cause: str
    suspect_lines: list[int]
    suggested_fix: str
    severity: Literal["low", "medium", "high"]

class RunManifest(BaseModel):
    run_id: str
    firmware_name: str
    started_at: str
    finished_at: Optional[str] = None
    status: Literal["running", "done", "failed"]
    total_tests: int = 0
    passed: int = 0
    failed: int = 0
    errors: int = 0
    followup_rounds: int = 0
```

## 4. Relationships
`FirmwareAnalysis.spec_rules[*].id` ← referenced by `TestCase.expect[*].spec_ref` ← referenced by `Finding.spec_ref`. `TestResult.test_id` = `TestCase.id`. `Finding.failed_tests` lists `TestResult.test_id` values.

## 5. Ownership and authorization
Single local user. No auth. Secrets (`GEMINI_API_KEY`, `WOKWI_CLI_TOKEN`, `GEMINI_MODEL`) are read from `.env` only and never written into run folders.

## 6. Data validation rules
- `TestCase.id` unique in a run; follow-up ids start with `F`.
- `set_temp` between **-40 and 80** (DHT22 range). Extra out-of-range checks are done by firmware logic tests, not by the simulator.
- `wait_ms` between 500 and 10000. Steps per test at most 6. Tests per round at most 20.
- `serial_contains` must be a literal string (no regex) and non-empty.
- Firmware upload: `.cpp`, `.ino`, `.c`, `.h`, under 200 KB.
- If the LLM returns invalid JSON, retry once with the validation error appended; then fail with a readable message.

## 7. LLM contracts (what each call receives and returns)
| Call | Input sent to LLM | Output (validated JSON) |
|------|-------------------|--------------------------|
| Analyzer | Firmware source **with line numbers** only | `FirmwareAnalysis` |
| Generator | `FirmwareAnalysis` + source | `{"tests": [TestCase, …]}` (12–20 tests, at least 6 categories) |
| Follow-up | Failed `TestCase`s, their observed logs, analysis | `{"tests": [TestCase, …]}` (max 6, category `followup`) |
| Root cause | Numbered source + failed results + spec rules | `{"findings": [Finding, …]}` |

**Prompt rules for all calls:**
1. Output JSON only, matching the schema.
2. Expected serial strings must follow the firmware's real output format (`[DATA] temp=31.0 fan=ON`).
3. Only use temperatures the DHT22 can produce (-40 to 80, one decimal).
4. The generator must cover: normal, boundary (exactly on and just around thresholds), abnormal, sensor disconnected, recovery, sequences (rise-then-fall), and combinations.
5. Do **not** invent behaviour that is not in the spec or the code. If unsure, set `confidence: "inferred"` on the rule.

## 8. Retention and deletion
`runs/` is git-ignored. Old runs may be deleted by hand. `runs/golden/` is committed (or backed up) so Replay mode always works.

## 9. Seed data
- `firmware/fan_controller/` (demo firmware + Wokwi project)
- `runs/golden/` created after the first fully successful run (task TASK-017)
