# 02 — Technical Requirements Document (TRD)

## 1. Platform
Local desktop tool on Windows. Python back end + Streamlit browser UI at `http://localhost:8501`. No cloud deployment.

## 2. Stack
| Layer | Choice | Reason |
|-------|--------|--------|
| Language | Python 3.11+ | Fast to build, good subprocess and JSON support |
| UI | Streamlit | A working UI in minutes, live progress updates |
| LLM | Gemini API via `google-genai` (model name in `.env` as `GEMINI_MODEL`) | Free API key from Google AI Studio, JSON output mode |
| Validation | Pydantic | Every LLM response is validated against a schema |
| Simulator | Wokwi CLI (`wokwi-cli`) with automation scenarios | Scriptable virtual hardware |
| Firmware build | PlatformIO Core (`pio run`) | Produces `.hex` and `.elf` for Wokwi |
| Target firmware | Arduino Uno (AVR) + DHT22 + LED as "fan" | Simplest supported combination |
| Scenario files | PyYAML | Test JSON → Wokwi YAML |

## 3. Architecture

```
Streamlit UI (app/main.py)
      │ start run / show progress
      ▼
Orchestrator (agent/orchestrator.py)   state machine + progress events
      ├─ Builder        code   pio run → firmware.hex / firmware.elf
      ├─ Analyzer       LLM    firmware source → analysis.json
      ├─ TestGenerator  LLM    analysis + source → tests.json
      ├─ Compiler       code   TestCase → scenario.yaml + diagram variant
      ├─ Runner         code   temp project → wokwi-cli → serial log + exit code
      ├─ Evaluator      code   pass/fail from expected vs observed
      ├─ FollowUp       LLM    failures → new probing tests → loop (max 2 rounds)
      ├─ RootCause      LLM    failures + numbered source → findings
      └─ Reporter       code   report.md + report.html
      ▼
runs/<run_id>/ (JSON files + report)
```

### Who decides what (very important for correctness)
| Decision | Made by |
|----------|---------|
| What is worth testing, what the expected behaviour is | LLM (from the spec comment + code) |
| Building YAML, running the simulator, parsing logs | Plain Python code |
| **PASS / FAIL verdict** | **Plain Python code** (never the LLM) |
| Why it failed, which lines, suggested fix | LLM (after the verdict is already fixed) |

## 4. Repository layout
```
firmagent/
├── app/main.py                 # Streamlit UI
├── agent/
│   ├── models.py               # Pydantic models (see 05_BACKEND_SCHEMA.md)
│   ├── llm.py                  # Gemini wrapper: JSON output, retry, cache
│   ├── prompts.py              # All prompt templates
│   ├── builder.py
│   ├── analyzer.py
│   ├── generator.py
│   ├── compiler.py
│   ├── runner.py
│   ├── evaluator.py
│   ├── followup.py
│   ├── rootcause.py
│   ├── reporter.py
│   ├── orchestrator.py
│   └── preflight.py            # checks tools, keys, CLI
├── firmware/fan_controller/    # demo firmware + Wokwi project
├── runs/                       # outputs (git-ignored) + runs/golden/
├── docs/                       # these documents
├── tests/                      # pytest for compiler/evaluator
├── .streamlit/config.toml
├── .env.example
├── requirements.txt
└── README.md
```

## 5. Simulation design (how a test really runs)
1. **Build once:** `pio run` in `firmware/fan_controller/` → copy `firmware.hex` and `firmware.elf`.
2. **One temp project per test** (`runs/<id>/sim/<test_id>/`) containing:
   - `firmware.hex`, `firmware.elf`
   - `diagram.json` (normal circuit, **or** the "sensor disconnected" variant with the DHT22 data wire removed)
   - `wokwi.toml` pointing to `firmware.hex` / `firmware.elf`
   - `scenario.test.yaml` generated from the test JSON
3. **Run:** `wokwi-cli <temp_dir> --scenario scenario.test.yaml --timeout 20000`
4. **Capture:** stdout (serial log) and exit code. Non-zero exit = a `wait-serial` never matched or timeout hit.
5. **Evaluate:** PASS only if exit code is 0 **and** none of the test's `must_not` strings appear in the log.

Scenario steps used (from the Wokwi automation docs): `set-control` (sensor value, e.g. DHT22 `temperature`), `delay`, `wait-serial`, `expect-pin`. Wokwi scenarios are marked *alpha*, so pin your `wokwi-cli` version once it works.

**Sensor disconnect:** implemented by generating a second `diagram.json` with the DHT22 SDA wire removed (the DHT library then returns NaN). Fallback if that does not work: the firmware treats an impossible value as a failed read, or accepts a serial fault-injection command.

## 6. External services and limits
| Service | Purpose | Limits / notes |
|---------|---------|----------------|
| Gemini API | Analyze, generate, follow-up, root cause | Free tier is rate-limited. Cache every response by hash of the prompt. |
| Wokwi CLI | Run simulations | Needs `WOKWI_CLI_TOKEN`. **Check free-tier limits tonight.** |
| PlatformIO | Build firmware | First build downloads the toolchain. **Do it tonight.** |

## 7. Security and privacy
- API keys only in `.env` (git-ignored). `.env.example` has empty names.
- Only the **firmware source** is sent to the LLM. Never send `.env`, docs Annex B, or any secret.
- Uploaded firmware is treated as untrusted text: the tool compiles only the bundled project unless a build is explicitly enabled.

## 8. Performance and reliability targets
| Target | Value |
|--------|-------|
| Full run (about 15 tests) | 3 to 8 minutes |
| Per-test timeout | 20 s, one automatic retry |
| LLM output | Validated by Pydantic; one automatic "repair" retry, then a clear error |
| Failure of one test | Never stops the run; the test is marked ERROR and the loop continues |
| Demo safety | **Replay mode** loads `runs/golden/` with zero network |

## 9. Environments and delivery
Local only. Git with small commits per task. One clean run-from-scratch on a fresh clone before the final demo.

## 10. Key technical decisions and trade-offs
| Decision | Reason | Alternative |
|----------|--------|-------------|
| Code decides PASS/FAIL | LLMs can mis-judge; judges want correctness | LLM as judge (rejected) |
| Spec comment is the oracle | Gives deterministic expected values | Infer intent from code only (used with a `confidence` flag when there is no spec) |
| Wokwi CLI | Real virtual hardware, scriptable | Renode (more setup) |
| Arduino Uno | Simple build, DHT22 supported | ESP32 (more moving parts) |
| Temp project per test | Isolated, allows diagram variants | Single shared project (cannot vary the circuit) |
| Sequential runs | Simple and stable | Parallel (only if time remains) |
| Streamlit | Very fast UI | Next.js (slower to build) |

## 11. Plan B (only if Wokwi cannot run by the go/no-go check)
Re-implement the demo firmware's decision logic as a pure C function (`fan_step(temp, state)`), compile it on the PC with `gcc` behind a tiny harness that reads test inputs and prints the same `[DATA]` lines. The runner switches with `SIMULATOR=host`. The problem statement allows "another suitable environment".
