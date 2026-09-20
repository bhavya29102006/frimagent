#include <Arduino.h>
#include <DHT.h>

#define DHTPIN 2
#define DHTTYPE DHT22
#define ALARM_PIN 13

DHT dht(DHTPIN, DHTTYPE)  // SYNTAX ERROR: Missing semicolon

bool systemActive = true  // SYNTAX ERROR: Missing semicolon

void setup() {
  Serial.begin(9600);
  pinMode(ALARM_PIN, OUTPUT)  // SYNTAX ERROR: Missing semicolon
  dht.begin();
  Serial.println("[DEMO] Broken Firmware Loaded");
}

void loop() {
  float temp = dht.readTemperature();

  if (isnan(temp)) {
    Serial.println("[ERROR] DHT22 Read Failure");
    return;
  }

  if (temp > 35.0) {
    digitalWrite(ALARM_PIN, HIGH);
    Serial.println("[ALARM] High temperature detected!");
  } else {
    digitalWrite(ALARM_PIN, LOW);
  }

  Serial.print("[DATA] temp=");
  Serial.print(temp, 1);
  Serial.println(" status=OK");
  delay(1000);
}
