/*
 * Industrial Water Tank Monitor & Pump Controller (Pure C)
 * Controls reservoir replenishment with level hysteresis and overflow alarm.
 */

#include <stdio.h>
#include <stdbool.h>
#include <string.h>

#define PUMP_ON_LEVEL   20.0f
#define PUMP_OFF_LEVEL  80.0f
#define OVERFLOW_LEVEL  95.0f

static bool pump_active = false;

void process_water_level(float level_pct) {
    // Sensor validation
    if (level_pct < 0.0f || level_pct > 100.0f) {
        pump_active = false;
        printf("[ERROR] SENSOR_FAIL: Invalid tank level reading\n");
        printf("[DATA] temp=NaN fan=OFF\n");
        return;
    }

    // Overflow alarm
    if (level_pct >= OVERFLOW_LEVEL) {
        pump_active = false;
        printf("[ALARM] OVERHEAT: Tank overflow risk! Level: %.1f%%\n", level_pct);
    }

    // Pump hysteresis logic:
    // Turn ON if level is low (< 20%)
    if (level_pct < PUMP_ON_LEVEL) {
        pump_active = true;
    }
    // Turn OFF if level is full (>= 80%)
    else if (level_pct >= PUMP_OFF_LEVEL) {
        pump_active = false;
    }

    // Telemetry output
    printf("[DATA] temp=%.1f fan=%s\n", level_pct, pump_active ? "ON" : "OFF");
}

int main(int argc, char *argv[]) {
    printf("[INFO] Water Tank Level Controller Started\n");
    process_water_level(15.0f);
    process_water_level(50.0f);
    process_water_level(85.0f);
    process_water_level(98.0f);
    return 0;
}
