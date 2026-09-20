"""
Autonomous Robot Obstacle Avoidance Controller (Gazebo 3D / ROS2 Node)

SPECIFICATION:
  R1: When proximity sensor detects obstacle <= 25.0 cm, set state to BRAKE, activate buzzer (ON) and rotate.
  R2: When distance > 25.0 cm, set drive state to FORWARD and buzzer to OFF.
  R3: Normal forward cruise speed distance is >= 50.0 cm.
  R4: Proximity <= 10.0 cm prints "[ALARM] CRITICAL_COLLISION" and executes emergency stop.
  R5: If sensor fails or disconnected (NaN), print "[ERROR] SENSOR_FAIL" and halt robot (fail-safe).
  R6: Standard serial/telemetry output: "[DATA] dist=<x.x> state=<FORWARD|BRAKE|STOP> buzzer=<ON|OFF>".

PLANTED DEFECTS (For Autonomous Testing Demo):
  - Bug 1 (Boundary Defect): Uses `dist_val < STOP_DISTANCE` (strict inequality) instead of `<= 25.0`.
  - Bug 2 (Missing Hysteresis / Clear Buffer): Resets brake to FORWARD immediately when `dist_val > STOP_DISTANCE`, omitting the 30.0 cm safety clearance buffer.
"""

import sys
import math

STOP_DISTANCE = 25.0
CRITICAL_DISTANCE = 10.0
CLEAR_DISTANCE = 30.0

drive_state = "FORWARD"
buzzer_state = "OFF"


def evaluate_distance(dist_val: float) -> None:
    global drive_state, buzzer_state

    # Rule R5: Sensor Disconnected / NaN Fail-Safe Check
    if dist_val is None or math.isnan(dist_val) or dist_val < 0.0:
        drive_state = "STOP"
        buzzer_state = "OFF"
        print("[ERROR] SENSOR_FAIL: Gazebo LiDAR / Ray sensor offline")
        print("[DATA] dist=NaN state=STOP buzzer=OFF")
        return

    # Rule R4: Critical Proximity Emergency Alarm (<= 10.0 cm)
    if dist_val <= CRITICAL_DISTANCE:
        drive_state = "STOP"
        buzzer_state = "ON"
        print(f"[ALARM] CRITICAL_COLLISION: Obstacle at {dist_val:.1f}cm! Emergency brake engaged.")
        print(f"[DATA] dist={dist_val:.1f} state=STOP buzzer=ON")
        return

    # Rule R1: Obstacle detection and avoidance brake
    # PLANTED BUG 1: Uses strictly less-than (<) instead of less-than-or-equal (<= 25.0)
    if dist_val < STOP_DISTANCE:
        drive_state = "BRAKE"
        buzzer_state = "ON"
        print(f"[ALARM] PROXIMITY_ALERT: Obstacle detected at {dist_val:.1f} cm!")
    # Rule R2: Clear path forward
    # PLANTED BUG 2: Resets immediately when > 25.0 instead of >= 30.0 clearance
    elif dist_val > STOP_DISTANCE:
        drive_state = "FORWARD"
        buzzer_state = "OFF"

    # Rule R6: Serial Telemetry Output
    print(f"[DATA] dist={dist_val:.1f} state={drive_state} buzzer={buzzer_state}")


def main():
    sensor_mode = "normal"
    test_distances = [60.0, 25.0, 24.0, 8.0, 40.0]

    for arg in sys.argv[1:]:
        if arg.startswith("--sensor="):
            sensor_mode = arg.split("=")[1].strip()
        elif arg.startswith("--temps=") or arg.startswith("--distances=") or arg.startswith("--distance="):
            raw_vals = arg.split("=")[1].strip()
            if raw_vals:
                try:
                    test_distances = [float(x.strip()) for x in raw_vals.split(",") if x.strip()]
                except ValueError:
                    pass

    if sensor_mode == "disconnected":
        evaluate_distance(float("nan"))
        return

    for d in test_distances:
        evaluate_distance(d)


if __name__ == "__main__":
    main()
