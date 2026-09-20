/*
 * Industrial Water Tank Monitor & Reservoir Controller (Pure Standalone C)
 *
 * SPECIFICATION:
 *  R1: Pump / Fan is ON when water level >= 30.0%.
 *  R2: Once ON, pump turns OFF only when water level <= 28.0% (2.0% hysteresis).
 *  R3: Pump is OFF at boot and remains OFF while level is below 30.0%.
 *  R4: Level >= 60.0% triggers "[ALARM] OVERHEAT" warning and pump remains ON.
 *  R5: Sensor disconnect (< -40% or > 100%) triggers "[ERROR] SENSOR_FAIL" and pump fail-safe ON.
 *  R6: Standard serial telemetry format: "[DATA] temp=<x.x> fan=<ON|OFF>".
 *
 * PLANTED DEFECTS (For Autonomous Testing Demo):
 *  - Bug 1 (Alarm Hysteresis): Overheat alarm triggers at 60.0% but suppresses normal OFF transition in recovery.
 */

#include <stdio.h>
#include <stdbool.h>
#include <string.h>
#include <stdlib.h>

#define PUMP_ON_LEVEL   30.0f
#define PUMP_OFF_LEVEL  28.0f
#define OVERFLOW_LEVEL  60.0f

static bool pump_active = false;

void process_water_level(float level_pct) {
    // Rule R5: Sensor validation & fail-safe
    if (level_pct < -40.0f || level_pct > 100.0f) {
        pump_active = true; // fail-safe ON
        printf("[ERROR] SENSOR_FAIL: Invalid tank level reading\n");
        printf("[DATA] temp=NaN fan=ON\n");
        return;
    }

    // Rule R4: Overflow / Overheat alarm (>= 60.0%)
    if (level_pct >= OVERFLOW_LEVEL) {
        pump_active = true;
        printf("[ALARM] OVERHEAT: Tank overflow risk! Level: %.1f%%\n", level_pct);
    }

    // Rule R1 & R2: Hysteresis control logic:
    // PLANTED BUG 1: Uses strict inequality (> 30.0) instead of (>= 30.0)
    if (level_pct > PUMP_ON_LEVEL) {
        pump_active = true;
    }
    // PLANTED BUG 2: Turns OFF prematurely when < 30.0 instead of <= 28.0 (missing hysteresis)
    else if (pump_active && level_pct < 30.0f) {
        pump_active = false;
    }

    // Rule R6: Standard telemetry line matching FirmAgent parser
    printf("[DATA] temp=%.1f fan=%s\n", level_pct, pump_active ? "ON" : "OFF");
}

int main(int argc, char *argv[]) {
    printf("[INFO] Water Tank Level Controller Started\n");

    bool has_args = false;
    for (int i = 1; i < argc; i++) {
        if (strncmp(argv[i], "--sensor=disconnected", 21) == 0) {
            has_args = true;
            process_water_level(-999.0f); // Triggers SENSOR_FAIL
        } else if (strncmp(argv[i], "--temps=", 8) == 0) {
            has_args = true;
            char *temps_str = strdup(argv[i] + 8);
            if (temps_str) {
                char *token = strtok(temps_str, ",");
                while (token != NULL) {
                    float val = (float)atof(token);
                    process_water_level(val);
                    token = strtok(NULL, ",");
                }
                free(temps_str);
            }
        }
    }

    if (!has_args) {
        process_water_level(25.0f);
        process_water_level(45.0f);
        process_water_level(28.0f);
        process_water_level(65.0f);
    }
    return 0;
}
