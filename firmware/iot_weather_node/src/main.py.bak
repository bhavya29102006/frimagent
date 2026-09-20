"""
IoT Weather & Ambient Ventilation Node (Embedded Python / MicroPython)

SPECIFICATION:
  R1: Ventilation Fan turns ON when temperature >= 30.0 C.
  R2: Once ON, the fan turns OFF only when temperature <= 28.0 C (2.0 C hysteresis).
  R3: Fan is OFF at boot and remains OFF while temperature is below 30.0 C.
  R4: Temperature >= 60.0 C prints "[ALARM] OVERHEAT" and turns fan ON.
  R5: If sensor read fails or disconnected, print "[ERROR] SENSOR_FAIL" and turn fan ON (fail-safe).
  R6: Standard serial telemetry output: "[DATA] temp=<x.x> fan=<ON|OFF>".

PLANTED DEFECTS (For Autonomous Testing Demo):
  - Bug 1 (Boundary Defect): Uses `temp_val > TEMP_FAN_ON` (strict inequality) instead of `>= 30.0`.
  - Bug 2 (Missing Hysteresis): Drops fan to OFF immediately when `temp_val < 30.0`, ignoring the 28.0 C hysteresis threshold.
"""

import sys
import math

TEMP_FAN_ON = 30.0
TEMP_FAN_OFF = 28.0
TEMP_OVERHEAT = 60.0

fan_state = "OFF"


def evaluate_sample(temp_val: float) -> None:
    global fan_state

    # Rule R5: Sensor Disconnected Fail-Safe Check
    if temp_val is None or math.isnan(temp_val):
        fan_state = "ON"  # Fail-safe ON
        print("[ERROR] SENSOR_FAIL: Ambient sensor offline")
        print("[DATA] temp=NaN fan=ON")
        return

    # Rule R4: Overheat Safety Alarm (>= 60.0 C)
    if temp_val >= TEMP_OVERHEAT:
        print(f"[ALARM] OVERHEAT: Temperature {temp_val:.1f}C exceeded safety limit!")
        fan_state = "ON"
    # Rule R1 & R3: Ventilation logic
    # PLANTED BUG 1: Uses strictly greater (>) instead of greater-than-or-equal (>= 30.0)
    elif temp_val > TEMP_FAN_ON:
        fan_state = "ON"
    # Rule R2: Hysteresis logic
    # PLANTED BUG 2: Turns off immediately when < 30.0 instead of <= 28.0
    elif fan_state == "ON" and temp_val < 30.0:
        fan_state = "OFF"
    elif fan_state == "OFF":
        fan_state = "OFF"

    # Rule R6: Serial Telemetry Output
    print(f"[DATA] temp={temp_val:.1f} fan={fan_state}")


def main():
    sensor_mode = "normal"
    temp_sequence = [22.0, 30.0, 31.0, 29.0, 28.0, 65.0]

    for arg in sys.argv[1:]:
        if arg.startswith("--sensor="):
            sensor_mode = arg.split("=")[1]
        elif arg.startswith("--temps="):
            raw_temps = arg.split("=")[1].split(",")
            temp_sequence = [float(x) for x in raw_temps if x]

    if sensor_mode == "disconnected":
        evaluate_sample(float("nan"))
    else:
        for t in temp_sequence:
            evaluate_sample(t)


if __name__ == "__main__":
    main()
