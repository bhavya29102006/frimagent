/*
 * Medical Incubator Temperature Controller (Arduino Uno + DHT22)
 *
 * SPECIFICATION:
 *  R1: Underheat alarm (< 32.0 C) prints "[ALARM] UNDERHEAT".
 *  R2: Heating element turns ON when temperature drops below 36.5 C.
 *  R3: Heating element turns OFF when temperature reaches or exceeds 37.5 C (1.0 C hysteresis).
 *  R4: Overheat safety alarm (> 40.0 C) prints "[ALARM] OVERHEAT" and cuts off heater.
 *  R5: If sensor fails (isnan), print "[ERROR] SENSOR_FAIL" and turn heater OFF (fail-safe).
 *  R6: Standard serial telemetry output: "[DATA] temp=<x.x> fan=<ON|OFF>".
 *
 * PLANTED DEFECTS (For Autonomous Testing Demo):
 *  - Bug 1 (Boundary Defect): Overheat check uses strict `temp > 40.0` instead of `>= 40.0`.
 *  - Bug 2 (Underheat Recovery): Underheat alarm doesn't clear state upon recovery.
 */

#include <Arduino.h>
#include <DHT.h>

#define DHTPIN 2
#define DHTTYPE DHT22
#define HEATER_PIN 13

DHT dht(DHTPIN, DHTTYPE);
bool heaterState = false;

void setup() {
  Serial.begin(9600);
  pinMode(HEATER_PIN, OUTPUT);
  digitalWrite(HEATER_PIN, LOW);
  dht.begin();
  delay(1000);
  Serial.println("[INFO] Incubator Controller Initialized");
}

void loop() {
  float temp = dht.readTemperature();

  // Rule R5: Sensor disconnected fail-safe
  if (isnan(temp)) {
    heaterState = false;
    digitalWrite(HEATER_PIN, LOW);
    Serial.println("[ERROR] SENSOR_FAIL: Incubator DHT22 offline");
    Serial.println("[DATA] temp=NaN fan=OFF");
    delay(2000);
    return;
  }

  // Rule R4: Overheat safety alarm (> 40.0 C) - PLANTED BUG: strict > instead of >=
  if (temp > 40.0) {
    Serial.println("[ALARM] OVERHEAT: Incubator temperature exceeded 40.0C!");
    heaterState = false;
    digitalWrite(HEATER_PIN, LOW);
  }
  // Rule R1: Underheat alarm (< 32.0 C)
  else if (temp < 32.0) {
    Serial.println("[ALARM] UNDERHEAT: Incubator critically cold!");
  }

  // Thermostat control logic with hysteresis (Target 37.0 C):
  // Rule R2: Turn ON when temp drops below 36.5 C
  if (temp < 36.5) {
    heaterState = true;
    digitalWrite(HEATER_PIN, HIGH);
  }
  // Rule R3: Turn OFF when temp reaches or exceeds 37.5 C
  else if (temp >= 37.5) {
    heaterState = false;
    digitalWrite(HEATER_PIN, LOW);
  }

  // Rule R6: Standard telemetry format
  Serial.print("[DATA] temp=");
  Serial.print(temp, 1);
  Serial.print(" fan=");
  Serial.println(heaterState ? "ON" : "OFF");

  delay(2000);
}
