# 01 — Product Requirements Document (PRD)

## 1. Product name and one-sentence idea
**FirmAgent** — an AI agent that reads embedded firmware, decides what is worth testing, runs those tests in a virtual hardware simulator (Wokwi), spots wrong behaviour, and writes a report explaining what failed and why.

> Give it a firmware file. Get back a tested-and-explained report, without writing a single test case.

## 2. Target users
- Embedded engineers and students who test firmware by hand today.
- Hackathon judges (Black Box Hackathon 2026, Problem Statement 3) who will watch a 5-minute live demo.

## 3. Problem and current workaround
Testing firmware means: write test cases by hand, wire up hardware, run, read the output, and debug failures. Edge cases (sensor unplugged, value exactly on a threshold, communication lost) are easy to forget. Today, engineers rely on manual test lists and physical bench setups.

## 4. Goal and success measure
| # | Goal | Measurable signal |
|---|------|-------------------|
| G1 | Fully automatic testing loop | One click: firmware in → report out, zero manual test writing |
| G2 | Finds real bugs | Detects all 3 planted bugs in the demo firmware; correct behaviours are reported as PASS (no false alarms) |
| G3 | Good coverage | At least 12 generated tests across at least 6 categories |
| G4 | Truly autonomous | After a failure, the agent creates follow-up tests by itself (at least 1 loop) |
| G5 | Clear explanation | Every failure shows expected vs observed, likely cause, and the suspect source lines |

**The judges' warning to respect:** this must be a working testing loop, not a chatbot that explains code.

## 5. Core features
| ID | Feature | User benefit | Priority |
|----|---------|--------------|----------|
| F1 | Firmware input (upload `.cpp/.ino` or pick the bundled demo) | Start in seconds | P0 |
| F2 | Firmware analysis (LLM → structured JSON): inputs, outputs, thresholds, states, error handling, spec rules | Shows the agent understood the code | P0 |
| F3 | Test generation (LLM): normal, boundary, abnormal, sensor-disconnect, recovery, sequences, combinations | Coverage without manual effort | P0 |
| F4 | Scenario compiler (code): test JSON → Wokwi YAML scenario + diagram variant | Tests are executable | P0 |
| F5 | Simulator runner (code): runs each test in Wokwi CLI, captures serial log and exit code | Real execution on virtual hardware | P0 |
| F6 | Evaluator (code): pass/fail from expected vs observed | Trustworthy verdicts (not LLM guesses) | P0 |
| F7 | Report (Markdown + HTML): summary, coverage, failures, causes, source lines | Deliverable for judges | P0 |
| F8 | Autonomous follow-up loop: failures → extra probing tests → re-run (max 2 rounds) | Proves it is an agent | P1 |
| F9 | Root-cause analysis with source line numbers and suggested fix | High "Analysis" score | P1 |
| F10 | Live progress UI (Streamlit) with per-test status | Good demo and UX | P1 |
| F11 | Replay mode: load a saved "golden" run | Demo survives bad internet/API limits | P1 |
| F12 | Second demo firmware (e.g. door alarm) | Shows generality | P2 |
| F13 | Host-simulator fallback (C logic compiled on PC) | Plan B if Wokwi fails | P2 |

## 6. Out of scope for version one
- Real hardware, physical boards, wiring
- Automatically fixing the firmware (we only *suggest* a fix)
- Support for many MCU families (one board: Arduino Uno + DHT22 + LED as "fan")
- Login, users, cloud hosting, databases
- A chat/Q&A interface about the code

## 7. User stories
- As an engineer, I want to upload firmware and get tests generated automatically, so I do not write test cases by hand.
- As an engineer, I want boundary and sensor-failure cases tested, so I find bugs I would have missed.
- As an engineer, I want each failure explained with expected vs observed and the suspect lines, so I can fix it fast.
- As a judge, I want to watch the whole loop run live, so I can see it is autonomous.
- As a presenter, I want to replay a saved run, so the demo works even if the internet fails.

## 8. Acceptance criteria
- **Given** the demo firmware is selected, **when** I click *Run autonomous test*, **then** analysis, tests, live execution and a final report appear without any other input.
- **Given** the fan spec says ON at ≥ 30.0 °C, **when** the temperature is set to exactly 30.0, **then** the agent reports a FAIL for the boundary test (planted bug B1).
- **Given** the spec requires hysteresis (stay ON until ≤ 28.0 °C), **when** the temperature goes 31 → 29, **then** the agent reports a FAIL (bug B2).
- **Given** the sensor is disconnected, **when** the firmware prints no error, **then** the agent reports a FAIL for the missing `[ERROR] SENSOR_FAIL` (bug B3).
- **Given** correct behaviour (e.g. 25 °C → fan OFF, 45 °C → fan ON), **then** those tests are PASS.
- **Given** at least one failure, **when** the loop continues, **then** the agent generates at least 2 extra follow-up tests around the failure and runs them.
- **Given** no internet, **when** I click *Load golden run*, **then** the full previous report is displayed.

## 9. How this maps to the judges' evaluation criteria
| Criterion | Our answer |
|-----------|------------|
| Firmware Understanding | Analysis JSON (F2) shown in UI |
| Test Generation | 12+ tests in 6+ categories (F3) |
| Edge Cases | Boundary, disconnect, recovery, rapid change, invalid values |
| Simulation | Wokwi CLI runs every test (F5) |
| Failure Detection | Code-based evaluator (F6) |
| Analysis | Root cause + lines + suggested fix (F9) |
| Automation | One click, follow-up loop (F8) |
| User Experience | Streamlit tabs with live status (F10) |

## 10. Open questions and default decisions
| Question | Default decision |
|----------|------------------|
| Which simulator? | Wokwi CLI. Plan B: host-compiled C logic |
| Which board? | Arduino Uno (AVR) + DHT22 + LED on pin 13 as fan |
| Which LLM? | Gemini API (model name kept in `.env`) |
| Where do expected values come from? | The spec comment block at the top of the firmware is the source of truth |
| Parallel test runs? | No. Sequential first, parallel only if time remains |

---

## Annex A — Demo firmware specification (the "oracle")
This same text is the comment block at the top of `firmware/fan_controller/src/main.cpp`.

- **R1** Fan is ON when temperature >= 30.0 °C.
- **R2** Once ON, the fan stays ON until temperature <= 28.0 °C (2 °C hysteresis).
- **R3** Fan is OFF at boot and stays OFF while temperature is below 30.0 °C.
- **R4** Temperature >= 60.0 °C prints `[ALARM] OVERHEAT` and the fan is ON.
- **R5** If the sensor read fails, print `[ERROR] SENSOR_FAIL` and turn the fan ON (fail-safe).
- **R6** When the sensor recovers, print `[INFO] SENSOR_OK` and resume normal control.
- Serial output every 2 s: `[DATA] temp=<x.x> fan=<ON|OFF>`. Boot line: `[INFO] BOOT`.

## Annex B — Planted bugs (PRIVATE: never give this annex to the agent's LLM)
| Bug | Violates | What the code does |
|-----|----------|--------------------|
| B1 | R1 | Uses `t > 30.0` instead of `>= 30.0`, so exactly 30.0 does not turn the fan ON |
| B2 | R2 | Turns the fan OFF as soon as `t < 30.0` (no hysteresis) |
| B3 | R5 / R6 | No `isnan()` check: a failed sensor prints `temp=nan`, no error, and the fan keeps its old state |

These bugs exist so the agent has real failures to find. The analyzer and generator must receive **only** the firmware source, never this annex.
