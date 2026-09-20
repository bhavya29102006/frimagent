# START HERE — exact steps for FirmAgent (PS3)

Commands below are for **Windows** (PowerShell or Git Bash). Wherever they differ, both are shown.
If the organizers do not allow pre-work, do PART A (tools only) tonight and PART B tomorrow at 10:00.

---

## PART A — Tonight (about 60–90 minutes): tools + go/no-go test

### A1. Install the basics
1. **Python 3.11+** from python.org. Tick **"Add Python to PATH"**. Check:
   ```
   python --version
   pip --version
   git --version
   ```
2. **VS Code** and **Antigravity 2.0** (already done). Ignore Antigravity IDE.

### A2. Create the project folder
1. Unzip `firmagent-kit.zip` somewhere simple, e.g. `C:\hack\firmagent`.
2. Open that folder in **VS Code** and in **Antigravity 2.0** (same folder in both).
3. In the VS Code terminal:
   ```
   git init
   python -m venv .venv
   ```
   Activate it:
   - PowerShell: `.venv\Scripts\Activate.ps1`
   - Git Bash: `source .venv/Scripts/activate`

   If PowerShell blocks scripts, run once: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`
4. Install packages:
   ```
   pip install -r requirements.txt
   pio --version
   ```

### A3. Get your two keys
1. **Wokwi:** create a free account at wokwi.com, then open the **Wokwi CI dashboard** (from your account/profile) and create a **CLI token**. Check the free limits shown there.
2. **Gemini:** go to Google AI Studio → *Get API key*.
3. Copy `.env.example` to `.env` and fill:
   ```
   GEMINI_API_KEY=your_key
   GEMINI_MODEL=<a current Flash model name shown in AI Studio>
   WOKWI_CLI_TOKEN=your_token
   ```
4. Make sure `.env` is listed in `.gitignore` (it already is).

### A4. Install Wokwi CLI
- PowerShell:
  ```
  iwr https://wokwi.com/ci/install.ps1 -useb | iex
  ```
- Close and reopen the terminal, then: `wokwi-cli --help`
- Set the token for this terminal session:
  - PowerShell: `$env:WOKWI_CLI_TOKEN="your_token"`
  - Git Bash: `export WOKWI_CLI_TOKEN=your_token`

### A5. Build the demo firmware (do this tonight: first build downloads the toolchain)
```
cd firmware/fan_controller
pio run
```
Success = the file `.pio/build/uno/firmware.hex` exists.

### A6. Run the example scenarios in the simulator
Still inside `firmware/fan_controller`:
```
wokwi-cli . --scenario tests/example_pass.test.yaml --timeout 20000
wokwi-cli . --scenario tests/example_fail_boundary.test.yaml --timeout 20000
wokwi-cli . --scenario tests/example_fail_hysteresis.test.yaml --timeout 20000
```
**Expected result:**
- `example_pass` → PASS (exit code 0)
- `example_fail_boundary` → FAIL (proves bug B1 is detectable)
- `example_fail_hysteresis` → FAIL (proves bug B2 is detectable)

Check the exit code: PowerShell `$LASTEXITCODE`, Git Bash `echo $?`.

**If `diagram.json` gives an error:** open wokwi.com → new **Arduino Uno** project → add a **DHT22** (SDA to pin 2, VCC to 5V, GND to GND) and an **LED** with a 220 Ω resistor on pin 13 → open the `diagram.json` tab and copy it over the one in the folder. The part IDs must stay `dht1` and `led1`.

### A7. Disconnected-sensor check
Copy `diagram.json` to `diagram_disconnected.json` and delete the line that connects `dht1:SDA` to `uno:2`. Run the firmware with that diagram and confirm the serial shows `temp=nan`. This is how the agent will test "sensor disconnected" (bug B3).

### A8. Gemini JSON check
Create a tiny script that calls Gemini and asks for `{"ok": true}` in JSON. If it prints valid JSON, you are ready.

### A9. GO / NO-GO
| Result | Decision |
|--------|----------|
| A5, A6 and A8 work | **GO with PS3** |
| Simulator works but disconnect (A7) does not | Still GO: use the fallback (firmware treats an impossible value as a failed read) |
| Stuck for about 45 minutes on A5/A6 | Use **Plan B (host simulator, TRD §11)** or switch to PS2. Message me. |

Finally commit: `git add . && git commit -m "chore: starter kit"`

---

## PART B — Tomorrow: first hour (10:00–11:00)

1. **Open Antigravity 2.0** with the project folder. Pick a model (Gemini for scaffolding).
2. **First message (context, no code):**
   ```
   Read docs/01_PRD.md, 02_TRD.md, 03_APP_FLOW.md, 04_UI_UX_BRIEF.md,
   05_BACKEND_SCHEMA.md, 06_IMPLEMENTATION_PLAN.md and RULES.md.
   Do NOT write code yet.
   1. Summarize what we are building in 5 lines.
   2. List any contradictions or missing information.
   3. Explain your plan for TASK-001.
   ```
3. Read its answer. Fix any contradictions in the docs (short edits).
4. **Second message (implement):**
   ```
   Plan approved. Implement ONLY TASK-001 from docs/06_IMPLEMENTATION_PLAN.md.
   Do not touch firmware/ or docs/.
   When done, run pip install -r requirements.txt and streamlit run app/main.py,
   then tell me: files changed, what works, remaining issues.
   ```
5. In VS Code: run the app, check it opens. Then:
   ```
   git add .
   git commit -m "feat: TASK-001 scaffold"
   ```
6. Tick TASK-001 in the plan, **open a new conversation**, and repeat with TASK-002, TASK-003…

### Prompt template for every task
```
CONTEXT: FirmAgent, read docs/ and RULES.md.
TASK: <copy the task line from 06_IMPLEMENTATION_PLAN.md>
FILES: <files this task may create or change>
CONSTRAINTS: only this task, no unrelated files, PASS/FAIL only in evaluator.py
ACCEPTANCE: <the "Done when" line>
TESTING: run pytest and show me how to verify manually.
Report: files changed, what was implemented, how to verify, remaining issues.
```

### Which model for what
- **Gemini:** TASK-001, 002, 005, 010, 015, 016, 017, 021, 023.
- **Claude/GPT:** TASK-003, 004, 006–009, 011–014, 018–020.
- Switch models only **between** tasks, after a commit.

## Bug report format (never just "fix this")
```
ERROR: <paste>
EXPECTED: <what should happen>
ACTUAL: <what happens>
STEPS: <how to reproduce>
Do not modify code yet. Find the root cause, then make the smallest fix.
```

## Helper chats (do NOT let them touch the code)
- **Claude chat:** review a file you paste, explain a stubborn bug.
- **Gemini chat:** presentation points, pitch, README wording.
- Never paste `.env` or API keys into any chat.
