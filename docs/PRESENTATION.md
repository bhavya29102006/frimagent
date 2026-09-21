# ⚡ FirmAgent: Autonomous Firmware Testing & Self-Healing Platform
### Pitch Deck & Technical Presentation (8 Slides)

---

## Slide 1: Title & Executive Summary

### Header
**FirmAgent: Autonomous End-to-End Embedded Firmware Testing, Simulation & Self-Healing Agent**

### Subtitle
*Bridging the Gap Between Code and Physical Hardware with AI-Driven Simulation and Safety-Gated Autonomous Patching*

### Key Highlights
- **Target Domains**: Arduino C++, Pure Embedded C, MicroPython IoT, Gazebo 3D Robotics.
- **Core Technology**: Google Gemini 2.5 Flash, PlatformIO Core, Wokwi CLI, Native GCC, Gazebo ROS2, SQLite3.
- **One-Line Pitch**: FirmAgent eliminates the physical hardware testing bottleneck by automatically deriving formal specification tests from code, executing them across 5 virtual simulation backends, localizing root causes, and safely repairing firmware bugs in an isolated sandbox with zero human intervention.

> **Speaker Notes:**  
> Welcome. Today we present FirmAgent, an autonomous agent built to solve one of the greatest engineering bottlenecks in hardware engineering: embedded firmware verification. In the next 7 slides, we will demonstrate how FirmAgent analyzes, tests, simulates, and auto-repairs firmware across multiple architectures with 100% test reliability.

---

## Slide 2: The Problem: The Embedded Testing Crisis

### The Hardware Bottleneck
1. **Physical Hardware Scarcity**:
   - Firmware engineers spend up to 40% of their time flashing boards, swapping wiring, and waiting for physical test rigs.
   - Hardware in the loop (HIL) setups cost tens of thousands of dollars and cannot be replicated on every developer's laptop.
2. **Subtle Edge-Case Deficiencies**:
   - Real hardware bugs occur at boundary conditions: sensor disconnects (`NaN`), hysteresis oscillations, and timing race conditions.
   - Traditional unit testing frameworks (like Unity or GoogleTest) mock out the hardware, missing real peripheral interactions.
3. **Cloud Quotas & Pipeline Chokepoints**:
   - Cloud hardware simulators (e.g. Wokwi CI) impose strict monthly minute quotas that exhaust rapidly in continuous CI/CD pipelines.
4. **Tedious Manual Triage**:
   - When a test fails on hardware, debugging requires manually reading raw megabyte-sized serial UART logs without line-number stack traces.

> **Speaker Notes:**  
> In software, automated testing is instant. In embedded systems, it is painfully slow. Developers must wait for physical boards or endure broken CI pipelines when cloud quotas run out. When bugs occur, tracking them down from raw serial logs takes hours. FirmAgent addresses all four of these pain points.

---

## Slide 3: The Solution: The FirmAgent Autonomous Engine

### What FirmAgent Delivers
1. **Autonomous Spec Extraction**:
   - Automatically parses C/C++/Python firmware and extracts formal functional requirements (e.g. temperature thresholds, sensor fail-safes, access PIN rules).
2. **Deterministic Multi-Engine Simulation**:
   - Executes tests without requiring physical hardware across 5 pluggable backends: Universal Virtual Hardware, Wokwi CLI, Native GCC/Clang, MicroPython, and Gazebo 3D.
3. **Persistent SQLite Caching (`firmagent.db`)**:
   - Caches analysis and test suites keyed by SHA-256 code hashes. Re-testing existing firmware costs **$0** and runs with **zero network latency**.
4. **Intelligent Cloud Quota Auto-Fallback**:
   - Automatically detects cloud quota exhaustion or network dropouts and seamlessly fails over to local virtual hardware simulation.
5. **Autonomous Root Cause Analysis & Sandbox Self-Healing**:
   - Pinpoints bugs down to exact source lines and proposes minimal unified diff patches verified in an isolated clone before touching production code.

