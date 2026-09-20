# 06 — Implementation Plan

Each task is 20–40 minutes. Work one task at a time in **Antigravity 2.0** (new conversation per task). After every task: run it, verify the definition of done, commit, tick the box.

**Model guide:** Gemini = scaffolding, UI, report formatting. Claude/GPT = runner, evaluator, LLM prompts, follow-up loop, hard bugs.

Legend: ⭐ = must exist for the round shown.

---

## Milestone 0 — Tonight (go/no-go gate)
Goal: prove the simulator loop works before committing to PS3.

- [ ] **P-01 Install tools** — Python 3.11+, Git, VS Code, `pip install platformio`, Wokwi CLI. *Done when:* `python --version`, `git --version`, `pio --version`, `wokwi-cli --help` all work.
- [ ] **P-02 Get keys** — Wokwi CLI token (Wokwi CI dashboard) and Gemini API key (Google AI Studio). Put them in `.env`. *Done when:* both saved, `.env` is git-ignored.
- [ ] **P-03 Build the demo firmware** — in `firmware/fan_controller/` run `pio run`. *Done when:* `.pio/build/uno/firmware.hex` exists. (First build downloads the toolchain, so do it tonight.)
- [ ] **P-04 Run the two example scenarios** — `example_pass` must PASS, `example_fail_boundary` must FAIL (that proves bug B1 is detected). *Done when:* you see serial output and correct exit codes.
- [ ] **P-05 Gemini JSON test** — one small script sends a prompt and gets valid JSON back. *Done when:* JSON printed.
- **Gate:** all five done → continue with PS3. Stuck after ~45 min on P-03/P-04 → switch to Plan B (host simulator) or PS2.

---

## Milestone 1 — Setup and manual proof (10:00 → 12:00)
- [ ] **TASK-001 Scaffold** (Gemini, 20 min). Create folders from TRD §4, `requirements.txt`, `.gitignore`, `.env.example`, empty modules. *Done when:* `pip install -r requirements.txt` works, `streamlit run app/main.py` shows a blank page.
- [ ] **TASK-002 Preflight** (Gemini, 20 min). `agent/preflight.py` checks Gemini key, Wokwi token, `wokwi-cli`, `pio`. UI sidebar shows green/red items. *Done when:* removing a key turns its item red.
- [ ] **TASK-003 Models** (Claude/GPT, 25 min). Paste Pydantic models from doc 05 into `agent/models.py`; add `tests/test_models.py`. *Done when:* `pytest` passes.
- [ ] **TASK-004 LLM wrapper** (Claude/GPT, 30 min). `agent/llm.py`: call Gemini with JSON output, validate with Pydantic, one repair retry, exponential backoff on rate limit, disk cache by prompt hash. *Done when:* a sample call returns a validated object and the second identical call hits the cache.
- [ ] **TASK-005 Builder** (Gemini, 20 min). `agent/builder.py`: run `pio run`, return paths of `.hex` and `.elf`, or the last 20 log lines on error. *Done when:* returns paths for the demo firmware.

---

## Milestone 2 — Evaluation 1 target (12:00 → 3:15) ⭐
- [ ] **TASK-006 Analyzer** (Claude/GPT, 30 min) ⭐. `agent/analyzer.py` + prompt: source with line numbers → `FirmwareAnalysis`. *Done when:* the demo firmware yields rules R1–R6 with correct line numbers.
- [ ] **TASK-007 Test generator** (Claude/GPT, 35 min) ⭐. `agent/generator.py` + prompt: 12–20 tests in at least 6 categories, using the exact serial format. *Done when:* `tests.json` validates and includes boundary at 30.0, hysteresis 31→29, sensor disconnected.
- [ ] **TASK-008 Compiler** (Claude/GPT, 35 min) ⭐. `agent/compiler.py`: `TestCase` → `scenario.test.yaml` (`wait-serial [INFO] BOOT`, then `set-control` + `delay` + `wait-serial` per step) and diagram variant for `sensor="disconnected"`. *Done when:* generated YAML runs in `wokwi-cli` by hand. Add pytest for the YAML output.
- [ ] **TASK-009 Runner** (Claude/GPT, 40 min) ⭐. `agent/runner.py`: build the temp project, run `wokwi-cli` with a 20 s timeout, capture stdout + exit code, save `serial.log`. *Done when:* one generated test runs and returns exit code and log.
- [ ] **TASK-010 Round-1 demo path** (Gemini, 30 min) ⭐. A CLI script (and a basic Streamlit page) that does: analyze → generate → run the boundary test → print the result; Analysis and Tests tabs display JSON nicely. *Done when:* you can show all of that live in under 2 minutes.
- [ ] **Eval 1 prep (15 min):** commit, screenshot, rehearse the 2-minute story (see ROADMAP).

