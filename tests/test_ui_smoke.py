"""Smoke test for app/main.py helper functions and module imports."""

from pathlib import Path
import pytest

from agent.models import TestCase, TestStep
from app.main import format_steps_plain, get_available_runs


def test_format_steps_plain_normal():
    test = TestCase(
        id="T01",
        name="Normal Test",
        category="normal",
        steps=[TestStep(set_temp=25.0, wait_ms=2500), TestStep(set_temp=30.0)],
        expect=[],
        rationale="Step test",
    )
    res = format_steps_plain(test)
    assert res == "Set temp 25.0°C ➔ Set temp 30.0°C"


def test_format_steps_plain_disconnected():
    test = TestCase(
        id="T05",
        name="Disconnect Test",
        category="sensor_failure",
        sensor="disconnected",
        steps=[],
        expect=[],
        rationale="Disconnect test",
    )
    res = format_steps_plain(test)
    assert "Sensor wire disconnected" in res


def test_format_steps_plain_empty():
    test = TestCase(
        id="T06",
        name="Empty steps",
        category="normal",
        steps=[],
        expect=[],
        rationale="Empty",
    )
    assert format_steps_plain(test) == "No input change"


def test_get_available_runs():
    runs = get_available_runs()
    assert isinstance(runs, list)
    assert "cache" not in runs