> **Speaker Notes:**  
> FirmAgent transforms embedded QA from a slow, manual chore into an autonomous closed-loop system. It reads code, writes tests, runs hardware simulations, finds the bug, and fixes the bug—all with rigorous safety guarantees.

---

## Slide 4: System Architecture & Technical Flowchart

### The 5-Stage Autonomous Loop

```text
[ 1. Ingest & Syntax Check ] ──> Clean? (If syntax broken -> 1-Click AI Repair)
             │
[ 2. SQLite Cache Layer ]   ──> Hash Hit? -> Instant DB Load ($0 / 0s)
             │                                   │ (Miss)
             │                          Gemini 2.5 Synthesis -> Save to DB
             ▼
[ 3. Simulation Dispatcher] ──> Auto-routes to Wokwi, Native GCC, Virtual Mock,
             │                  Python Sim, or Gazebo 3D (with Quota Failover)
             ▼
[ 4. Telemetry Evaluation ] ──> Evaluates serial streams, timestamps & assert rules
             │
[ 5. Sandbox Self-Healing ] ──> Root Cause Localization -> 7 Safety Gates ->
                                Isolated Sandbox Compile & Retest -> Zero-Regression Gate
```

### Core Architecture Pillars
- **Non-Blocking Orchestrator**: Python threading with cooperative `stop_event` permits stopping or replaying runs at any instant.
- **Modular Simulators**: Base class interface (`BaseSimulator`) enabling drop-in support for any future simulator or hardware probe.
- **Isolated Sandbox Workspace**: Every fix attempt is generated in `runs/<run_id>/fix/<attempt_id>/project/` with immutable `.orig` backups.

> **Speaker Notes:**  
> Here is our complete 5-stage architectural pipeline. Notice the two key architectural highlights: First, the persistent SQLite caching layer that ensures zero unnecessary LLM costs; second, the isolated sandbox environment that guarantees broken patches can never compromise the master firmware repository.

---

## Slide 5: Multi-Firmware & Multi-Engine Simulation Matrix

### Comprehensive Domain Support

| Firmware Preset | Target Language | Hardware Architecture | Simulation Backend | Test Cases | Handled Bugs |
| :--- | :---: | :--- | :---: | :---: | :--- |
| **`fan_controller`** | Arduino C++ | Uno + DHT22 + Relay | Virtual Mock / Wokwi | 16 | Boundary `>= 30°C`, Hysteresis, `isnan()` Fail-safe |
| **`incubator_controller`** | Arduino C++ | Uno + Dual Temp + Heater | Virtual Mock / Wokwi | 16 | Overheat limit boundary `>= 40°C` & `>= 60°C` |
| **`water_tank_monitor`** | Pure Embedded C | MCU + Ultrasonic + Valve | Native C (GCC / Clang) | 16 | Solenoid cutoff boundary (`< 20` vs `<= 20`) |
| **`iot_weather_node`** | MicroPython | ESP32 / RP2040 Telemetry | Python AST Runner | 16 | Freeze protection threshold & NaN sensor drop |
| **`smart_door_lock`** | Arduino C++ | Keypad + Buzzer + EEPROM | Virtual Mock | 14 | 3-attempt lockout security counter logic |
| **`ultrasonic_radar`** | Arduino C++ | HC-SR04 + SG90 Servo | Virtual Mock | 16 | Strict distance boundary (`< 20` vs `<= 20`) |
| **`robot_obstacle_avoidance`** | Python / ROS2 | Differential Drive + LiDAR | Gazebo 3D Simulation | 15 | LiDAR safety braking distance threshold |

### Highlights
- **100% Simulator Reliability**: Zero simulator crashes (`0 ERROR`) across all 7 firmware presets.
- **Zero-Dependency Mode**: The Universal Virtual Hardware engine runs on any Windows, Linux, or macOS machine without installing PlatformIO or Wokwi CLI.

> **Speaker Notes:**  
> Unlike generic testing tools that only test Arduino sketches, FirmAgent is truly multi-paradigm. We support Arduino C++, pure industrial C compiled with GCC, MicroPython for modern IoT nodes, and Gazebo 3D simulation with SDF physics for autonomous robotics.

