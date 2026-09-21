# ⚡ FirmAgent

> **Autonomous End-to-End Embedded Firmware Testing, Self-Healing & Hardware Simulation Platform**  
> *Black Box AI Hackathon 2026 — Track PS3: Autonomous Agent for Embedded Systems*

[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg?logo=python&logoColor=white)](https://python.org)
[![Streamlit App](https://img.shields.io/badge/Streamlit-1.42%2B-FF4B4B.svg?logo=streamlit&logoColor=white)](https://streamlit.io)
[![Gemini 2.5 Flash](https://img.shields.io/badge/LLM-Gemini%202.5%20Flash-4285F4.svg?logo=google&logoColor=white)](https://ai.google.dev/)
[![PlatformIO Core](https://img.shields.io/badge/Build-PlatformIO%20Core-FF9900.svg?logo=platformio&logoColor=white)](https://platformio.org/)
[![Wokwi Simulator](https://img.shields.io/badge/Simulation-Wokwi%20CLI-00B4D8.svg)](https://wokwi.com/)
[![GCC / Clang](https://img.shields.io/badge/Native-GCC%20%2F%20Clang-5C6BC0.svg)](https://gcc.gnu.org/)
[![Tests](https://img.shields.io/badge/Tests-144%2F144%20PASS-22C55E.svg)](tests/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## 🎯 Executive Summary (One-Line Pitch)

> **FirmAgent is an autonomous end-to-end AI testing and self-healing agent that analyzes embedded firmware across Arduino C++, pure C, MicroPython, and Gazebo robotics, synthesizes deterministic specification-derived test suites, executes virtual hardware simulations, diagnoses root-cause bugs with Gemini, and safely auto-patches firmware in an isolated sandbox with zero human intervention.**

---

## 📑 Pitch Deck & Presentation

- 📄 **[Download Presentation (PDF)](docs/FirmAgent_Pitch_Deck.pdf)** — *Pixel-perfect 8-page 16:9 landscape presentation with comparative graphs & flowchart.*
- 🌐 **[Launch Interactive Slides (HTML)](docs/presentation.html)** — *Browser presentation with keyboard navigation (`➔`, `←`, `Space`), progress bar, and speaker notes (`N`).*
- 📝 **[Slide Deck Script & Notes (Markdown)](docs/PRESENTATION.md)** — *Full slide-by-slide transcript and speaking notes.*

---

## 🛑 The Problem: Why Hardware Testing is Broken

1. **Physical Hardware Scarcity**: Engineers spend up to 40% of their time flashing physical microcontrollers, swapping wiring, and waiting for shared Hardware-in-the-Loop (HIL) test benches.
2. **Silent Edge-Case Bugs**: Software unit tests mock out peripherals and fail to catch real-world issues: sensor disconnections (`NaN`), power brownouts, and 2°C hysteresis glitches.
3. **Cloud CI Minute Quotas**: Cloud simulators (e.g. Wokwi CI) enforce strict monthly quotas that burn out in hours, breaking automated team CI/CD pipelines with HTTP 429 errors.
4. **Painful UART Serial Triage**: Microcontrollers offer no stack traces or line numbers when tests fail; engineers must manually read through megabytes of raw serial UART logs.

---

## 💡 The FirmAgent Solution

```text
+---------------------+     +--------------------+     +-----------------------+
|  1. AUTO-TEST       |     |  2. MULTI-SIMULATE |     |  3. SELF-HEAL         |
|  Reads source code, |     |  Runs 5 simulators |     |  Finds root cause,    |
|  extracts specs, &  | --> |  at ~0.4s/test with| --> |  runs 7 safety gates, |
|  generates 12-22    |     |  zero-downtime     |     |  & sandbox verifies   |
|  boundary tests.    |     |  quota failover.   |     |  with 0 regressions.  |
+---------------------+     +--------------------+     +-----------------------+
```

1. **Autonomous Spec & Test Generation**: Uses Gemini 2.5 Flash to extract formal requirements and generate deterministic YAML/Python test scenarios (`T01..T16+`).
2. **Multi-Engine Simulation Matrix**: Pluggable backends: **Universal Virtual Hardware** (zero-dependency local simulator), **Wokwi CLI**, **Native GCC/Clang**, **MicroPython**, or **Gazebo 3D Robotics**.
3. **Persistent SQLite Caching (`firmagent.db`)**: Code SHA-256 caching guarantees that re-running tests costs **$0** and runs with **zero Gemini API calls**.
4. **Intelligent Cloud Quota Auto-Fallback**: Automatically detects Wokwi CI minute exhaustion and instantly routes tests to the local virtual hardware simulator with zero interruption.
5. **Deterministic Sandbox Self-Healing**: Synthesizes minimal diffs, enforces **7 safety constraints**, and verifies patches in an isolated sandbox clone with a strict **Zero-Regression Rule**.

---

## 🔄 Technical Architecture Flowchart

```mermaid
flowchart TD
    subgraph INGEST["1. Firmware Ingestion & Pre-Flight"]
        FW["Target Firmware Source<br/>(.cpp, .c, .py, .ino, .sdf)"] --> SYN["Syntax Diagnostics<br/>(GCC / Pio / PyCompile)"]
        SYN -->|Syntax Errors| AI_SYN["🛠️ 1-Click AI Syntax Auto-Repair"]
        AI_SYN --> SYN
        SYN -->|Clean Code| HASH["Compute SHA-256 Code Hash"]
    end

    subgraph CACHE_LAYER["2. Persistent SQLite Cache Layer"]
        HASH --> DB_CHECK{"Cache Hit in<br/>firmagent.db?"}
        DB_CHECK -->|Hit| DB_LOAD["⚡ Instant Retrieval<br/>(0 Gemini API Calls / $0)"]
        DB_CHECK -->|Miss| GEMINI_AN["🤖 Gemini 2.5 Flash<br/>Spec & Test Synthesis"]
        GEMINI_AN --> DB_SAVE["💾 Persist to firmagent.db"]
        DB_LOAD --> SUITE["Specification Rules & Test Suite<br/>(T01..T16+, Follow-ups F01..F04)"]
        DB_SAVE --> SUITE
    end

    subgraph SIM_LAYER["3. Multi-Engine Simulation Dispatcher"]
        SUITE --> ROUTER{"Engine Router &<br/>Language Classifier"}
        ROUTER -->|Arduino Uno / ESP32| WOKWI["Wokwi Cloud CLI<br/>(AVR / Sensor Emulation)"]
        ROUTER -->|Zero-Dep / Standalone| VMOCK["⚡ Universal Virtual Hardware<br/>(Embedded State Machine)"]
        ROUTER -->|Pure Embedded C| GCC_HOST["Native C Host Runner<br/>(GCC / Clang Subprocess)"]
        ROUTER -->|MicroPython| PY_SIM["Python Telemetry Runner<br/>(py_compile / AST)"]
        ROUTER -->|Differential Robot| GAZEBO["Gazebo 3D Simulation<br/>(LiDAR / SDF World)"]
        
        WOKWI -->|Quota Exhausted / Offline| VMOCK
    end

    subgraph EVAL_LAYER["4. Verification & Evaluation"]
        WOKWI --> EVAL["Telemetry & Serial Log Evaluator<br/>(Regex / Pass / Fail / Error)"]
        VMOCK --> EVAL
        GCC_HOST --> EVAL
        PY_SIM --> EVAL
        GAZEBO --> EVAL
        EVAL --> REPORT["📊 Interactive 5-Tab Dashboard<br/>(Pass/Fail Scores, Timeline, Metrics)"]
    end

    subgraph HEALING["5. Autonomous Bug Self-Healing"]
        EVAL -->|Failures Detected| RCA["🤖 Gemini Root Cause Analysis<br/>(Suspect Line Localization)"]
        RCA --> PATCH_GEN["Autonomous Patch Synthesis<br/>(Minimal Unified Diff Hunks)"]
        PATCH_GEN --> SAFETY["🛡️ 7-Stage Safety Validator<br/>(Hunks ≤ 3, Lines ≤ 25, Spec Locked)"]
        SAFETY -->|Checks Pass| SANDBOX["🛠️ Sandbox Clone Verification<br/>(Isolated Compile & Retest)"]
        SANDBOX --> REG_CHECK{"Regressions >= 1<br/>or 0 Tests Fixed?"}
        REG_CHECK -->|Yes| REJECT["❌ Auto-Reject Patch"]
        REG_CHECK -->|No (0 Regressions)| ACCEPT["✅ STATUS: VALIDATED<br/>(Safe 1-Click Apply to Production)"]
    end

    style INGEST fill:#1e293b,stroke:#3b82f6,stroke-width:2px,color:#fff
    style CACHE_LAYER fill:#1e293b,stroke:#8b5cf6,stroke-width:2px,color:#fff
    style SIM_LAYER fill:#1e293b,stroke:#06b6d4,stroke-width:2px,color:#fff
    style EVAL_LAYER fill:#1e293b,stroke:#10b981,stroke-width:2px,color:#fff
    style HEALING fill:#1e293b,stroke:#f59e0b,stroke-width:2px,color:#fff
```

---

## 🎛️ Multi-Firmware & Multi-Engine Simulation Matrix

FirmAgent includes **7 embedded firmware presets** spanning industrial, medical, consumer IoT, and robotics architectures:

| Preset Name | Description | Target Language | Hardware Specs | Simulation Engine | Suite | Verified Fix Status |
| :--- | :--- | :---: | :--- | :---: | :---: | :---: |
| **`fan_controller`** | Thermostat fan with hysteresis & sensor disconnect fail-safe | **Arduino C++** | Uno, DHT22, Relay, PWM Fan | `virtual_mock` / `wokwi` | 16 Tests | **16 / 16 PASS** ✅ |
| **`incubator_controller`** | Medical / laboratory incubator temperature stabilizer | **Arduino C++** | Uno, Precision Heater Relay | `virtual_mock` / `wokwi` | 16 Tests | **16 / 16 PASS** ✅ |
| **`water_tank_monitor`** | Industrial reservoir level monitor & pump cutoff | **Pure Embedded C** | Generic MCU, Level Sensor, Valve | `native_c` (GCC) | 16 Tests | **16 / 16 PASS** ✅ |
| **`iot_weather_node`** | Ambient weather telemetry node | **MicroPython** | ESP32 / RP2040, DHT22, Sleep | `python_sim` | 16 Tests | **16 / 16 PASS** ✅ |
| **`smart_door_lock`** | Security keypad access lock with lockout timer | **Arduino C++** | Uno, Matrix Keypad, LEDs, Buzzer | `virtual_mock` | 14 Tests | **14 / 14 PASS** ✅ |
| **`ultrasonic_radar`** | Proximity radar scanner with servo sweep | **Arduino C++** | Uno, HC-SR04, Micro Servo | `virtual_mock` | 16 Tests | **16 / 16 PASS** ✅ |
| **`robot_obstacle_avoidance`**| Autonomous differential drive ground robot | **Python / ROS2** | Diff Drive Chassis, 360° LiDAR | `gazebo` | 15 Tests | **15 / 15 PASS** ✅ |
| **`custom_uploaded`** | Open workspace slot for user custom code | **C / C++ / Python** | User Defined | Auto-detected | Dynamic | User custom code |

---

## 📊 Key Performance Benchmarks

```text
TEST CYCLE LATENCY (Lower is Better)
Physical Hardware MCU Flashing : [████████████████████] 320.0s
Wokwi Cloud CI Simulation      : [███                 ]  48.0s
⚡ FirmAgent Virtual Simulator  : [▍                   ]   6.4s (50x Speedup)

BEFORE VS AFTER SELF-HEALING TEST PASS RATE
water_tank_monitor (Pure C)    : 14/16 (87%) ➔ [████████████████████] 16/16 (100% PASS)
fan_controller (Arduino C++)   : 15/16 (94%) ➔ [████████████████████] 16/16 (100% PASS)
iot_weather_node (MicroPython) : 14/16 (87%) ➔ [████████████████████] 16/16 (100% PASS)
incubator_controller (C++)     :  0/16 (0%)  ➔ [████████████████████] 16/16 (100% PASS)
```

- **50x Faster Execution**: Average test execution time is **~0.4s** on the Universal Virtual Hardware engine.
- **100% Verified Patch Rate**: All benchmarked firmwares achieve **100% test pass rate** after applying sandbox fixes.
- **$0 Re-Run Cost**: SHA-256 SQLite caching eliminates repeated LLM queries during development.
- **Zero Simulator Errors (`0 ERROR`)**: Seamless failover avoids Wokwi cloud quota crashes.

---

## 🛡️ Safety & Reliability Architecture

FirmAgent enforces a **7-Stage Deterministic Safety Gate** before any patch can touch code:

1. **Hunk Count Limit**: $\le 3$ hunks allowed per patch proposal.
2. **Line Count Limit**: $\le 25$ total modified lines to prevent runaway rewrites.
3. **Exact Byte Match**: Every replaced line must match original source code byte-for-byte.
4. **Disjoint Hunks**: Zero overlapping hunk line ranges.
5. **Protected Range Locking**: `#include`, `#define`, and hardware pin macros are cryptographically locked.
6. **Spec Comment Block Integrity**: Specification docstring requirements cannot be altered.
7. **Sandbox Compilation & Zero-Regression Rule**:
   - The patch is tested in an isolated sandbox clone: `runs/<run_id>/fix/<attempt_id>/project/`.
   - Idempotent patching guarantees clean diff application from `.orig` backups.
   - Retests all previously passing tests: **Auto-Rejected** if even 1 regression occurs.

---

## 🖥️ Streamlit 5-Tab Dashboard Tour

Launch the web dashboard via `streamlit run app/main.py`:

- **Tab 1: 🚀 Run (One-Click Pipeline)**: Target firmware switcher, preflight syntax check, 1-click AI syntax auto-repair, live progress stepper, and run controls.
- **Tab 2: 🔍 Analysis**: Extracted formal specification rules, pin mapping diagrams, and peripheral hardware inventory.
- **Tab 3: 📋 Tests**: Dynamic test case catalog (T01..T16+), steps, expected outputs, and sensor disconnection scenarios.
- **Tab 4: ⚡ Live Execution**: Monospace serial UART log streaming, per-test timeline charts, and pass/fail/error status pills.
- **Tab 5: 📊 Report & Self-Healing**: Root-cause defect cards, side-by-side unified diffs, 7 safety checks, 1-click sandbox verification, and safe production apply/revert buttons.

---

## 💻 Technical Stack

- **Core Engine**: Python 3.10+, Pydantic v2 schemas, non-blocking cooperative threading.
- **AI Reasoning**: Google Gemini 2.5 Flash API via official `google-genai` SDK with strict JSON schema enforcement.
- **User Interface**: Streamlit 1.42+ with custom dark technical CSS, responsive metrics, and serial log viewers.
- **Simulation Backends**:
  - Universal Virtual Hardware Emulator (built-in state-machine emulator with microsecond precision).
  - Wokwi CLI (`wokwi-cli`) with dynamic scenario generation (`scenario.test.yaml`, `diagram.json`).
  - Native GCC / MinGW / Clang host simulation.
  - MicroPython telemetry runner.
  - Gazebo 3D simulation with SDF world and robot models.
- **Build Systems**: PlatformIO Core (`pio run`), GCC / MinGW, Python `py_compile`.
- **Database & Storage**: SQLite3 (`runs/firmagent.db`), SHA-256 hash indexing, JSON artifacts, unified diff patches.
- **Automated Verification**: Pytest suite (144 unit and integration tests with 100% pass rate).

---

## 🚀 Quick Start Guide

### Prerequisites
- Python 3.10, 3.11, or 3.12 installed.
- *(Optional)* [Wokwi CLI](https://docs.wokwi.com/wokwi-cli/getting-started) and [PlatformIO Core](https://platformio.org/).  
  *Note: FirmAgent runs 100% offline out-of-the-box using the built-in Universal Virtual Hardware simulator without installing Wokwi or PlatformIO.*

### 1. Clone & Setup Virtual Environment
```powershell
git clone https://github.com/your-username/firmagent.git
cd firmagent
python -m venv .venv
.venv\Scripts\activate      # On Windows
# source .venv/bin/activate # On Linux/macOS
pip install -r requirements.txt
```

### 2. Configure API Keys
Create a `.env` file in the project root:
```env
GEMINI_API_KEY=your_google_gemini_api_key_here
# Optional (for Wokwi cloud simulation):
WOKWI_CLI_TOKEN=your_wokwi_ci_token_here
```

### 3. Launch FirmAgent Dashboard
```powershell
streamlit run app/main.py
```
Open your browser at `http://localhost:8501`.

---

## 🧪 Running Automated Tests

Run the complete 144-test verification suite:
```powershell
.venv\Scripts\pytest -q
```
Expected output:
```text
144 passed, 1 warning in 7.5s
```

---

## 📁 Repository Structure

```text
firmagent/
├── agent/                      # Core agent logic
│   ├── builder.py              # PlatformIO & native GCC build manager
│   ├── compiler.py             # Wokwi YAML & diagram scenario compiler
│   ├── db.py                   # SQLite firmagent.db persistent cache manager
│   ├── evaluator.py            # Serial telemetry & expectation verification
│   ├── fixer.py                # Sandbox verification & fix orchestration
│   ├── generator.py            # LLM-assisted & fallback test generator
│   ├── models.py               # Pydantic data schemas
│   ├── orchestrator.py         # Autonomous pipeline state machine
│   ├── patcher.py              # Idempotent diff synthesis & safety checks
│   ├── syntax_fixer.py         # 1-Click compiler syntax diagnostics & repair
│   └── simulators/             # Pluggable simulation backends
│       ├── base.py             # Simulator interface base class
│       ├── gazebo_sim.py       # Gazebo 3D robotics simulation adapter
│       ├── mock_sim.py         # Universal zero-dependency virtual hardware
│       ├── native_sim.py       # Host GCC/Clang executable runner
│       ├── python_sim.py       # MicroPython runner
│       ├── registry.py         # Simulator registry & dynamic loader
│       └── wokwi_sim.py        # Wokwi cloud CLI adapter with quota guard
├── app/                        # Streamlit web interface
│   └── main.py                 # 5-Tab interactive dashboard
├── docs/                       # Project documentation & pitch deck
│   ├── FirmAgent_Pitch_Deck.pdf # 8-page 16:9 PDF presentation
│   ├── presentation.html       # Interactive web slides
│   ├── PRESENTATION.md         # Markdown slides with speaker notes
│   └── presentation_print.html # Print-optimized layout
├── firmware/                   # Embedded firmware project workspaces
│   ├── fan_controller/         # Arduino thermostat fan
│   ├── incubator_controller/   # Medical incubator stabilizer
│   ├── smart_door_lock/        # Security keypad access control
│   ├── water_tank_monitor/     # Pure C industrial reservoir monitor
│   ├── iot_weather_node/       # MicroPython weather station
│   ├── ultrasonic_radar/       # Proximity sweep radar scanner
│   └── robot_obstacle_avoidance/ # Gazebo differential drive robot
├── sample_firmwares/           # Pre-packaged sample firmware repository
├── runs/                       # Test execution runs, logs, and sandbox workspaces
│   └── firmagent.db            # Persistent SQLite cache database
└── tests/                      # Pytest unit & integration test suite (144 tests)
```

---

## 📜 License

Distributed under the **MIT License**. See `LICENSE` for more information.
