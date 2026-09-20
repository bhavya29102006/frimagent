"""IoT Weather & Ambient Ventilation Node (Embedded Python).

Monitors ambient temperature, commands exhaust ventilation, and asserts freeze protection.
"""

import sys
import math

TEMP_FAN_ON = 28.0
TEMP_FAN_OFF = 25.0
TEMP_FREEZE_LIMIT = 4.0

fan_state = "OFF"


def evaluate_sample(temp_val: float) -> None:
    global fan_state

    # Check invalid / NaN
    if temp_val is None or math.isnan(temp_val):
        fan_state = "OFF"
        print("[ERROR] SENSOR_FAIL: Ambient sensor offline")
        print("[DATA] temp=NaN fan=OFF")
        return

    # Freeze warning (< 4.0 C)
    if temp_val <= TEMP_FREEZE_LIMIT:
        print(f"[ALARM] OVERHEAT: Freeze condition detected: {temp_val:.1f}C")
        fan_state = "OFF"

    # Ventilation logic with hysteresis:
    if temp_val >= TEMP_FAN_ON:
        fan_state = "ON"
    elif fan_state == "ON" and temp_val <= TEMP_FAN_OFF:
        fan_state = "OFF"

    # Serial telemetry line
    print(f"[DATA] temp={temp_val:.1f} fan={fan_state}")


def main():
    sensor_mode = "normal"
    temp_sequence = [22.0, 29.5, 26.0, 24.0, 3.5]

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
