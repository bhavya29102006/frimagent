"""Base abstract class for FirmAgent simulator engines."""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from agent.models import TestCase, TestResult


class BaseSimulator(ABC):
    """Abstract base class that every simulator engine plugin must implement."""

    name: str = "base"
    display_name: str = "Base Simulator"
    supported_languages: list[str] = ["cpp", "c", "ino"]

    @abstractmethod
    def is_available(self) -> tuple[bool, str]:
        """Check if this simulator is available on the current host.

        Returns:
            tuple[bool, str]: (is_available, description_or_missing_hint)
        """
        pass

    @abstractmethod
    def run_test(
        self,
        test: TestCase,
        firmware_dir: Path | str,
        run_dir: Path | str,
    ) -> TestResult:
        """Execute a single TestCase and return a verified TestResult."""
        pass
