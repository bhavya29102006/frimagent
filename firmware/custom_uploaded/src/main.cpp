#include <Arduino.h>

void setup() {
  Serial.begin(9600);
  pinMode(13, OUTPUT);
  Serial.println("[INFO] Custom Upload Slot Ready");
}

void loop() {
  digitalWrite(13, HIGH);
  delay(1000);
  digitalWrite(13, LOW);
  delay(1000);
  Serial.println("[DATA] status=RUNNING");
}
