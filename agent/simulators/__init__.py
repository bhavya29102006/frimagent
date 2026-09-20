"""Simulators package for FirmAgent."""

from agent.simulators.base import BaseSimulator
from agent.simulators.gazebo_sim import GazeboSimulator
from agent.simulators.mock_sim import VirtualMockSimulator
from agent.simulators.native_sim import NativeHostSimulator
from agent.simulators.python_sim import PythonSimulator
from agent.simulators.registry import (
    detect_firmware_language,
    get_simulator,
    list_available_simulators,
    register_simulator,
)
from agent.simulators.wokwi_sim import WokwiSimulator

__all__ = [
    "BaseSimulator",
    "WokwiSimulator",
    "VirtualMockSimulator",
    "NativeHostSimulator",
    "PythonSimulator",
    "GazeboSimulator",
    "get_simulator",
    "list_available_simulators",
    "register_simulator",
    "detect_firmware_language",
]
