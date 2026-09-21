/*
 * FAN CONTROLLER FIRMWARE
 *
 * SPECIFICATION
 *  R1: Fan is ON when temperature >= 30.0 C.
 *  R2: Once ON, the fan turns OFF only when temperature <= 28.0 C (2 C hysteresis).
 *  R3: Fan is OFF at boot and stays OFF while temperature is below 30.0 C.
 *  R4: Temperature >= 60.0 C prints "[ALARM] OVERHEAT" and the fan is ON.
 *  R5: If the sensor read fails, print "[ERROR] SENSOR_FAIL" and turn the fan ON (fail-safe).
 *  R6: When the sensor recovers, print "[INFO] SENSOR_OK" and resume normal control.
 *
 * SERIAL OUTPUT (9600 baud)
 *  Boot:        [INFO] BOOT
 *  Every 2 s:   [DATA] temp=<x.x> fan=<ON|OFF>
 *
 * HARDWARE
 *  DHT22 data on pin 2, fan (LED) on pin 13.
 */
#include <Arduino.h>
#include <DHT.h>

#define DHTPIN 2
#define DHTTYPE DHT22
#define FAN_PIN 13

DHT dht(DHTPIN, DHTTYPE);
bool fanOn = false;

void setup() {
  Serial.begin(9600);
  pinMode(FAN_PIN, OUTPUT);
  digitalWrite(FAN_PIN, LOW);
  dht.begin();
  Serial.println("[INFO] BOOT");
}

void loop() {
  delay(2000);
  float t = dht.readTemperature();

  if (t >= 60.0) {
    Serial.println("[ALARM] OVERHEAT");
    fanOn = true;
  } else if (t > 30.0) {
    fanOn = true;
  } else if (t < 30.0) {
    fanOn = false;
  }

  digitalWrite(FAN_PIN, fanOn ? HIGH : LOW);
  Serial.print("[DATA] temp=");
  Serial.print(t, 1);
  Serial.print(" fan=");
  Serial.println(fanOn ? "ON" : "OFF");
}