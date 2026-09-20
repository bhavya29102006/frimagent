# 04 — UI and UX Design Brief

## 1. Audience and tone
Engineers and hackathon judges. Design adjectives: **clear, technical, trustworthy**. Results must be readable from across a room during a demo.

## 2. Reference products
- GitHub Actions run page (borrow: per-job status list with ✅ / ❌ and expandable logs)
- Playwright HTML report (borrow: pass/fail summary + expandable failure detail)
- Avoid: chat-style layouts (the judges said "not a chatbot")

## 3. Color palette (Streamlit dark theme)
| Role | Hex |
|------|-----|
| Primary / accent | `#6366F1` |
| Background | `#0F172A` |
| Surface (cards) | `#1E293B` |
| Text | `#E2E8F0` |
| Muted text | `#94A3B8` |
| PASS | `#22C55E` |
| FAIL | `#EF4444` |
| WARNING / follow-up | `#F59E0B` |
| INFO | `#38BDF8` |

`.streamlit/config.toml` is already included in the kit.

## 4. Typography
UI: Inter (or Streamlit default sans). Logs, serial output and code: monospace. Headings large; log text small but readable.

## 5. Components
- **Metric cards** (top of Report): Tests run, Passed, Failed, Bugs found, Follow-up tests.
- **Status pill:** ✅ PASS, ❌ FAIL, ⚠ ERROR, ⏳ RUNNING, 🔁 FOLLOW-UP.
- **Test table:** ID, name, category, status, duration.
- **Expandable row:** Expected vs Observed side by side, serial log, spec rule reference.
- **Code viewer:** firmware source with line numbers; suspect lines highlighted.
- **Progress stepper:** Build → Analyze → Generate → Run → Explain → Report.
- **Buttons:** Primary *Run autonomous test*; secondary *Load golden run*; *Stop*; *Download report*.

## 6. Layout rules
Wide layout. Sidebar (settings, preflight) + main area with 5 tabs. Cards use 12 px radius. 16 px spacing scale. On a projector, use browser zoom 125%.

## 7. Screen notes
**Tab 1 Run:** big centered button, firmware picker, progress stepper under it. Nothing else.

**Tab 2 Analysis:** four small cards: *Inputs*, *Outputs*, *Thresholds and constants*, *States and error handling*. Below: a table of **spec rules R1..Rn** with the source lines each maps to. Show a *Risk areas* list (where bugs are likely).

**Tab 3 Tests:** grouped by category (Normal, Boundary, Abnormal, Sensor failure, Recovery, Sequence, Combination, Follow-up). Each test shows its name, steps in plain words ("set temp 31 → wait 2.5 s") and expected result.

**Tab 4 Live Execution:** left list of tests with live status; right panel with the selected test's serial log. Failing test opens automatically with Expected vs Observed highlighted.

**Tab 5 Report:** metric cards, coverage matrix (category × pass/fail), failure cards each with *what happened*, *why (likely cause)*, *source lines*, *suggested fix*. Download buttons (Markdown, HTML).

## 8. Accessibility
Never rely on color alone: always pair color with an icon and text (✅ PASS, ❌ FAIL). Contrast at least 4.5:1. Keyboard-usable buttons (Streamlit default). Log text not smaller than 13 px.

## 9. Interaction states
- Loading: spinner plus the current step name.
- Empty: friendly message with the next action (e.g. "Pick a firmware and press Run").
- Error: red banner with a plain-language cause and a hint.
- Success: green summary banner "N tests, X failures found".

## 10. Assets needed
None. Use emoji/icons from Streamlit. For the presentation only: one architecture diagram and 3 screenshots (analysis, live run, report).

## 11. Presentation slides (5 minutes)
1. Problem (30 s) 2. Architecture (45 s) 3. Live demo (2 min 30 s) 4. Results: bugs found (45 s) 5. Why it is autonomous and what is next (30 s).
