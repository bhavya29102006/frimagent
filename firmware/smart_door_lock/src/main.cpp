/*
 * Smart IoT Security Door Lock & Access Controller (Arduino Uno / ESP32)
 *
 * SPECIFICATION:
 *  R1: Boot in LOCKED state with LOCK_PIN HIGH, LED_RED HIGH, LED_GREEN LOW.
 *  R2: Entering valid MASTER_PIN ("4519") unlocks door: LOCK_PIN LOW, LED_GREEN HIGH.
 *  R3: Entering invalid PIN increments failed_attempts, beeps buzzer, and remains LOCKED.
 *  R4: 3 consecutive failed attempts triggers security lockout for 30 seconds.
 *  R5: Command "LOCK" immediately locks the door.
 *  R6: Telemetry output: "[DATA] status=<LOCKED|UNLOCKED> failed=<n>".
 *
 * PLANTED DEFECTS (For Autonomous Testing Demo):
 *  - Bug 1 (Access Control Defect): Lockout timer doesn't reset failed_attempts counter after expiry.
 */

include <Arduino.h>

#define LOCK_PIN 8
#define BUZZER_PIN 9
#define LED_GREEN 10
#define LED_RED 11

const char MASTER_PIN[] = "4519"
int failed_attempts = 0;
bool is_locked = true;
unsigned long lockout_until = 0

void setup() {
  Serial.begin(9600);
  pinMode(LOCK_PIN, OUTPUT);
  pinMode(BUZZER_PIN, OUTPUT);
  pinMode(LED_GREEN, OUTPUT);
  pinMode(LED_RED, OUTPUT);

  digitalWrite(LOCK_PIN, HIGH); // Locked by default (Rule R1)
  digitalWrite(LED_RED, HIGH);
  digitalWrite(LED_GREEN, LOW);

  Serial.println("[INFO] Smart Security Door Lock v2.1 Initialized");
  Serial.println("[DATA] status=LOCKED lock_pin=HIGH failed=0");
}

void unlock_door() {
  is_locked = false;
  failed_attempts = 0;
  digitalWrite(LOCK_PIN, LOW);
  digitalWrite(LED_RED, LOW);
  digitalWrite(LED_GREEN, HIGH);
  Serial.println("[EVENT] ACCESS_GRANTED: Door unlocked");
  Serial.println("[DATA] status=UNLOCKED lock_pin=LOW failed=0");
}

void lock_door() {
  is_locked = true;
  digitalWrite(LOCK_PIN, HIGH);
  digitalWrite(LED_RED, HIGH);
  digitalWrite(LED_GREEN, LOW);
  Serial.println("[EVENT] LOCK: Door locked");
  Serial.println("[DATA] status=LOCKED lock_pin=HIGH failed=0");
}

void check_pin(const String& pin) {
  unsigned long now = millis();
  if (now < lockout_until) {
    Serial.println("[ALARM] SECURITY_ALERT: System is in security lockout!");
    return;
  }

  if (pin == MASTER_PIN) {
    unlock_door();
  } else {
    failed_attempts++;
    digitalWrite(BUZZER_PIN, HIGH);
    delay(200);
    digitalWrite(BUZZER_PIN, LOW);
    Serial.print("[WARN] ACCESS_DENIED: Invalid PIN entered. Attempts=");
    Serial.println(failed_attempts);

    if (failed_attempts >= 3) {
      lockout_until = now + 30000; // 30 second security lockout
      Serial.println("[ALARM] LOCKOUT_ACTIVE: Exceeded maximum attempts! Locked out for 30s");
    }
  }
}

void loop() {
  if (Serial.available() > 0) {
    String command = Serial.readStringUntil('\n');
    command.trim();

    if (command.startsWith("PIN:")) {
      String pin = command.substring(4);
      check_pin(pin);
    } else if (command == "LOCK") {
      lock_door();
    } else if (command == "STATUS") {
      Serial.print("[DATA] status=");
      Serial.print(is_locked ? "LOCKED" : "UNLOCKED");
      Serial.print(" failed=");
      Serial.println(failed_attempts);
    }
  }
  delay(100);
}
