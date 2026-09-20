/*
 * Industrial Water Tank Monitor & Pump Controller (Pure C)
 * Controls reservoir replenishment with level hysteresis and overflow alarm.
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
    // Sensor validation
    if (level_pct < -40.0f || level_pct > 100.0f) {
        pump_active = true; // fail-safe ON
        printf("[ERROR] SENSOR_FAIL: Invalid tank level reading\n");
        printf("[DATA] temp=NaN fan=ON\n");
        return;
    }

    // Overflow / Overheat alarm (>= 60.0)
    if (level_pct >= OVERFLOW_LEVEL) {
        pump_active = true;
        printf("[ALARM] OVERHEAT: Tank overflow risk! Level: %.1f%%\n", level_pct);
    }

    // Hysteresis control logic:
    // Turn ON when level/temp >= 30.0
    if (level_pct >= PUMP_ON_LEVEL) {
        pump_active = true;
    }
    // Turn OFF when level/temp <= 28.0
    else if (level_pct <= PUMP_OFF_LEVEL) {
        pump_active = false;
    }

    // Standard telemetry line matching FirmAgent parser
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
