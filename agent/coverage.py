"""Coverage computation module for FirmAgent test suites."""

from typing import Any, Optional
from agent.models import TestCase, TestResult

REQUIRED_CATEGORIES = [
    "normal",
    "boundary",
    "abnormal",
    "sensor_failure",
    "recovery",
    "sequence",
    "combination",
]

RULE_DESCRIPTIONS = {
    "R1": "Fan ON at >= 30.0°C",
    "R2": "Fan OFF at <= 28.0°C (hysteresis)",
    "R3": "Fan OFF below 30.0°C initially",
    "R4": "Overheat alarm at >= 60.0°C",
    "R5": "Sensor disconnect fail-safe (fan ON)",
    "R6": "Sensor reconnect recovery",
}


class CoverageResult(dict):
    """Dictionary holding coverage metrics with category and rule lookups.

    Supports both:
    - cov["categories"]["normal"] and cov["normal"]
    - cov["rules"]["R1"] and cov["rules"]["R6"]
    """

    def __getitem__(self, key: str) -> Any:
        if dict.__contains__(self, key):
            return super().__getitem__(key)
        if dict.__contains__(self, "categories") and key in self["categories"]:
            return self["categories"][key]
        raise KeyError(key)

    def __contains__(self, key: object) -> bool:
        return dict.__contains__(self, key) or (
            dict.__contains__(self, "categories") and key in self["categories"]
        )

    def get(self, key: str, default: Any = None) -> Any:
        if dict.__contains__(self, key):
            return super().get(key, default)
        if dict.__contains__(self, "categories") and key in self["categories"]:
            return self["categories"][key]
        return default


def compute_coverage(
    tests: list[TestCase],
    results: Optional[list[TestResult]] = None,
) -> CoverageResult:
    """Compute test category coverage matrix and per-rule mapping.

    Args:
        tests: List of TestCase objects to evaluate.
        results: Optional list of TestResult objects from execution.

    Returns:
        CoverageResult: Dict containing:
            - "categories": category x {total, passed, failed, errors} matrix
              ensuring all 7 required categories are present.
            - "rules": map of R1..R6 to test IDs (using spec_ref).
              R6 is always set to "not testable in simulator".
    """
    res_map = {r.test_id: r.status for r in results} if results else {}

    # Initialize categories matrix with all required categories
    cat_matrix: dict[str, dict[str, int]] = {
        cat: {"total": 0, "passed": 0, "failed": 0, "errors": 0}
        for cat in REQUIRED_CATEGORIES
    }

    # Count tests and map test results
    for t in tests:
        cat = t.category
        if cat not in cat_matrix:
            cat_matrix[cat] = {
                "total": 0,
                "passed": 0,
                "failed": 0,
                "errors": 0,
            }
        cat_matrix[cat]["total"] += 1

        status = res_map.get(t.id)
        if status == "PASS":
            cat_matrix[cat]["passed"] += 1
        elif status == "FAIL":
            cat_matrix[cat]["failed"] += 1
        elif status == "ERROR":
            cat_matrix[cat]["errors"] += 1

    # Map rules R1..R6 using spec_ref in expectations
    rule_ids = ["R1", "R2", "R3", "R4", "R5"]
    rules_map: dict[str, Any] = {r: [] for r in rule_ids}

    for t in tests:
        for exp in t.expect:
            if exp.spec_ref:
                # Handle single or comma/semicolon separated rule references (e.g. "R1", "R1, R2")
                refs = [
                    ref.strip().upper()
                    for ref in exp.spec_ref.replace(";", ",").split(",")
                    if ref.strip()
                ]
                for ref in refs:
                    if ref in rules_map and t.id not in rules_map[ref]:
                        rules_map[ref].append(t.id)

    # Rule R6 is not testable in simulator (DECISIONS.md #3)
    rules_map["R6"] = "not testable in simulator"

    cov = CoverageResult(
        {
            "categories": cat_matrix,
            "rules": rules_map,
        }
    )
    return cov
