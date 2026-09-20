"""FirmAgent — Streamlit Application Entrypoint."""

import sys
from pathlib import Path
import json
import pandas as pd
import streamlit as st

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.analyzer import analyze_firmware
from agent.generator import generate_tests
from agent.models import FirmwareAnalysis, TestCase, TestList, TestResult
from agent.preflight import run_preflight
from agent.runner import run_test

st.set_page_config(
    page_title="FirmAgent",
    page_icon="⚡",
    layout="wide",
)

DEV_DIR = PROJECT_ROOT / "runs" / "dev"
ANALYSIS_FILE = DEV_DIR / "analysis.json"
TESTS_FILE = DEV_DIR / "tests.json"
FIRMWARE_SRC_FILE = PROJECT_ROOT / "firmware" / "fan_controller" / "src" / "main.cpp"


def collapse_observed_lines(lines: list[str]) -> list[str]:
    """Format and collapse consecutive identical observed lines with counts.

    Example:
        ['[DATA] temp=30.0 fan=OFF', '[DATA] temp=30.0 fan=OFF']
        -> ['temp=30.0 fan=OFF (x2)']
    """
    if not lines:
        return []

    cleaned = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[DATA] "):
            stripped = stripped[7:].strip()
        cleaned.append(stripped)

    collapsed = []
    current_line = cleaned[0]
    count = 1
    for line in cleaned[1:]:
        if line == current_line:
            count += 1
        else:
            if count > 1:
                collapsed.append(f"{current_line} (x{count})")
            else:
                collapsed.append(current_line)
            current_line = line
            count = 1
    if count > 1:
        collapsed.append(f"{current_line} (x{count})")
    else:
        collapsed.append(current_line)
    return collapsed


def format_steps_plain(test: TestCase) -> str:
    """Format test steps into human-readable plain language."""
    if test.sensor == "disconnected":
        return "Sensor wire removed (wait for fail-safe)"
    if not test.steps:
        return "No input changes"
    parts = []
    for s in test.steps:
        if s.set_temp is not None:
            parts.append(f"Set temp {s.set_temp:.1f}°C")
        else:
            parts.append("Maintain temperature")
    return " ➔ ".join(parts)


