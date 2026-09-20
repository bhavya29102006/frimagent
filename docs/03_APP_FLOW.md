# 03 — App Flow

## 1. Entry point
`streamlit run app/main.py` → opens `http://localhost:8501`. The very first thing shown is the **Preflight** panel (tools and keys OK or missing).

## 2. Screen inventory
| Screen / tab | Purpose | Data it needs |
|--------------|---------|---------------|
| Sidebar: Settings + Preflight | Show that Gemini key, Wokwi token, `wokwi-cli`, `pio` are found; choose firmware; buttons | env status, firmware list |
| Tab 1: Run | Choose firmware, big **Run autonomous test** button, overall progress | selected firmware, run state |
| Tab 2: Analysis | Show what the agent understood | `analysis.json` |
| Tab 3: Tests | Table of generated tests grouped by category | `tests.json` |
| Tab 4: Live Execution | Per-test status, serial log viewer, expected vs observed | `results.json`, live events |
| Tab 5: Report | Final report, download buttons | `report.md`, `report.html` |

## 3. Primary journey
Open app → Preflight all green → choose *Demo: fan_controller* → click **Run autonomous test** → *Building* → *Analyzing* → *Generating tests* → *Running tests* (live list turns ✅ / ❌) → *Root-cause analysis* → *Follow-up tests* (agent adds new tests around failures) → *Report* → download.

## 4. Pipeline state machine
```
IDLE → BUILDING → ANALYZING → GENERATING → RUNNING(test i of n)
     → EVALUATING → [failures?] → FOLLOWUP → RUNNING(new tests) → EVALUATING
     → (repeat, max 2 rounds) → ROOT_CAUSE → REPORTING → DONE
Any state → FAILED (with a clear message) — the UI never crashes.
```

## 5. Action specifications
| Action | Trigger | Validation | Loading state | Success | Error | Next |
|--------|---------|------------|---------------|---------|-------|------|
| Run autonomous test | Button click | Preflight OK, firmware file present and under 200 KB | Progress bar + current step name | Report tab opens | Red banner with the reason and a "Fix" hint | Report tab |
| Build firmware | Orchestrator | `pio` found | "Building firmware…" | `firmware.hex` exists | Show build log tail | Analyze |
| Analyze | Orchestrator | Source not empty | "Reading firmware…" | Analysis tab filled | Retry once, then show error | Generate |
| Generate tests | Orchestrator | Analysis valid JSON schema | "Designing tests…" | Tests tab filled (≥ 8 tests) | Retry once with repair prompt | Run |
| Run one test | Orchestrator | Compiled scenario exists | Row shows ⏳ | Row shows ✅ or ❌ | Row shows ⚠ ERROR (run continues) | Next test |
| Follow-up | Failures exist | Round < 2 | "Probing failures…" | New rows appended, tagged *follow-up* | Skip and continue | Evaluate |
| Root cause | After tests | At least one FAIL | "Explaining failures…" | Findings added | Fall back to rule-based text | Report |
| Load golden run | Button | `runs/golden/` exists | Instant | All tabs filled | "No golden run found" | Report |
| Download report | Button | Report exists | none | File saved | none | — |

## 6. Alternate journeys
- **Replay:** *Load golden run* fills every tab from disk. No network needed.
- **Re-run one test:** In Live Execution, click *Re-run* on a row to execute only that test.
- **Cancel:** *Stop* button sets a flag. The current test finishes, then the run ends with the partial report.
- **Upload own firmware:** Upload a `.cpp/.ino`. Analysis and test generation work. Execution needs a matching Wokwi project, so uploaded firmware runs in *analysis-only* mode unless a project is attached.

## 7. Navigation rules
Tabs stay visible during a run. Tabs fill progressively (Analysis appears as soon as it is ready). Reload keeps the last run (loaded from `runs/`).

## 8. Empty and blocked states
| Situation | What the user sees |
|-----------|--------------------|
| No Gemini key | Sidebar red item: "Add GEMINI_API_KEY to .env". Run disabled. |
| No Wokwi token / CLI | Red item with install hint. Offer *Load golden run*. |
| Gemini rate limit | Message "Rate limited, retrying in N s", automatic backoff |
| No internet | Banner: "Offline: use Replay mode" |
| Build fails | Last 20 lines of the build log in a code block |
| No failures found | Report says "No failures detected" and shows the coverage matrix |

## 9. First-use journey
1. Fill `.env` from `.env.example` (Gemini key, Wokwi token).
2. Start the app. Preflight shows green ticks.
3. Click *Run autonomous test* on the bundled demo. Done.
