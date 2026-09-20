"""Simulator Registry and language detection for FirmAgent."""

from pathlib import Path
from typing import Any, Optional

from agent.simulators.base import BaseSimulator
from agent.simulators.mock_sim import VirtualMockSimulator
from agent.simulators.native_sim import NativeHostSimulator
from agent.simulators.python_sim import PythonSimulator
from agent.simulators.wokwi_sim import WokwiSimulator


_SIMULATORS: dict[str, BaseSimulator] = {
    "wokwi": WokwiSimulator(),
    "virtual_mock": VirtualMockSimulator(),
    "native_c": NativeHostSimulator(),
    "python_sim": PythonSimulator(),
}


def register_simulator(simulator: BaseSimulator) -> None:
    """Register a custom or plugin simulator engine."""
    _SIMULATORS[simulator.name] = simulator


def get_simulator(name: Optional[str] = None) -> BaseSimulator:
    """Retrieve simulator by identifier, defaulting to wokwi or virtual_mock."""
    if not name:
        name = "wokwi"
    if name in _SIMULATORS:
        return _SIMULATORS[name]
    # Fallback to universal virtual mock
    return _SIMULATORS["virtual_mock"]


def list_available_simulators() -> list[dict[str, Any]]:
    """List all registered simulator engines and their availability status."""
    results = []
    for sim_id, sim in _SIMULATORS.items():
        avail, detail = sim.is_available()
        results.append({
            "id": sim_id,
            "name": sim.name,
            "display_name": sim.display_name,
            "supported_languages": sim.supported_languages,
            "available": avail,
            "detail": detail,
        })
    return results


def detect_firmware_language(path_or_content: Path | str) -> str:
    """Detect programming language of firmware from file path or content.

    Returns: 'cpp' | 'c' | 'ino' | 'python'
    """
    if isinstance(path_or_content, (Path, str)):
        s_str = str(path_or_content).lower()
        if s_str.endswith(".py"):
            return "python"
        if s_str.endswith(".ino"):
            return "ino"
        if s_str.endswith(".c") and not s_str.endswith(".cpp"):
            return "c"
        if s_str.endswith(".cpp") or s_str.endswith(".h") or s_str.endswith(".hpp"):
            return "cpp"

    # Check content markers
    content = str(path_or_content)
    if "import " in content and "def " in content:
        return "python"
    if "#include <Arduino.h>" in content or "void setup()" in content or "void loop()" in content:
        return "ino"
    if "#include" in content and "int main(" in content:
        return "cpp"

    return "cpp"
