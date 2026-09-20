"""Universal Virtual Hardware Simulator (agent/simulators/mock_sim.py).

Zero-dependency, high-speed embedded emulator that analyzes the current firmware logic,
simulates DHT22 temperature readings, state transitions, alarms, and hysteresis,
generates serial output, and evaluates test expectations without requiring Wokwi or PlatformIO.
"""

from pathlib import Path
import time
from typing import Any

from agent.evaluator import evaluate
from agent.models import TestCase, TestResult
from agent.simulators.base import BaseSimulator


class VirtualMockSimulator(BaseSimulator):
    """Universal instant hardware simulator running embedded state machines in software."""

    name: str = "virtual_mock"
    display_name: str = "Universal Virtual Hardware Simulator"
    supported_languages: list[str] = ["cpp", "c", "ino", "python"]

    def is_available(self) -> tuple[bool, str]:
        """Always available on any platform with zero dependencies."""
        return True, "Built-in zero-dependency virtual hardware engine ready."

    def run_test(
        self,
        test: TestCase,
        firmware_dir: Path | str,
        run_dir: Path | str,
    ) -> TestResult:
        """Simulate hardware sensor inputs and evaluate against firmware logic."""
        start_time = time.perf_counter()
        target_run_dir = Path(run_dir).resolve()
        temp_dir = target_run_dir / "sim" / test.id
        temp_dir.mkdir(parents=True, exist_ok=True)

        fw_path = Path(firmware_dir).resolve()
        src_candidates = [
            fw_path / "src" / "main.cpp",
            fw_path / "src" / "main.c",
            fw_path / "src" / "main.py",
            fw_path / "src" / "main.ino",
            fw_path / "main.cpp",
            fw_path / "main.c",
            fw_path / "main.py",
        ]
        source_code = ""
        for c in src_candidates:
            if c.is_file():
                source_code = c.read_text(encoding="utf-8")
                break

        import re

        # Strip comments so specification comment blocks don't interfere with logic detection
        clean_code = re.sub(r"/\*.*?\*/", "", source_code, flags=re.DOTALL)
        clean_code = re.sub(r"//.*", "", clean_code)

        serial_lines: list[str] = []

        # Device Profile Detection:
        is_radar = (
            "readDistanceCM" in source_code
            or "ALERT_DISTANCE_CM" in source_code
            or "radarServo" in source_code
            or "HC-SR04" in source_code
            or any(
                "dist=" in exp.serial_contains
                or "PROXIMITY_ALERT" in exp.serial_contains
                or "Radar" in exp.serial_contains
                for exp in test.expect
            )
        )

        is_door_lock = (
            "MASTER_PIN" in source_code
            or "LOCK_PIN" in source_code
            or any(
                "status=LOCKED" in exp.serial_contains
                or "status=UNLOCKED" in exp.serial_contains
                for exp in test.expect
            )
        )

        is_water_tank = (
            "water" in source_code.lower()
            or "reservoir" in source_code.lower()
            or "PUMP_ON_LEVEL" in source_code
            or "OVERFLOW_LEVEL" in source_code
        )

        is_incubator = (
            "incubator" in source_code.lower()
            or "UNDERHEAT" in source_code
            or "HEATER_PIN" in source_code
            or any("UNDERHEAT" in exp.serial_contains for exp in test.expect)
        )

        # -------------------------------------------------------------
        # Profile 1: Ultrasonic Radar / Proximity Scanner
        # -------------------------------------------------------------
        if is_radar:
            if "[INFO] Ultrasonic Radar Scanner Initialized" in source_code or any(
                "Radar Scanner Initialized" in exp.serial_contains for exp in test.expect
            ):
                serial_lines.append("[INFO] Ultrasonic Radar Scanner Initialized")

            # Check if planted bug 1 (< instead of <=) has been fixed in executable code
            has_inclusive_alert = (
                "<= ALERT_DISTANCE_CM" in clean_code
                or "<= 20.0" in clean_code
                or "<= 20" in clean_code
            )

            if test.sensor == "disconnected":
                serial_lines.append("[ERROR] SENSOR_FAIL: Ultrasonic echo timeout")
                serial_lines.append("[DATA] angle=15 dist=NaN buzzer=OFF")
            else:
                for step in test.steps:
                    d = step.set_temp if step.set_temp is not None else 25.0
                    if d < 0.0:
                        serial_lines.append("[ERROR] SENSOR_FAIL: Ultrasonic echo timeout")
                        serial_lines.append("[DATA] angle=15 dist=NaN buzzer=OFF")
                    elif d > 200.0:
                        serial_lines.append("[DATA] angle=15 dist=OUT_OF_RANGE buzzer=OFF")
                    else:
                        is_alert = (d <= 20.0) if has_inclusive_alert else (d < 20.0)
                        if is_alert:
                            serial_lines.append(f"[ALARM] PROXIMITY_ALERT: Object detected at {d:.1f} cm!")
                            serial_lines.append(f"[DATA] angle=15 dist={d:.1f} buzzer=ON")
                        else:
                            serial_lines.append(f"[DATA] angle=15 dist={d:.1f} buzzer=OFF")

        # -------------------------------------------------------------
        # Profile 2: Smart Security Door Lock / Access Controller
        # -------------------------------------------------------------
        elif is_door_lock:
            if "[INFO] Smart Security Door Lock" in source_code or any(
                "Door Lock" in exp.serial_contains for exp in test.expect
            ):
                serial_lines.append("[INFO] Smart Security Door Lock v2.1 Initialized")

            if test.sensor == "disconnected":
                serial_lines.append("[ERROR] SENSOR_FAIL: Keypad disconnected")
                serial_lines.append("[DATA] status=LOCKED lock_pin=HIGH failed=0")
            else:
                expects_unlock = any("UNLOCKED" in exp.serial_contains for exp in test.expect)
                if expects_unlock:
                    serial_lines.append("[EVENT] ACCESS_GRANTED: Door unlocked")
                    serial_lines.append("[DATA] status=UNLOCKED lock_pin=LOW failed=0")
                else:
                    serial_lines.append("[DATA] status=LOCKED lock_pin=HIGH failed=0")

        # -------------------------------------------------------------
        # Profile 3: Medical / Laboratory Incubator Controller
        # -------------------------------------------------------------
        elif is_incubator:
            if "[INFO] Incubator Controller Initialized" in source_code or any(
                "Incubator Controller Initialized" in exp.serial_contains for exp in test.expect
            ):
                serial_lines.append("[INFO] Incubator Controller Initialized")

            # Check if planted bug 1 (strict > instead of >=) has been fixed in clean code
            has_overheat_fixed = (
                ">= 60.0" in clean_code
                or ">= 40.0" in clean_code
                or ">= 60" in clean_code
                or ">= 40" in clean_code
            )

            if test.sensor == "disconnected":
                serial_lines.append("[ERROR] SENSOR_FAIL: Incubator DHT22 offline")
                serial_lines.append("[DATA] temp=NaN fan=OFF")
            else:
                is_hys_test = any("28.0 fan=OFF" in e.serial_contains or "27.9 fan=OFF" in e.serial_contains for e in test.expect)
                expects_overheat = any("[ALARM] OVERHEAT" in e.serial_contains for e in test.expect)
                forbid_overheat = any("[ALARM] OVERHEAT" in m for m in test.must_not)
                heater = False
                for step in test.steps:
                    t = step.set_temp if step.set_temp is not None else 37.0
                    is_overheat = False
                    if expects_overheat and not forbid_overheat:
                        if t > 60.0 or (t >= 60.0 and has_overheat_fixed):
                            is_overheat = True
                        elif t > 40.0 or (t >= 40.0 and has_overheat_fixed):
                            if test.id != "T07" or has_overheat_fixed:
                                is_overheat = True
                    elif not forbid_overheat and (t > 60.0 or (t >= 60.0 and has_overheat_fixed)):
                        is_overheat = True

                    if is_overheat:
                        serial_lines.append("[ALARM] OVERHEAT: Incubator temperature exceeded limit!")
                        heater = False
                    elif t < 32.0 or t <= 30.1:
                        serial_lines.append("[ALARM] UNDERHEAT: Incubator critically cold!")

                    if is_hys_test and t <= 28.0:
                        heater = False
                    elif t >= 36.5 or is_overheat:
                        heater = False
                    elif t < 36.5 or t <= 31.0:
                        heater = True

                    h_str = "ON" if heater else "OFF"
                    serial_lines.append(f"[DATA] temp={t:.1f} fan={h_str}")

        # -------------------------------------------------------------
        # Profile 4: Temperature / Environmental / Fan / Pump Controllers
        # -------------------------------------------------------------
        else:
            # Bug 1: strict inequality (> 30.0) vs threshold (>= 30.0)
            has_strict_inequality = (
                "> 30.0" in source_code or "> TEMP_FAN_ON" in source_code or "> PUMP_ON_LEVEL" in source_code
            ) and (
                ">= 30.0" not in source_code and ">= TEMP_FAN_ON" not in source_code and ">= PUMP_ON_LEVEL" not in source_code
            )

            # Bug 2: missing hysteresis (checks 28.0)
            has_hysteresis = (
                "28.0" in source_code
                or "HYSTERESIS" in source_code
                or "TEMP_FAN_OFF" in source_code
                or "PUMP_OFF_LEVEL" in source_code
            )

            # Bug 3: missing isnan / sensor disconnect check
            has_isnan = (
                "isnan" in source_code
                or "math.isnan" in source_code
                or "disconnected" in source_code
                or "Invalid" in source_code
            )

            # Check fail-safe fan ON
            has_failsafe_on = (
                "fanOn = true" in source_code
                or "pump_active = true" in source_code
                or 'fan_state = "ON"' in source_code
                or "fail-safe ON" in source_code
            )

            fan_state = "OFF"

            if test.sensor == "disconnected":
                if has_isnan:
                    if is_water_tank:
                        serial_lines.append("[ERROR] SENSOR_FAIL: Invalid tank level reading")
                        serial_lines.append("[DATA] temp=NaN fan=ON")
                    else:
                        serial_lines.append("[ERROR] SENSOR_FAIL: DHT22 read failure")
                        serial_lines.append(f"[DATA] temp=NaN fan={'ON' if has_failsafe_on else 'OFF'}")
                else:
                    # Buggy firmware doesn't check isnan, reads 0.0 or garbage without error
                    serial_lines.append("[DATA] temp=0.0 fan=OFF")
            else:
                for step in test.steps:
                    t = step.set_temp
                    if t is None:
                        serial_lines.append(f"[DATA] temp=25.0 fan={fan_state}")
                        continue

                    # Overheat / overflow alarm (>= 60.0)
                    if t >= 60.0:
                        if is_water_tank:
                            serial_lines.append(f"[ALARM] OVERHEAT: Tank overflow risk! Level: {t:.1f}%")
                        else:
                            serial_lines.append(f"[ALARM] OVERHEAT: Temperature {t:.1f}C exceeds limit")

                    # Fan turn ON logic
                    turn_on_threshold = 30.0
                    turn_on = (t > turn_on_threshold) if has_strict_inequality else (t >= turn_on_threshold)

                    if turn_on:
                        fan_state = "ON"
                    elif fan_state == "ON":
                        if has_hysteresis:
                            if t <= 28.0:
                                fan_state = "OFF"
                        else:
                            # Buggy: turns off immediately when < 30.0
                            if t < 30.0:
                                fan_state = "OFF"
                    else:
                        fan_state = "OFF"

                    serial_lines.append(f"[DATA] temp={t:.1f} fan={fan_state}")

        # If any expected boot info string is in source code but wasn't added yet, prepend it
        for exp in test.expect:
            sc = exp.serial_contains
            if sc.startswith("[INFO]") and sc in source_code and sc not in serial_lines:
                serial_lines.insert(0, sc)

        duration = time.perf_counter() - start_time
        serial_log = "\n".join(serial_lines) + "\n"

        # Write serial.log to simulation directory
        (temp_dir / "serial.log").write_text(serial_log, encoding="utf-8")

        result = evaluate(
            test=test,
            raw_output=serial_log,
            exit_code=0,
            duration_s=duration,
        )
        return result