def run_regeneration_pipeline() -> None:
    """Execute firmware analysis and test generation pipeline."""
    if not FIRMWARE_SRC_FILE.is_file():
        st.sidebar.error(f"Firmware source not found at {FIRMWARE_SRC_FILE}")
        return

    source_code = FIRMWARE_SRC_FILE.read_text(encoding="utf-8")
    DEV_DIR.mkdir(parents=True, exist_ok=True)

    with st.spinner("Analyzing firmware specification and code..."):
        try:
            analysis = analyze_firmware(source_code)
            ANALYSIS_FILE.write_text(
                analysis.model_dump_json(indent=2), encoding="utf-8"
            )
        except Exception as exc:
            st.sidebar.error(f"Analysis failed: {exc}")
            return

    with st.spinner("Generating targeted test suite..."):
        try:
            tests = generate_tests(analysis, source_code)
            TESTS_FILE.write_text(
                TestList(tests=tests).model_dump_json(indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            st.sidebar.error(f"Test generation failed: {exc}")
            return

    st.sidebar.success(
        f"Generated {len(analysis.spec_rules)} rules & {len(tests)} tests!"
    )
    st.rerun()


# ==========================================
# Sidebar: Preflight & Pipeline Actions
# ==========================================
with st.sidebar:
    st.header("Preflight")
    checks = run_preflight()
    for check in checks:
        if check.ok:
            st.markdown(f"✅ **{check.name}** (`{check.detail}`)")
        else:
            st.markdown(f"❌ **{check.name}** (`{check.detail}`)")
            if check.hint:
                st.caption(f"💡 {check.hint}")

    st.divider()
    st.subheader("Pipeline Actions")
    if st.button("🔄 Regenerate analysis & tests", use_container_width=True):
        run_regeneration_pipeline()


# ==========================================
# Main App Header & Navigation
# ==========================================
st.title("⚡ FirmAgent")
st.caption(
    "Autonomous Embedded Firmware Testing Agent — Virtual Hardware Simulation in Wokwi"
)

tab_analysis, tab_tests, tab_run = st.tabs(
    ["📋 Analysis", "🧪 Tests", "▶ Run"]
)

# ==========================================
# Tab 1: Analysis
# ==========================================
with tab_analysis:
    if not ANALYSIS_FILE.is_file():
        st.info(
            "ℹ️ No analysis file found (`runs/dev/analysis.json`). "
            "Click **Regenerate analysis & tests** in the sidebar or run `scripts/analyze_and_generate.py`."
        )
    else:
        try:
            analysis = FirmwareAnalysis.model_validate_json(
                ANALYSIS_FILE.read_text(encoding="utf-8")
            )

            st.subheader("Summary")
            st.info(analysis.summary)

            st.markdown("#### Hardware & Technical Profile")
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.markdown("**Inputs**")
                for item in analysis.inputs:
                    st.markdown(f"- {item}")
            with col2:
                st.markdown("**Outputs**")
                for item in analysis.outputs:
                    st.markdown(f"- {item}")
            with col3:
                st.markdown("**Constants / Thresholds**")
                for k, v in analysis.constants.items():
                    st.markdown(f"- `{k}`: `{v}`")
            with col4:
                st.markdown("**States & Handling**")
                for item in analysis.states:
                    st.markdown(f"- `{item}`")

            st.markdown("#### Specification Rules")
            if analysis.spec_rules:
                rules_data = []
                for r in analysis.spec_rules:
                    lines_str = (
                        ", ".join(map(str, r.source_lines))
                        if r.source_lines
                        else "None"
                    )
                    rules_data.append(
                        {
                            "ID": r.id,
                            "Specification Rule": r.text,
                            "Confidence": r.confidence,
                            "Source Lines": lines_str,
                        }
                    )
                st.dataframe(
                    pd.DataFrame(rules_data),
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.caption("No specification rules extracted.")

            st.markdown("#### Risk Areas")
            if analysis.risk_areas:
                for risk in analysis.risk_areas:
                    st.markdown(f"⚠️ **{risk}**")
            else:
                st.caption("No risk areas identified.")
        except Exception as exc:
            st.error(f"Error loading analysis: {exc}")

# ==========================================
# Tab 2: Tests
# ==========================================
with tab_tests:
    if not TESTS_FILE.is_file():
        st.info(
            "ℹ️ No tests file found (`runs/dev/tests.json`). "
            "Click **Regenerate analysis & tests** in the sidebar or run `scripts/analyze_and_generate.py`."
        )
    else:
        try:
            test_list = TestList.model_validate_json(
                TESTS_FILE.read_text(encoding="utf-8")
            )
            st.subheader(f"Generated Test Suite ({len(test_list.tests)} Tests)")

            categories = sorted(list({t.category for t in test_list.tests}))
            for cat in categories:
                cat_tests = [t for t in test_list.tests if t.category == cat]
                with st.expander(
                    f"📂 {cat.upper()} ({len(cat_tests)} tests)", expanded=True
                ):
                    table_rows = []
                    for t in cat_tests:
                        table_rows.append(
                            {
                                "ID": t.id,
                                "Name": t.name,
                                "Sensor": t.sensor,
                                "Steps (Plain Words)": format_steps_plain(t),
                                "Expected Serial": ", ".join(
                                    e.serial_contains for e in t.expect
                                ),
                                "Rationale": t.rationale,
                            }
                        )
                    st.dataframe(
                        pd.DataFrame(table_rows),
                        use_container_width=True,
                        hide_index=True,
                    )
        except Exception as exc:
            st.error(f"Error loading tests: {exc}")

# ==========================================
# Tab 3: Run
# ==========================================
with tab_run:
    if not TESTS_FILE.is_file():
        st.info("ℹ️ Tests file missing. Please generate tests first.")
    else:
        try:
            test_list = TestList.model_validate_json(
                TESTS_FILE.read_text(encoding="utf-8")
            )
            test_map = {
                f"{t.id} - {t.name} [{t.category.upper()}]": t
                for t in test_list.tests
            }

            st.subheader("Select and Execute Test in Virtual Simulator")
            col_sel, col_btn = st.columns([3, 1])
            with col_sel:
                selected_label = st.selectbox(
                    "Choose Test",
                    options=list(test_map.keys()),
                    label_visibility="collapsed",
                )
            selected_test = test_map[selected_label]

            with col_btn:
                run_clicked = st.button(
                    "▶ Run test in simulator",
                    type="primary",
                    use_container_width=True,
                )

            # Selected test details card
            st.caption(
                f"**Selected Test**: `{selected_test.id}` | Category: `{selected_test.category}` | Sensor: `{selected_test.sensor}`"
            )
            st.markdown(f"**Steps**: {format_steps_plain(selected_test)}")
            st.markdown(
                f"**Expected**: {', '.join(f'`{e.serial_contains}`' for e in selected_test.expect)}"
            )

            if run_clicked:
                firmware_dir = PROJECT_ROOT / "firmware" / "fan_controller"
                run_dir = PROJECT_ROOT / "runs" / "dev"
                with st.spinner(
                    f"Running test {selected_test.id} in Wokwi simulator..."
                ):
                    result = run_test(
                        test=selected_test,
                        firmware_dir=firmware_dir,
                        run_dir=run_dir,
                    )
                    st.session_state["last_result"] = result
                    st.session_state["last_result_test_id"] = selected_test.id

            if "last_result" in st.session_state:
                result: TestResult = st.session_state["last_result"]
                st.divider()

                # Status Banner
                if result.status == "PASS":
                    st.success(
                        f"### ✅ PASS — Test {result.test_id} Passed Successfully"
                    )
                elif result.status == "FAIL":
                    st.error(
                        f"### ❌ FAIL — Test {result.test_id} Expectation Not Met (Exit Code: {result.exit_code})"
                    )
                else:
                    st.warning(
                        f"### ⚠ ERROR — Test {result.test_id} Simulator Error (Exit Code: {result.exit_code})"
                    )

                # Metrics row
                m1, m2, m3 = st.columns(3)
                status_icon = (
                    "✅ PASS"
                    if result.status == "PASS"
                    else ("❌ FAIL" if result.status == "FAIL" else "⚠ ERROR")
                )
                m1.metric("Status", status_icon)
                m2.metric("Duration", f"{result.duration_s:.2f} s")
                m3.metric("Exit Code", f"{result.exit_code}")

                # Expected vs Observed
                res_col1, res_col2 = st.columns(2)
                with res_col1:
                    st.markdown("#### 🎯 Expected Strings")
                    for exp in result.expected:
                        st.markdown(f"- `{exp}`")

                with res_col2:
                    st.markdown("#### 📡 Observed Protocol Lines")
                    collapsed = collapse_observed_lines(result.observed_lines)
                    if collapsed:
                        for obs in collapsed:
                            st.markdown(f"- `{obs}`")
                    else:
                        st.caption("No matching protocol lines captured.")

                # Serial Log in code block
                with st.expander("📜 Full Wokwi Serial Log", expanded=True):
                    st.code(
                        result.serial_log or "(no serial log captured)",
                        language="text",
                    )

                if result.error_message:
                    st.error(f"Error Detail: {result.error_message}")
        except Exception as exc:
            st.error(f"Error running test: {exc}")
