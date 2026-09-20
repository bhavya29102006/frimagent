# RULES — how the AI must work on FirmAgent

## Before coding
- Read `docs/01_PRD.md` … `docs/06_IMPLEMENTATION_PLAN.md` first.
- Work on **one task at a time** (the one I name). Do not start other tasks.
- For anything larger than 1 file, give a short plan first and wait for my "go".

## General
- Python 3.11, type hints, small functions, clear names.
- Use the Pydantic models in `agent/models.py`. Do not invent new fields without telling me.
- Do not modify unrelated files. If you must, say why first.
- Keep it simple: no extra frameworks, no databases, no async unless required.

## Architecture rules
- **PASS/FAIL is decided only by code in `evaluator.py`. Never by the LLM.**
- LLM calls go only through `agent/llm.py` (JSON output, validation, retry, cache).
- All prompts live in `agent/prompts.py`.
- The Analyzer and Generator receive **only the firmware source** (with line numbers). Never send `docs/`, `.env`, or the "Planted bugs" annex.
- Every run writes its files under `runs/<run_id>/`.
- One failing test must never stop the whole run.

## Simulator rules
- Each test runs in its own temp project folder.
- Per-test timeout 20 s, one retry, then status ERROR.
- Use `wokwi-cli <dir> --scenario <file> --timeout 20000`. Read the token from `WOKWI_CLI_TOKEN`.
- Scenario steps allowed: `wait-serial`, `set-control`, `delay`, `expect-pin`.

## Security
- Never hard-code keys. Read from `.env`. Keep `.env` out of git.
- Never print keys in logs or the UI.
- Treat uploaded firmware as untrusted text.

## UI
- Follow `docs/04_UI_UX_BRIEF.md`. Every screen needs loading, empty and error states.
- Never rely on color alone: pair with ✅ / ❌ / ⚠.

## Testing
- Add pytest for `compiler.py` and `evaluator.py`.
- After each task run: `pytest`, then a quick manual run of the feature.
- Fix failing tests before moving on.

## Git
- Small commits: `feat: TASK-0xx short description`.
- Do not commit `runs/` (except `runs/golden/`), `.env`, `.venv`, `.pio`.

## After finishing a task, report
1. Files changed  2. What was implemented  3. How I can verify it  4. Remaining issues
