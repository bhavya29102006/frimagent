# ROADMAP — Black Box Hackathon 2026 (PS3: FirmAgent)

Official schedule: 10:00 AM start · 2:30 PM lunch · **3:30 PM Eval 1** · 8:00 PM dinner · **9:30 PM Eval 2** · 12:00 AM fun session · **4:00 AM Eval 3** · 7:30 AM freshen up · **9:00 AM final 5-minute PPT**. All three evaluation rounds are compulsory, so each round needs something that runs.

## Full timeline
| Time | What you do | Tasks |
|------|-------------|-------|
| 9:00–10:00 | Registration. Open project in Antigravity 2.0 and VS Code. Check quota and Wi-Fi. | — |
| 10:00–12:00 | Scaffold, preflight, models, LLM wrapper, builder | TASK-001…005 |
| 12:00–2:30 | Analyzer, generator, compiler, runner (start) | TASK-006…009 |
| 2:30–3:00 | Lunch (fast) | — |
| 3:00–3:30 | Finish demo path, rehearse Eval 1 | TASK-010 |
| **3:30** | **EVALUATION 1** | |
| 3:45–6:30 | Run-all, evaluator, orchestrator, root cause | TASK-011…014 |
| 6:30–8:00 | Reporter, UI v1 | TASK-015…016 |
| 8:00–8:45 | Dinner | — |
| 8:45–9:30 | Golden run + Replay, dry run, rehearse Eval 2 | TASK-017…018 |
| **9:30 PM** | **EVALUATION 2** | |
| 10:00–12:30 | Follow-up loop, coverage tuning, UI polish | TASK-019…021 |
| 12:00 AM | Fun session (20 min max) then **sleep until 3:15 AM** | — |
| 3:15–4:00 | Fresh full run, refresh golden run, rehearse Eval 3 | — |
| **4:00 AM** | **EVALUATION 3** | |
| 4:30–7:30 | README, architecture doc, presentation, clean-room test | TASK-023…025 |
| 7:30–9:00 | Freshen up, breakfast, rehearse 3 times | TASK-026 |
| **9:00 AM** | **FINAL 5-MINUTE PRESENTATION** | |

---

## Evaluation 1 — 3:30 PM (5½ hours in)
**Goal:** prove you understand the problem and the agent already "thinks".

**Must be working ⭐**
- Demo firmware (fan controller) built and shown running in Wokwi
- Analyzer: firmware → structured analysis (rules R1–R6 with line numbers)
- Generator: 12+ tests in several categories
- Compiler + Runner: **one** generated test executed in the simulator, result shown

**Show (2 minutes)**
1. Architecture diagram: "LLM decides what to test, code runs and judges" (20 s)
2. Firmware and its spec (15 s)
3. Click analyze → Analysis tab (30 s)
4. Generate → Tests tab, point at boundary and sensor-disconnect tests (30 s)
5. Run one test live and show the serial log with a verdict (25 s)

**Judges' criteria you hit:** Firmware Understanding, Test Generation, Edge Cases (early).

**Minimum acceptable:** analysis JSON + test list + generated YAML file shown, with a manual Wokwi run of that YAML.

**Exit checklist:** committed · screenshots taken · docs in `docs/` · you know what to say in 2 minutes.

---

## Evaluation 2 — 9:30 PM (11½ hours in)
**Goal:** the complete loop works end to end.

**Must be working ⭐**
- One click: build → analyze → generate → run **all** tests → evaluate → report
- Bugs B1, B2, B3 found; correct behaviours PASS
- Root cause with source line numbers for each failure
- Streamlit UI with live progress; Replay mode

**Show (3 minutes)**
1. Click *Run autonomous test* (say nothing for a moment: let the live list fill) (60 s)
2. Point at ❌ tests: expected vs observed (45 s)
3. Report tab: finding for B1 with lines and suggested fix (45 s)
4. Coverage matrix and metrics (20 s)
5. If slow: switch to *Load golden run* (10 s)

**Judges' criteria you hit:** Simulation, Failure Detection, Analysis, Automation, User Experience.

**Minimum acceptable:** pipeline produces a report with at least 2 of 3 bugs found, run from CLI or UI.

**Exit checklist:** 3 clean runs in a row · golden run saved · everything committed and pushed.

---

## Evaluation 3 — 4:00 AM (18 hours in)
**Goal:** show it is truly autonomous and polished.

**Must be working ⭐**
- Follow-up loop: after failures the agent invents extra tests by itself (29.9 / 30.0 / 30.1, disconnect timing) and re-runs
- Coverage matrix with all categories
- Friendly error and empty states (no crash without internet or a key)
- (Optional) second firmware analyzed

**Show (3 minutes)**
1. Full run start to finish, narrating what the agent decides (90 s)
2. Highlight the 🔁 follow-up tests: "nobody wrote these" (30 s)
3. Failure explanation and suggested fix (30 s)
4. Replay mode / robustness (15 s)
5. Limitations and next steps (15 s)

**Judges' criteria you hit:** Edge Cases, Automation, Analysis, User Experience.

**Minimum acceptable:** Eval-2 build with a stable run plus a one-round follow-up loop.

**Exit checklist:** you slept · fresh full run passes · golden run refreshed.

---

## Final presentation — 9:00 AM (5 minutes, exactly)
| Time | Slide | Say |
|------|-------|-----|
| 0:00–0:30 | 1. Problem | "Firmware testing is manual, slow and misses edge cases." |
| 0:30–1:15 | 2. Architecture | "The LLM decides what to test; Python runs the simulator and decides pass/fail." |
| 1:15–3:45 | 3. **Live demo** | One click → tests → failures → report → follow-up tests |
| 3:45–4:30 | 4. Results | "Found 3 planted bugs, N tests, X seconds, zero manual test cases." |
| 4:30–5:00 | 5. Autonomy and next steps | "Follow-up loop; next: more MCUs, CI integration." |

**Backups:** replay mode, 60-second screen recording, screenshots in the PPT.

---

## Demo-day risk list
| Risk | Prevention |
|------|-----------|
| Wi-Fi drops | Replay mode from `runs/golden/`, Gemini cache on |
| Gemini rate limit | Disk cache, backoff, retry; keep prompts small |
| Wokwi token or limits | Test early, keep golden run |
| Laptop battery | Charger at the table, close other apps |
| A test hangs | 20 s timeout, one retry, ERROR status, run continues |
| Antigravity quota out | Switch model pool (Gemini ↔ Claude/GPT) |
