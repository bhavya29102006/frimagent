"""Pydantic data models for FirmAgent (see docs/05_BACKEND_SCHEMA.md)."""

from typing import Literal, Optional
from pydantic import BaseModel, Field

Category = Literal[
    "normal",
    "boundary",
    "abnormal",
    "sensor_failure",
    "recovery",
    "sequence",
    "combination",
    "followup",
]


class SpecRule(BaseModel):
    id: str  # "R1"
    text: str  # plain-English rule
    source_lines: list[int] = []  # firmware lines that implement it
    confidence: Literal["spec", "inferred"] = "spec"


class FirmwareAnalysis(BaseModel):
    summary: str
    inputs: list[str]  # e.g. "DHT22 temperature on pin 2"
    outputs: list[str]  # e.g. "Fan LED on pin 13", "Serial logs"
    constants: dict[str, str]  # thresholds e.g. {"ON_THRESHOLD": "30.0"}
    states: list[str]
    error_handling: list[str]
    communication: list[str]
    spec_rules: list[SpecRule]
    risk_areas: list[str]  # places bugs are likely


class TestStep(BaseModel):
    set_temp: Optional[float] = None  # DHT22 temperature to apply
    wait_ms: int = 2500  # how long to wait after the change


class Expectation(BaseModel):
    serial_contains: str  # matched in order using wait-serial
    spec_ref: Optional[str] = None  # "R1"


class TestCase(BaseModel):
    id: str  # "T01", follow-ups "F01"
    name: str
    category: Category
    sensor: Literal["normal", "disconnected"] = "normal"
    steps: list[TestStep]  # max 6
    expect: list[Expectation]  # at least 1
    must_not: list[str] = []  # strings that must NEVER appear in serial
    rationale: str
    round: int = 0  # 0 = initial, 1..2 = follow-up


class TestResult(BaseModel):
    test_id: str
    status: Literal["PASS", "FAIL", "ERROR"]
    exit_code: Optional[int] = None
    duration_s: float = 0.0
    expected: list[str]
    observed_lines: list[str]  # relevant serial lines
    serial_log: str
    violated_must_not: list[str] = []
    missing_expected: list[str] = []
    error_message: Optional[str] = None


class Finding(BaseModel):
    id: str  # "FIND-1"
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
    status: Literal["running", "done", "failed", "stopped"]
    total_tests: int = 0
    passed: int = 0
    failed: int = 0
    errors: int = 0
    followup_rounds: int = 0


class TestList(BaseModel):
    """Wrapper for list of test cases in LLM generator outputs."""

    tests: list[TestCase]


class FindingList(BaseModel):
    """Wrapper for list of findings in LLM root-cause outputs."""

    findings: list[Finding]


class PatchHunk(BaseModel):
    """Single contiguous modification to the firmware source code."""

    id: str  # "H1", "H2"
    start_line: int  # 1-indexed start line in original source
    end_line: int  # 1-indexed end line in original source
    original_code: str  # Exact text from original source
    new_code: str  # Replacement text
    explanation: str
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    fixes_tests: list[str] = []  # Failed test IDs targeted by this hunk
    spec_ref: Optional[str] = None  # e.g. "R1", "R2"


class PatchProposal(BaseModel):
    """Collection of patch hunks representing a proposed firmware fix."""

    hunks: list[PatchHunk]
    summary: str


class PatchCheck(BaseModel):
    """Result of an individual validation check against a proposed patch."""

    name: str
    ok: bool
    detail: str


class PatchValidation(BaseModel):
    """Comprehensive validation outcome across all safety and build checks."""

    ok: bool
    checks: list[PatchCheck] = []


class FixAttempt(BaseModel):
    """Lifecycle record of a single autonomous fix attempt."""

    attempt_id: str
    status: Literal["proposed", "validated", "rejected", "applied", "reverted"]
    proposal: PatchProposal
    validation: PatchValidation
    before_counts: dict[str, int]
    after_counts: Optional[dict[str, int]] = None
    fixed_tests: list[str] = []
    regressions: list[str] = []


# Prevent pytest from attempting to collect data models as test suites
TestStep.__test__ = False
TestCase.__test__ = False
TestResult.__test__ = False
TestList.__test__ = False
PatchHunk.__test__ = False
PatchProposal.__test__ = False
PatchCheck.__test__ = False
PatchValidation.__test__ = False
FixAttempt.__test__ = False

