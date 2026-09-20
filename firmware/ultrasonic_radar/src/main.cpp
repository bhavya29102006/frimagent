/*
 * Ultrasonic Proximity Radar Scanner (Arduino Uno + HC-SR04 + SG90 Servo)
 *
 * SPECIFICATION:
 *  R1: Proximity Alert: When detected object distance <= 20.0 cm, activate buzzer (HIGH)
 *      and print "[ALARM] PROXIMITY_ALERT: Object detected at <dist> cm!".
 *  R2: Normal Tracking: When distance is between 20.0 cm and 200.0 cm, buzzer is OFF
 *      and print standard serial telemetry: "[DATA] angle=<deg> dist=<x.x> buzzer=OFF".
 *  R3: Out of Range / Sensor Timeout: When distance < 0 (no echo received),
 *      print "[ERROR] SENSOR_FAIL: Ultrasonic echo timeout" and "[DATA] angle=<deg> dist=NaN buzzer=OFF".
 *  R4: Maximum Range Exceeded: When distance > 200.0 cm, print "[DATA] angle=<deg> dist=OUT_OF_RANGE buzzer=OFF".
 *  R5: Servo Sweep: Radar oscillates between 15 deg (SWEEP_MIN) and 165 deg (SWEEP_MAX).
 *  R6: Boot Telemetry: Print "[INFO] Ultrasonic Radar Scanner Initialized" on startup.
 *
 * PLANTED DEFECTS (For Autonomous Testing Demo):
 *  - Bug 1 (Boundary Defect): Uses strict `distance < ALERT_DISTANCE_CM` instead of `<= 20.0 cm`.
 */

#include <Arduino.h>
#include <Servo.h>

#define TRIG_PIN 9
#define ECHO_PIN 10
#define SERVO_PIN 11
#define BUZZER_PIN 8

#define MAX_DISTANCE_CM 200.0f
#define ALERT_DISTANCE_CM 20.0f
#define SWEEP_MIN 15
#define SWEEP_MAX 165
#define STEP_DELAY 30

Servo radarServo;
int currentAngle = SWEEP_MIN;
int sweepDirection = 1;

void setup() {
  Serial.begin(9600);
  pinMode(TRIG_PIN, OUTPUT);
  pinMode(ECHO_PIN, INPUT);
  pinMode(BUZZER_PIN, OUTPUT);
  digitalWrite(BUZZER_PIN, LOW);

  radarServo.attach(SERVO_PIN);
  radarServo.write(currentAngle);
  delay(500);

  // Rule R6: Boot Notification
  Serial.println("[INFO] Ultrasonic Radar Scanner Initialized");
}

float readDistanceCM() {
  digitalWrite(TRIG_PIN, LOW);
  delayMicroseconds(2);
  digitalWrite(TRIG_PIN, HIGH);
  delayMicroseconds(10);
  digitalWrite(TRIG_PIN, LOW);

  long duration = pulseIn(ECHO_PIN, HIGH, 25000);
  if (duration == 0) {
    return -1.0f; // Sensor timeout
  }
  return (float)(duration * 0.0343 / 2.0);
}

void loop() {
  radarServo.write(currentAngle);
  delay(STEP_DELAY);

  float distance = readDistanceCM();

  // Rule R3: Out of Range / Sensor Timeout
  if (distance < 0.0f) {
    digitalWrite(BUZZER_PIN, LOW);
    Serial.println("[ERROR] SENSOR_FAIL: Ultrasonic echo timeout");
    Serial.print("[DATA] angle=");
    Serial.print(currentAngle);
    Serial.println(" dist=NaN buzzer=OFF");
  }
  // Rule R4: Distance exceeds max range
  else if (distance > MAX_DISTANCE_CM) {
    digitalWrite(BUZZER_PIN, LOW);
    Serial.print("[DATA] angle=");
    Serial.print(currentAngle);
    Serial.println(" dist=OUT_OF_RANGE buzzer=OFF");
  }
  // Rule R1: Proximity alert (PLANTED BUG 1: strict < instead of <=)
  else if (distance < ALERT_DISTANCE_CM) {
    digitalWrite(BUZZER_PIN, HIGH);
    Serial.print("[ALARM] PROXIMITY_ALERT: Object detected at ");
    Serial.print(distance, 1);
    Serial.println(" cm!");

    Serial.print("[DATA] angle=");
    Serial.print(currentAngle);
    Serial.print(" dist=");
    Serial.print(distance, 1);
    Serial.println(" buzzer=ON");
  }
  // Rule R2: Normal distance tracking
  else {
    digitalWrite(BUZZER_PIN, LOW);
    Serial.print("[DATA] angle=");
    Serial.print(currentAngle);
    Serial.print(" dist=");
    Serial.print(distance, 1);
    Serial.println(" buzzer=OFF");
  }

  // Rule R5: Sweep angle update
  currentAngle += sweepDirection * 2;
  if (currentAngle >= SWEEP_MAX) {
    currentAngle = SWEEP_MAX;
    sweepDirection = -1;
  } else if (currentAngle <= SWEEP_MIN) {
    currentAngle = SWEEP_MIN;
    sweepDirection = 1;
  }
}