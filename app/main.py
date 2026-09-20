"""FirmAgent — Streamlit Application Entrypoint.

5-tab UI adhering to docs/04_UI_UX_BRIEF.md and docs/03_APP_FLOW.md:
1. Run: Autonomous one-click test execution with progress stepper.
2. Analysis: Firmware analysis, spec rules oracle, and risk areas.
3. Tests: Generated test suite grouped by category with plain-words steps.
4. Live Execution: Master-detail test inspector, serial log viewer, and re-run single test.
5. Report: Executive metric cards, coverage matrix, bug findings with suggested fixes, and downloads.
"""

import html
import json
from pathlib import Path
import sys
import time
import pandas as pd
import streamlit as st

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.analyzer import analyze_firmware
from agent.evaluator import collapse_firmware_lines
from agent.generator import generate_tests
from agent.models import (
    Finding,
    FirmwareAnalysis,
    RunManifest,
    TestCase,
    TestList,
    TestResult,
)
from agent.orchestrator import run_all
from agent.preflight import run_preflight
from agent.reporter import generate_reports
from agent.rootcause import run_root_cause
from agent.runner import run_test

st.set_page_config(
    page_title="FirmAgent — Autonomous Firmware Testing",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom CSS for dark technical styling
st.markdown(
    """
    <style>
    .metric-card {
        background: #1E293B;
        border: 1px solid #334155;
        border-radius: 10px;
        padding: 14px 18px;
        margin-bottom: 12px;
    }
    .badge-pill {
        display: inline-block;
        padding: 2px 8px;
        font-size: 11px;
        font-weight: 600;
        border-radius: 6px;
    }
    .badge-pass { background: rgba(34, 197, 94, 0.2); color: #22C55E; border: 1px solid #22C55E; }
    .badge-fail { background: rgba(239, 68, 68, 0.2); color: #EF4444; border: 1px solid #EF4444; }
    .badge-err  { background: rgba(245, 158, 11, 0.2); color: #F59E0B; border: 1px solid #F59E0B; }
    </style>
""",
    unsafe_allow_html=True,
)

FIRMWARE_SRC_FILE = (
    PROJECT_ROOT / "firmware" / "fan_controller" / "src" / "main.cpp"
)
FIRMWARE_DIR = PROJECT_ROOT / "firmware" / "fan_controller"
RUNS_DIR = PROJECT_ROOT / "runs"


def get_available_runs() -> list[str]:
    """List available run directory names sorted newest first."""
    if not RUNS_DIR.is_dir():
        return []
    candidates = []
    for d in RUNS_DIR.iterdir():
        if d.is_dir() and d.name != "cache":
            candidates.append(d)
    candidates.sort(key=lambda d: d.stat().st_mtime, reverse=True)
    return [c.name for c in candidates]


def format_steps_plain(test: TestCase) -> str:
    """Format test steps into human-readable plain language."""
    if test.sensor == "disconnected":
        return "Sensor wire disconnected (expect fail-safe)"
    if not test.steps:
        return "No input change"
    parts = []
    for s in test.steps:
        if s.set_temp is not None:
            parts.append(f"Set temp {s.set_temp:.1f}°C")
        else:
            parts.append("Maintain temp")
    return " ➔ ".join(parts)


# ==========================================
# Sidebar: Settings, Preflight & Run Selection
# ==========================================
with st.sidebar:
    st.header("⚡ FirmAgent")
    st.caption("Autonomous Embedded Firmware Testing")

    # Preflight Panel
    with st.expander("🛠 Preflight Checks", expanded=True):
        checks = run_preflight()
        all_ok = True
        for check in checks:
            if check.ok:
                st.markdown(f"✅ **{check.name}** (`{check.detail}`)")
            else:
                all_ok = False
                st.markdown(f"❌ **{check.name}** (`{check.detail}`)")
                if check.hint:
                    st.caption(f"💡 {check.hint}")

    st.divider()
    st.subheader("Configuration")
    selected_fw = st.selectbox(
        "Target Firmware",
        options=["Demo: fan_controller (Arduino Uno + DHT22)"],
        index=0,
    )

    # Run Selector / Replay
    avail_runs = get_available_runs()
    if "active_run_id" not in st.session_state and avail_runs:
        st.session_state["active_run_id"] = avail_runs[0]

    run_opts = ["(New Autonomous Run)"] + avail_runs
    current_idx = 0
    if st.session_state.get("active_run_id") in avail_runs:
        current_idx = avail_runs.index(st.session_state["active_run_id"]) + 1

    selected_run_opt = st.selectbox(
        "Viewed Run / Replay",
        options=run_opts,
        index=current_idx,
    )

    if selected_run_opt != "(New Autonomous Run)":
        st.session_state["active_run_id"] = selected_run_opt

    # Golden Run button
    golden_dir = RUNS_DIR / "golden"
    if golden_dir.is_dir():
        if st.button("🌟 Load Golden Run (Replay)", use_container_width=True):
            st.session_state["active_run_id"] = "golden"
            st.rerun()

    st.divider()
    if st.button("🔄 Regenerate Analysis & Tests", use_container_width=True):
        if not FIRMWARE_SRC_FILE.is_file():
            st.error("Firmware source file not found.")
        else:
            with st.spinner("Analyzing firmware & generating tests..."):
                source_code = FIRMWARE_SRC_FILE.read_text(encoding="utf-8")
                analysis = analyze_firmware(source_code)
                tests = generate_tests(analysis, source_code)
                dev_dir = RUNS_DIR / "dev"
                dev_dir.mkdir(parents=True, exist_ok=True)
                (dev_dir / "analysis.json").write_text(
                    analysis.model_dump_json(indent=2), encoding="utf-8"
                )
                (dev_dir / "tests.json").write_text(
                    TestList(tests=tests).model_dump_json(indent=2),
                    encoding="utf-8",
                )
                st.session_state["active_run_id"] = "dev"
                st.success(
                    f"Generated {len(analysis.spec_rules)} rules & {len(tests)} tests!"
                )
                st.rerun()


# Determine Active Run Directory
active_run_id = st.session_state.get("active_run_id", "dev")
active_run_dir = RUNS_DIR / active_run_id
if not active_run_dir.is_dir():
    active_run_dir = RUNS_DIR / "dev"


# Helper to load JSON files from active run directory
def load_run_file(filename: str):
    p = active_run_dir / filename
    if not p.is_file():
        # Fallback to dev dir if file missing in active run
        dev_p = RUNS_DIR / "dev" / filename
        if dev_p.is_file():
            p = dev_p
        else:
            return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


# ==========================================
# Main Header & 5 Tabs
# ==========================================
st.title("⚡ FirmAgent")
st.caption(
    f"Active Workspace: `{active_run_dir.name}` | Target: `firmware/fan_controller`"
)

if active_run_dir.name == "golden":
    st.info(
        "🌟 **Offline Replay Mode: Viewing Golden Run.** Fully offline demonstration dataset with verified 14 tests and 3 planted bug findings."
    )

tab_run, tab_analysis, tab_tests, tab_live, tab_report = st.tabs(
    ["🚀 Run", "🔍 Analysis", "📋 Tests", "⚡ Live Execution", "📊 Report"]
)


# ==========================================
# Tab 1: Run (One-Click Autonomous Pipeline)
# ==========================================
with tab_run:
    st.subheader("Autonomous Testing Pipeline")
    st.markdown(
        "Execute the end-to-end testing loop: compile firmware, run tests in virtual Wokwi hardware simulation, diagnose root-cause bugs with Gemini, and compile reports."
    )

    col_btn, col_info = st.columns([1, 2])
    with col_btn:
        start_run = st.button(
            "🚀 Run Autonomous Test",
            type="primary",
            use_container_width=True,
        )

    # Progress Stepper Display
    stepper_cols = st.columns(5)
    steps_labels = [
        "1. Build & Spec",
        "2. Test Generation",
        "3. Wokwi Simulation",
        "4. Root Cause",
        "5. Final Report",
    ]
    for col, lbl in zip(stepper_cols, steps_labels):
        with col:
            st.info(f"**{lbl}**")

    progress_placeholder = st.empty()
    status_placeholder = st.empty()

    if start_run:
        status_placeholder.info(
            "Starting autonomous execution pipeline. Please wait..."
        )
        progress_bar = progress_placeholder.progress(5)

        # 1. Ensure Analysis and Tests exist
        dev_dir = RUNS_DIR / "dev"
        dev_dir.mkdir(parents=True, exist_ok=True)
        if (
            not (dev_dir / "analysis.json").is_file()
            or not (dev_dir / "tests.json").is_file()
        ):
            status_placeholder.text("Analyzing firmware & generating tests...")
            progress_bar.progress(15)
            source_code = FIRMWARE_SRC_FILE.read_text(encoding="utf-8")
            analysis = analyze_firmware(source_code)
            tests = generate_tests(analysis, source_code)
            (dev_dir / "analysis.json").write_text(
                analysis.model_dump_json(indent=2), encoding="utf-8"
            )
            (dev_dir / "tests.json").write_text(
                TestList(tests=tests).model_dump_json(indent=2),
                encoding="utf-8",
            )

        # 2. Run All Tests in Wokwi Simulator
        status_placeholder.text("Simulating tests in Wokwi virtual hardware...")
        progress_bar.progress(30)

        def on_sim_event(ev):
            if ev.get("type") == "test_finished":
                idx = ev.get("index", 1)
                tot = ev.get("total", 1)
                pct = int(30 + (idx / tot) * 45)
                progress_bar.progress(min(pct, 75))
                status_placeholder.text(
                    f"Simulating [{idx}/{tot}] {ev.get('test_id')} - {ev.get('result').status}"
                )
            elif ev.get("type") == "followup_started":
                status_placeholder.text(
                    f"🔁 Autonomous follow-up round {ev.get('round')}: generated {ev.get('count')} probing tests..."
                )

        manifest = run_all(
            source_dir=dev_dir,
            firmware_dir=FIRMWARE_DIR,
            on_event=on_sim_event,
            enable_followup=True,
        )
        new_run_dir = RUNS_DIR / manifest.run_id

        # 3. Root Cause Analysis
        status_placeholder.text("Diagnosing root-cause bugs with Gemini...")
        progress_bar.progress(80)
        try:
            run_root_cause(run_dir=new_run_dir)
        except Exception as exc:
            st.warning(f"Root cause analysis warning: {exc}")

        # 4. Generate Reports
        status_placeholder.text("Compiling Markdown and HTML reports...")
        progress_bar.progress(95)
        try:
            generate_reports(run_dir=new_run_dir)
        except Exception as exc:
            st.warning(f"Report generator warning: {exc}")

        progress_bar.progress(100)
        status_placeholder.success(
            f"✅ Autonomous run complete! Run ID: `{manifest.run_id}` | "
            f"Passed: {manifest.passed} | Failed: {manifest.failed} | Errors: {manifest.errors}"
        )
        st.session_state["active_run_id"] = manifest.run_id
        st.rerun()

    # If run directory exists, show summary card
    manifest_data = load_run_file("manifest.json")
    if manifest_data:
        st.divider()
        st.subheader(f"Current Run Status: `{active_run_dir.name}`")
        m = RunManifest.model_validate(manifest_data)
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Total Tests", m.total_tests)
        c2.metric("Passed", f"✅ {m.passed}")
        c3.metric("Failed", f"❌ {m.failed}")
        c4.metric("Errors", f"⚠ {m.errors}")
        c5.metric("Status", m.status.upper())


# ==========================================
# Tab 2: Analysis
# ==========================================
with tab_analysis:
    analysis_data = load_run_file("analysis.json")
    if not analysis_data:
        st.info("No analysis data available. Run the pipeline in Tab 1.")
    else:
        try:
            analysis = FirmwareAnalysis.model_validate(analysis_data)
            st.subheader("Firmware Analysis Profile")
            st.write(analysis.summary)

            c1, c2, c3, c4 = st.columns(4)
            with c1:
                st.markdown("**Inputs**")
                for i in analysis.inputs:
                    st.markdown(f"- `{i}`")
            with c2:
                st.markdown("**Outputs**")
                for o in analysis.outputs:
                    st.markdown(f"- `{o}`")
            with c3:
                st.markdown("**Thresholds & Constants**")
                for k, v in analysis.constants.items():
                    st.markdown(f"- `{k}`: `{v}`")
            with c4:
                st.markdown("**States**")
                for s in analysis.states:
                    st.markdown(f"- `{s}`")

            st.markdown("#### Specification Rules (Oracle)")
            rules_list = []
            for r in analysis.spec_rules:
                lines_str = (
                    ", ".join(map(str, r.source_lines))
                    if r.source_lines
                    else "None"
                )
                rules_list.append(
                    {
                        "ID": r.id,
                        "Rule Specification": r.text,
                        "Confidence": r.confidence,
                        "Source Lines": lines_str,
                    }
                )
            st.dataframe(
                pd.DataFrame(rules_list),
                use_container_width=True,
                hide_index=True,
            )

            st.markdown("#### Identified Risk Areas")
            for risk in analysis.risk_areas:
                st.markdown(f"⚠️ **{risk}**")
        except Exception as exc:
            st.error(f"Error displaying analysis: {exc}")


# ==========================================
# Tab 3: Tests
# ==========================================
with tab_tests:
    tests_data = load_run_file("tests.json")
    if not tests_data:
        st.info("No test cases found. Run the pipeline in Tab 1.")
    else:
        try:
            raw_list = (
                tests_data.get("tests", [])
                if isinstance(tests_data, dict)
                else tests_data
            )
            tests = [TestCase.model_validate(t) for t in raw_list]
            st.subheader(f"Generated Test Suite ({len(tests)} Tests)")

            categories = sorted(list({t.category for t in tests}))
            for cat in categories:
                cat_tests = [t for t in tests if t.category == cat]
                with st.expander(
                    f"📁 {cat.upper()} ({len(cat_tests)} tests)", expanded=True
                ):
                    rows = []
                    for t in cat_tests:
                        rows.append(
                            {
                                "ID": t.id,
                                "Name": t.name,
                                "Sensor": t.sensor,
                                "Steps (Plain Language)": format_steps_plain(t),
                                "Expected Serial": ", ".join(
                                    e.serial_contains for e in t.expect
                                ),
                                "Rationale": t.rationale,
                            }
                        )
                    st.dataframe(
                        pd.DataFrame(rows),
                        use_container_width=True,
                        hide_index=True,
                    )
        except Exception as exc:
            st.error(f"Error displaying tests: {exc}")


# ==========================================
# Tab 4: Live Execution
# ==========================================
with tab_live:
    tests_data = load_run_file("tests.json")
    results_data = load_run_file("results.json")

    if not tests_data or not results_data:
        st.info(
            "Simulation results not yet available. Run the autonomous test in Tab 1."
        )
    else:
        raw_tests = (
            tests_data.get("tests", [])
            if isinstance(tests_data, dict)
            else tests_data
        )
        tests = [TestCase.model_validate(t) for t in raw_tests]
        results = [TestResult.model_validate(r) for r in results_data]
        res_map = {r.test_id: r for r in results}

        # Master-Detail Layout
        col_list, col_detail = st.columns([1, 2])

        with col_list:
            st.markdown("### Tests")
            filter_failures = st.checkbox("Only show failures (FAIL / ERROR)")

            labels = []
            test_lookup = {}
            for t in tests:
                res = res_map.get(t.id)
                status_str = res.status if res else "NOT_RUN"
                if (
                    filter_failures
                    and res
                    and res.status not in ("FAIL", "ERROR")
                ):
                    continue
                icon = (
                    "✅"
                    if status_str == "PASS"
                    else (
                        "❌"
                        if status_str == "FAIL"
                        else ("⚠" if status_str == "ERROR" else "⏳")
                    )
                )
                followup_tag = (
                    " [🔁 FOLLOW-UP]"
                    if (t.category == "followup" or t.round > 0)
                    else ""
                )
                label = f"{icon} {t.id} - {t.name}{followup_tag}"
                labels.append(label)
                test_lookup[label] = t

            if not labels:
                st.caption("No matching tests.")
                selected_label = None
            else:
                selected_label = st.radio(
                    "Select a test to inspect",
                    options=labels,
                    label_visibility="collapsed",
                )

        with col_detail:
            if selected_label and selected_label in test_lookup:
                sel_test = test_lookup[selected_label]
                sel_res = res_map.get(sel_test.id)

                st.markdown(f"### {sel_test.id}: {sel_test.name}")
                st.caption(
                    f"Category: `{sel_test.category}` | Sensor: `{sel_test.sensor}` | Rationale: {sel_test.rationale}"
                )

                if sel_res:
                    # Status banner
                    if sel_res.status == "PASS":
                        st.success(
                            f"**✅ PASS** (Duration: {sel_res.duration_s:.1f}s)"
                        )
                    elif sel_res.status == "FAIL":
                        st.error(
                            f"**❌ FAIL** — Expectation not satisfied (Duration: {sel_res.duration_s:.1f}s, Exit: {sel_res.exit_code})"
                        )
                    else:
                        st.warning(
                            f"**⚠ ERROR** — Simulator execution fault (Exit: {sel_res.exit_code})"
                        )

                    # Expected vs Observed
                    c_exp, c_obs = st.columns(2)
                    with c_exp:
                        st.markdown("**Expected Serial Output:**")
                        for exp in sel_res.expected:
                            st.markdown(f"- `{exp}`")
                    with c_obs:
                        st.markdown("**Observed Firmware Output:**")
                        collapsed = collapse_firmware_lines(
                            sel_res.observed_lines
                        )
                        if collapsed:
                            for line in collapsed:
                                st.markdown(f"- `{line}`")
                        else:
                            st.caption("No firmware output observed.")

                    if sel_res.missing_expected:
                        st.error(
                            f"Missing Expected Text: {', '.join(f'`{m}`' for m in sel_res.missing_expected)}"
                        )
                    if sel_res.violated_must_not:
                        st.error(
                            f"Violated Forbidden Strings: {', '.join(f'`{v}`' for v in sel_res.violated_must_not)}"
                        )

                    # Expandable raw serial log
                    with st.expander("📜 Raw Simulator Serial Log"):
                        st.code(
                            sel_res.serial_log or "(no log)", language="text"
                        )

                # Re-run button for this test
                if st.button(f"🔄 Re-run {sel_test.id} in Simulator"):
                    with st.spinner(f"Running {sel_test.id}..."):
                        rerun_res = run_test(
                            test=sel_test,
                            firmware_dir=FIRMWARE_DIR,
                            run_dir=active_run_dir,
                        )
                        # Update results on disk
                        res_map[sel_test.id] = rerun_res
                        new_results = [
                            res_map.get(t.id, rerun_res) for t in tests
                        ]
                        (active_run_dir / "results.json").write_text(
                            json.dumps(
                                [r.model_dump() for r in new_results], indent=2
                            ),
                            encoding="utf-8",
                        )
                        st.success(f"Re-run complete: {rerun_res.status}")
                        st.rerun()


# ==========================================
# Tab 5: Report
# ==========================================
with tab_report:
    manifest_data = load_run_file("manifest.json")
    results_data = load_run_file("results.json")
    tests_data = load_run_file("tests.json")
    findings_data = load_run_file("findings.json")

    if not manifest_data or not results_data:
        st.info("No report data available. Run the autonomous test in Tab 1.")
    else:
        manifest = RunManifest.model_validate(manifest_data)
        raw_tests = (
            tests_data.get("tests", [])
            if isinstance(tests_data, dict)
            else (tests_data or [])
        )
        tests = [TestCase.model_validate(t) for t in raw_tests]
        results = [TestResult.model_validate(r) for r in results_data]
        findings = (
            [Finding.model_validate(f) for f in findings_data]
            if findings_data
            else []
        )

        st.subheader("Autonomous Test & Defect Report")

        # Metric Cards
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Tests Executed", manifest.total_tests)
        pass_rate = (
            f"{(manifest.passed / manifest.total_tests * 100):.0f}%"
            if manifest.total_tests
            else "0%"
        )
        c2.metric("Passed", manifest.passed, delta=pass_rate)
        c3.metric("Failed", manifest.failed)
        c4.metric("Errors", manifest.errors)
        c5.metric("Defects Identified", len(findings))

        st.divider()

        # Root Cause / Planted Bugs Cards
        st.markdown("### 🐛 Root-Cause Bug Findings")
        if not findings:
            st.success("✓ No software defects or failures detected in this run.")
        else:
            for f in findings:
                sev_icon = (
                    "🔴 HIGH"
                    if f.severity == "high"
                    else ("🟡 MEDIUM" if f.severity == "medium" else "🔵 LOW")
                )
                with st.expander(
                    f"[{sev_icon}] {f.id}: {f.title}", expanded=True
                ):
                    st.markdown(
                        f"**Spec Rule Reference**: `{f.spec_ref or 'General'}` | **Failed Tests**: {', '.join(f'`{tid}`' for tid in f.failed_tests)}"
                    )
                    c_e, c_o = st.columns(2)
                    c_e.info(f"**Expected:**\n{f.expected}")
                    c_o.error(f"**Observed:**\n{f.observed}")

                    st.markdown(f"**Likely Root Cause:**\n{f.likely_cause}")
                    if f.suspect_lines:
                        st.markdown(
                            f"**Suspect Source Lines:** `{f.suspect_lines}`"
                        )
                    st.markdown("**Suggested Code Fix:**")
                    st.code(f.suggested_fix, language="cpp")

        st.divider()

        # Download Buttons
        st.markdown("### 📥 Download Reports")
        report_md_path = active_run_dir / "report.md"
        report_html_path = active_run_dir / "report.html"

        # Generate on demand if missing
        if not report_md_path.is_file() or not report_html_path.is_file():
            try:
                generate_reports(active_run_dir)
            except Exception:
                pass

        col_dl1, col_dl2 = st.columns(2)
        if report_md_path.is_file():
            with col_dl1:
                st.download_button(
                    label="📄 Download Markdown Report (report.md)",
                    data=report_md_path.read_text(encoding="utf-8"),
                    file_name=f"report_{manifest.run_id}.md",
                    mime="text/markdown",
                    use_container_width=True,
                )
        if report_html_path.is_file():
            with col_dl2:
                st.download_button(
                    label="🌐 Download Standalone HTML Report (report.html)",
                    data=report_html_path.read_text(encoding="utf-8"),
                    file_name=f"report_{manifest.run_id}.html",
                    mime="text/html",
                    use_container_width=True,
                )