---

## Milestone 3 — Evaluation 2 target (3:30 → 9:15) ⭐
- [ ] **TASK-011 Run-all with progress** (Claude/GPT, 30 min) ⭐. Runner loop over all tests, emits progress events, one failure never stops the run. *Done when:* all tests run, ERRORs are recorded.
- [ ] **TASK-012 Evaluator** (Claude/GPT, 40 min) ⭐. `agent/evaluator.py`: PASS iff exit code 0 and no `must_not` string in the log; extract observed lines for the expected pattern (e.g. lines with the same temp). *Done when:* pytest covers pass, fail, `must_not` violation, timeout.
- [ ] **TASK-013 Orchestrator** (Claude/GPT, 40 min) ⭐. `agent/orchestrator.py` state machine from App Flow §4, saves all JSON files, writes `manifest.json`. *Done when:* one function call runs the whole loop and produces `results.json`.
- [ ] **TASK-014 Root cause** (Claude/GPT, 40 min) ⭐. `agent/rootcause.py`: failed results + numbered source → `Finding`s (cause, suspect lines, suggested fix). *Done when:* the 3 planted bugs each produce a Finding pointing at the right lines.
- [ ] **TASK-015 Reporter** (Gemini, 40 min) ⭐. `agent/reporter.py`: `report.md` and `report.html` (summary cards, coverage matrix, test table, failure cards). *Done when:* the report opens in a browser and reads well.
- [ ] **TASK-016 Streamlit UI v1** (Gemini, 60 min) ⭐. Five tabs from doc 04, live progress, one-click run. *Done when:* the full loop runs from the browser.
- [ ] **TASK-017 Golden run + Replay** (Gemini, 30 min) ⭐. After a good run, copy to `runs/golden/`; *Load golden run* button fills every tab offline. *Done when:* works with Wi-Fi off.
- [ ] **TASK-018 End-to-end dry run** (you, 45 min) ⭐. Run start-to-finish three times. Fix flakiness (timeouts, wording of expected strings). *Done when:* B1, B2, B3 are found in 3 runs out of 3 and correct behaviours pass.

---

## Milestone 4 — Evaluation 3 target (9:30 PM → 12:30 AM, then sleep, up by 3:15 AM) ⭐
- [ ] **TASK-019 Autonomous follow-up loop** (Claude/GPT, 60 min) ⭐. `agent/followup.py`: for failures, generate up to 6 probing tests (e.g. 29.9, 30.1 around a failed boundary; more disconnect timings), run them, evaluate, repeat max 2 rounds. Tag as `followup`, show 🔁 in the UI. *Done when:* the demo run shows follow-up tests created without any user click.
- [ ] **TASK-020 Coverage tuning** (Claude/GPT, 30 min). Improve the generator prompt until every category appears (normal, boundary, abnormal, sensor failure, recovery, sequence, combination). Add a coverage matrix to the report. *Done when:* the matrix has no empty category.
- [ ] **TASK-021 UI polish and error states** (Gemini, 45 min). Empty/loading/error states, Stop button, Re-run one test, Preflight hints. *Done when:* unplugging the internet or removing a key shows a friendly message, not a crash.
- [ ] **TASK-022 Second firmware (optional, P2)** (Claude/GPT, 60 min). e.g. a door/motion alarm. Only if everything above is stable. *Done when:* the agent analyses it and generates tests (execution optional).
- **12:30 AM → sleep.** Tired prompts create bugs. Alarm for 3:15 AM.

---

## Milestone 5 — Final (4:00 → 9:00 AM)
- [ ] **TASK-023 README + architecture + setup steps** (Gemini, 30 min): required documentation deliverables.
- [ ] **TASK-024 Presentation** (Gemini chat, 45 min): 5-slide deck, 3 screenshots, a 60-second backup screen recording of a full run.
- [ ] **TASK-025 Clean-room test** (you, 30 min): fresh clone, `pip install -r requirements.txt`, `.env`, run once, refresh `runs/golden/`.
- [ ] **TASK-026 Rehearse** (you, 3 times, timer on): exactly 5 minutes.
- **No new features after 7:30 AM.**

---

## Per-task loop (every time)
Read → Plan (ask Antigravity for a plan first, no code) → Implement (only this task, do not touch other files) → Run and test → Review the diff → Commit (`feat: TASK-0xx …`) → tick the box → new conversation.

## If you fall behind (cut in this order)
1. TASK-022 second firmware
2. HTML report (keep Markdown)
3. Re-run-one-test button
4. Follow-up rounds down from 2 to 1
5. **Never cut:** analyzer, generator, compiler, runner, evaluator, report, replay mode.