---

## Slide 6: Technology Stack & Engineering Rigor

### Technology Layers
- **Orchestration & Data Models**:
  - Python 3.10+ with **Pydantic v2** strict typing and schema serialization.
  - Multi-threaded execution with thread-safe stop signaling.
- **Generative AI & Reasoning**:
  - **Google Gemini 2.5 Flash** with low-temperature structured JSON output.
  - Customized system prompts for embedded failure mode analysis.
- **Toolchains & Compilers**:
  - **PlatformIO Core (`pio`)**: Headless AVR GCC build system.
  - **Native GCC / MinGW / Clang**: Host compilation for pure embedded C.
  - **Python `py_compile` & AST**: Syntax validation for MicroPython scripts.
- **Database & Cache**:
  - **SQLite3 (`runs/firmagent.db`)**: Indexed by SHA-256 code digests.
- **User Interface**:
  - **Streamlit 1.42+**: Accessible dark-mode dashboard with monospace serial terminals, responsive metrics, and unified diff viewers.
- **Test Automation**:
  - **Pytest**: 144 unit and integration tests with 100% pass rate.

> **Speaker Notes:**  
> Our technology stack was chosen for maximum speed, reproducibility, and production stability. Pydantic ensures robust data validation, PlatformIO and GCC give us bare-metal compilation confidence, and SQLite gives us instant performance.

---

## Slide 7: Feasibility, Reliability & Safety

### Why FirmAgent is Production-Ready
1. **7-Stage Deterministic Safety Gate**:
   - `hunk_limit`: $\le 3$ hunks permitted per patch.
   - `line_limit`: $\le 25$ total modified lines (no runaway refactors).
   - `exact_match`: Every replaced line must match original source byte-for-byte.
   - `non_overlapping`: Disjoint hunk ranges.
   - `protected_ranges`: `#include`, `#define`, and hardware pin macros are cryptographically locked.
   - `spec_block_integrity`: Specification docstrings must remain byte-identical.
   - `compilation`: Clean compilation with zero compiler warnings or errors.
2. **Idempotent Sandbox Verification**:
   - Cloned sandbox workspace tests patches in complete isolation.
   - Idempotent `.orig` backups guarantee repeated testing never corrupts source code.
3. **Zero-Regression Rule**:
   - If even **one** previously passing test fails after applying a patch, the fix is **automatically rejected**.
4. **Cloud Quota & Offline Resilience**:
   - Built-in quota guard prevents pipeline failures when cloud tokens expire.
   - Golden Replay mode allows 100% offline demonstration.

> **Speaker Notes:**  
> In embedded systems, safety is paramount. An AI hallucination could burn out a motor or short a circuit. FirmAgent enforces 7 strict deterministic safety checks and a strict zero-regression gate. If a patch fixes 2 bugs but breaks 1 existing feature, it is instantly rejected.

---

## Slide 8: Real-World Impact, Metrics & Future Roadmap

### Demonstrated Benchmarks
- **Test Execution Speed**: ~0.4s per test on Universal Virtual Hardware (vs 20s on physical microcontrollers) — **50x speedup**.
- **Automated Patch Verification**: **100% Test Pass Rate** achieved across all 4 benchmark firmwares after applying verified patches.
- **Cost Reduction**: SQLite code caching reduces Gemini API token spend by **85%** during active development.
- **Pytest Verification**: **144 / 144 unit tests passing** continuously.

### Future Roadmap
- **Q2 2026**: CI/CD GitHub Actions / GitLab CI native runner integration.
- **Q3 2026**: Hardware-in-the-loop (HIL) bridge via JTAG/SWD debug probes (J-Link, ST-Link).
- **Q4 2026**: Formal model checking (CBMC / Frama-C) integration alongside LLM verification.

### Call to Action
FirmAgent proves that firmware testing can be as fast, safe, and autonomous as modern web and cloud software.

---
