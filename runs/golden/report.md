# FirmAgent Autonomous Test Report
**Run ID**: `20260920-185754` | **Firmware**: `fan_controller` | **Status**: `DONE`

- **Started**: 2026-09-20T13:27:54.863839+00:00
- **Finished**: 2026-09-20T13:30:39.707386+00:00

## Executive Summary

| Metric | Count | Rate |
| :--- | :--- | :--- |
| **Total Tests** | 14 | 100% |
| **Passed** | 11 | 78.6% |
| **Failed** | 3 | - |
| **Errors** | 0 | - |
| **Bugs / Findings** | 3 | - |

## Test Coverage Matrix

| Category | Total Tests | Passed | Failed | Errors | Pass Rate |
| :--- | :---: | :---: | :---: | :---: | :---: |
| `abnormal` | 2 | 2 | 0 | 0 | 100.0% |
| `boundary` | 3 | 2 | 1 | 0 | 66.7% |
| `combination` | 2 | 2 | 0 | 0 | 100.0% |
| `normal` | 2 | 2 | 0 | 0 | 100.0% |
| `recovery` | 1 | 1 | 0 | 0 | 100.0% |
| `sensor_failure` | 1 | 0 | 1 | 0 | 0.0% |
| `sequence` | 3 | 2 | 1 | 0 | 66.7% |

## Root-Cause Findings & Planted Bugs

### [F1] Strict Inequality on Temperature Threshold for Fan Activation
- **Severity**: `MEDIUM` | **Spec Rule**: `R1`
- **Failed Tests**: `T03`
- **Expected Behavior**: Fan turns ON when temperature is exactly 30.0 C
- **Observed Behavior**: Fan remains OFF when temperature is 30.0 C due to strict greater-than comparison
- **Likely Cause**: Line 44 uses `t > 30.0` instead of `t >= 30.0`, violating rule R1 which specifies fan is ON when temperature >= 30.0 C.
- **Suspect Line(s)**: 44
```cpp
    42 |     Serial.println("[ALARM] OVERHEAT");
    43 |     fanOn = true;
>>  44 |   } else if (t > 30.0) {
    45 |     fanOn = true;
    46 |   } else if (t < 30.0) {
```
- **Suggested Fix**:
```cpp
  } else if (t >= 30.0) {
    fanOn = true;
```

### [F2] Missing Sensor Failure Handling and Fail-Safe Operation
- **Severity**: `HIGH` | **Spec Rule**: `R5`
- **Failed Tests**: `T08`
- **Expected Behavior**: Print '[ERROR] SENSOR_FAIL' and turn the fan ON when sensor read fails (NaN)
- **Observed Behavior**: Prints temp=nan fan=OFF without any error message or fail-safe fan activation
- **Likely Cause**: The firmware lacks a check for `isnan(t)` to detect sensor read failures, completely missing the error logging and fail-safe logic required by R5.
- **Suspect Line(s)**: 39, 40, 41
```cpp
    37 | void loop() {
    38 |   delay(2000);
>>  39 |   float t = dht.readTemperature();
>>  40 | 
>>  41 |   if (t >= 60.0) {
    42 |     Serial.println("[ALARM] OVERHEAT");
    43 |     fanOn = true;
```
- **Suggested Fix**:
```cpp
  float t = dht.readTemperature();
  if (isnan(t)) {
    Serial.println("[ERROR] SENSOR_FAIL");
    fanOn = true;
  } else if (t >= 60.0) {
    Serial.println("[ALARM] OVERHEAT");
    fanOn = true;
  } else if (t >= 30.0) {
    fanOn = true;
  } else if (t <= 28.0) {
    fanOn = false;
  }
```

### [F3] Missing Hysteresis Logic for Fan Turn-Off
- **Severity**: `MEDIUM` | **Spec Rule**: `R2`
- **Failed Tests**: `T10`
- **Expected Behavior**: Fan remains ON when temperature drops to 29.0 C after being ON, until it drops to <= 28.0 C
- **Observed Behavior**: Fan turns OFF immediately when temperature drops to 29.0 C because branch `else if (t < 30.0)` turns it off
- **Likely Cause**: The control logic uses `t < 30.0` instead of incorporating the 2 C hysteresis rule (turning off only when temperature <= 28.0 C once ON), and lacks state tracking for hysteresis.
- **Suspect Line(s)**: 46, 47
```cpp
    44 |   } else if (t > 30.0) {
    45 |     fanOn = true;
>>  46 |   } else if (t < 30.0) {
>>  47 |     fanOn = false;
    48 |   }
    49 | 
```
- **Suggested Fix**:
```cpp
  } else if (fanOn && t <= 28.0) {
    fanOn = false;
  } else if (!fanOn && t < 30.0) {
    fanOn = false;
  }
```

## Test Execution Details

| ID | Test Name | Category | Status | Duration | Observed Serial Summary |
| :--- | :--- | :--- | :---: | :---: | :--- |
| `T01` | Normal Low Temperature | `normal` | **PASS** | 7.4s | `[INFO] BOOT; temp=25.0 fan=OFF` |
| `T02` | Normal High Temperature | `normal` | **PASS** | 6.9s | `[INFO] BOOT; temp=45.0 fan=ON` |
| `T03` | Boundary Temperature Exact Threshold | `boundary` | **FAIL** | 25.0s | `[INFO] BOOT; temp=30.0 fan=OFF (x9)` |
| `T04` | Boundary Temperature Just Below Threshold | `boundary` | **PASS** | 6.8s | `[INFO] BOOT; temp=29.9 fan=OFF` |
| `T05` | Boundary Temperature Just Above Threshold | `boundary` | **PASS** | 6.5s | `[INFO] BOOT; temp=30.1 fan=ON` |
| `T06` | Abnormal Minimum DHT22 Range | `abnormal` | **PASS** | 6.7s | `[INFO] BOOT; temp=-40.0 fan=OFF` |
| `T07` | Abnormal Maximum Valid DHT22 Range | `abnormal` | **PASS** | 6.7s | `[INFO] BOOT; [ALARM] OVERHEAT; temp=80.0 fan=ON` |
| `T08` | Sensor Failure Disconnected | `sensor_failure` | **FAIL** | 24.5s | `[INFO] BOOT; temp=nan fan=OFF (x9)` |
| `T09` | Thermal Recovery from Overheat | `recovery` | **PASS** | 9.3s | `[INFO] BOOT; [ALARM] OVERHEAT; temp=65.0 fan=ON` |
| `T10` | Hysteresis Sequence Step to 29.0 C | `sequence` | **FAIL** | 25.0s | `[INFO] BOOT; temp=31.0 fan=ON; temp=29.0 fan=OF...` |
| `T11` | Hysteresis Sequence Step to 28.0 C | `sequence` | **PASS** | 9.7s | `[INFO] BOOT; temp=31.0 fan=ON; temp=28.0 fan=OFF` |
| `T12` | Hysteresis Boundary Step to 27.9 C | `sequence` | **PASS** | 9.7s | `[INFO] BOOT; temp=31.0 fan=ON; temp=27.9 fan=OFF` |
| `T13` | Overheat Alarm Trigger | `combination` | **PASS** | 7.4s | `[INFO] BOOT; [ALARM] OVERHEAT; temp=60.0 fan=ON` |
| `T14` | Multi-Step Fluctuation Combination | `combination` | **PASS** | 13.0s | `[INFO] BOOT; temp=26.0 fan=OFF; temp=32.0 fan=ON` |

## Specification Oracle Reference

- **R1**: Fan is ON when temperature >= 30.0 C. *(lines: [44, 45])*
- **R2**: Once ON, the fan turns OFF only when temperature <= 28.0 C (2 C hysteresis).
- **R3**: Fan is OFF at boot and stays OFF while temperature is below 30.0 C. *(lines: [27, 32, 46, 47])*
- **R4**: Temperature >= 60.0 C prints "[ALARM] OVERHEAT" and the fan is ON. *(lines: [41, 42, 43])*
- **R5**: If the sensor read fails, print "[ERROR] SENSOR_FAIL" and turn the fan ON (fail-safe).
- **R6**: When the sensor recovers, print "[INFO] SENSOR_OK" and resume normal control.
