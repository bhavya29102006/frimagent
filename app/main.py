"""FirmAgent — Streamlit Application Entrypoint.

5-tab UI adhering to docs/04_UI_UX_BRIEF.md, docs/03_APP_FLOW.md, and TASK-021:
1. Run: Autonomous one-click test execution with progress stepper, live spinner, stop button, summary banner.
2. Analysis: Firmware analysis, spec rules oracle, and risk areas with friendly empty states.
3. Tests: Generated test suite grouped by category with plain-words steps.
4. Live Execution: Master-detail test inspector, serial log viewer, re-run single test, and ERROR warning rows.
5. Report: Executive metric cards, coverage matrix, bug findings with suggested fixes, and downloads.
"""

from datetime import datetime
import hashlib
import html
import json
from pathlib import Path
import socket
import sys
import threading
import time
import traceback
from typing import Any, Optional
import pandas as pd
import streamlit as st

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.analyzer import analyze_firmware
from agent.compare import format_comparison_summary, update_reports_with_fix
from agent.coverage import compute_coverage, RULE_DESCRIPTIONS
from agent.evaluator import collapse_firmware_lines
from agent.fixer import (
    load_fix_attempt,
    run_autofix,
    save_golden_fix_attempt,
    verify_fix,
)
from agent.generator import generate_tests
from agent.models import (
    Finding,
    FirmwareAnalysis,
    FixAttempt,
    PatchCheck,
    PatchHunk,
    PatchProposal,
    PatchValidation,
    RunManifest,
    TestCase,
    TestList,
    TestResult,
)
from agent.orchestrator import run_all
from agent.patcher import (
    apply_to_original,
    render_diff,
    render_diff_rows,
    revert_original,
)
from agent.preflight import run_preflight
from agent.reporter import generate_reports
from agent.rootcause import run_root_cause
from agent.runner import run_test
from agent.syntax_fixer import (
    auto_fix_syntax_errors,
    check_firmware_syntax,
    restore_firmware_backup,
)
from agent.db import (
    delete_firmware_cache,
    get_db_stats,
    get_firmware_cache,
    save_firmware_cache,
)
from agent.simulators.registry import (
    detect_firmware_language,
    get_simulator,
    list_available_simulators,
)

st.set_page_config(
    page_title="FirmAgent — Autonomous Firmware Testing",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom CSS for dark technical styling, accessible badges, and monospace >=13px logs
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
    .badge-stop { background: rgba(148, 163, 184, 0.2); color: #94A3B8; border: 1px solid #94A3B8; }

    /* Enforce monospace font and at least 13px for all serial logs and code blocks */
    pre, code, .stCodeBlock, .stCodeBlock code, textarea {
        font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, Courier, monospace !important;
        font-size: 13px !important;
        line-height: 1.5 !important;
    }
    </style>
""",
    unsafe_allow_html=True,
)

FIRMWARE_BASE_DIR = PROJECT_ROOT / "firmware"
RUNS_DIR = PROJECT_ROOT / "runs"

FIRMWARE_PRESETS: dict[str, dict[str, Any]] = {
    "fan_controller": {
        "title": "🌡️ fan_controller (Arduino Uno + DHT22 Fan)",
        "desc": "Arduino Uno thermostat fan with hysteresis & sensor disconnect fail-safe.",
        "lang": "cpp",
        "default_sim": "wokwi",
    },
    "incubator_controller": {
        "title": "🐣 incubator_controller (Arduino Uno + Heater Relay)",
        "desc": "Medical/poultry incubator maintaining 37.0°C with 40°C overheat alarm.",
        "lang": "cpp",
        "default_sim": "wokwi",
    },
    "smart_door_lock": {
        "title": "🔐 smart_door_lock (Arduino Uno + PIN Access Control)",
        "desc": "Security keypad lock with master PIN, buzzer, LEDs & 3-attempt lockout.",
        "lang": "cpp",
        "default_sim": "virtual_mock",
    },
    "water_tank_monitor": {
        "title": "💧 water_tank_monitor (Pure Embedded C)",
        "desc": "Industrial reservoir level monitor with inlet valve, pump cut-off & overflow alarm.",
        "lang": "c",
        "default_sim": "native_c",
    },
    "iot_weather_node": {
        "title": "☁️ iot_weather_node (MicroPython)",
        "desc": "Ambient weather telemetry node measuring temp, ventilation & freeze protection.",
        "lang": "python",
        "default_sim": "python_sim",
    },
    "broken_syntax_demo": {
        "title": "🛠️ broken_syntax_demo (Arduino C++: Test 1-Click AI Auto-Repair)",
        "desc": "Arduino C++ with intentional syntax errors (missing semicolons) for live repair demo.",
        "lang": "cpp",
        "default_sim": "virtual_mock",
    },
    "custom_uploaded": {
        "title": "📁 custom_uploaded (Active User Upload Slot)",
        "desc": "Custom workspace slot for uploading and testing your own embedded C, C++, or Python firmware.",
        "lang": "cpp",
        "default_sim": "virtual_mock",
    },
}

SAMPLE_DIR = PROJECT_ROOT / "sample_firmwares"


def get_local_sample_firmwares() -> dict[str, Path]:
    """Scan sample_firmwares/ directory for available sample files."""
    if not SAMPLE_DIR.is_dir():
        return {}
    samples = {}
    for f in sorted(SAMPLE_DIR.iterdir()):
        if f.is_file() and f.suffix in (".cpp", ".c", ".py", ".ino"):
            samples[f.name] = f
    return samples


def get_available_firmwares() -> list[str]:
    """Scan firmware/ directory for available firmware projects."""
    if not FIRMWARE_BASE_DIR.is_dir():
        return ["fan_controller"]
    found = []
    # Known presets in order
    for name in FIRMWARE_PRESETS:
        if (FIRMWARE_BASE_DIR / name).is_dir():
            found.append(name)
    # Any custom folders added by user
    for d in sorted(FIRMWARE_BASE_DIR.iterdir()):
        if d.is_dir() and not d.name.startswith(".") and d.name not in found:
            found.append(d.name)
    return found or ["fan_controller"]


def find_firmware_src_file(fw_dir: Path) -> Path:
    """Locate primary source code file (.cpp, .c, .py, .ino) in firmware directory."""
    candidates = [
        fw_dir / "src" / "main.cpp",
        fw_dir / "src" / "main.c",
        fw_dir / "src" / "main.py",
        fw_dir / "src" / "main.ino",
        fw_dir / "main.cpp",
        fw_dir / "main.c",
        fw_dir / "main.py",
        fw_dir / "main.ino",
    ]
    for c in candidates:
        if c.is_file():
            return c
    src_dir = fw_dir / "src"
    if src_dir.is_dir():
        for ext in ("*.cpp", "*.c", "*.py", "*.ino"):
            matches = list(src_dir.glob(ext))
            if matches:
                return matches[0]
    for ext in ("*.cpp", "*.c", "*.py", "*.ino"):
        matches = list(fw_dir.glob(ext))
        if matches:
            return matches[0]
    return fw_dir / "src" / "main.cpp"


# Resolve active target firmware dynamically from session_state
_active_fw_name = st.session_state.get("target_firmware_choice", "fan_controller")
FIRMWARE_DIR = FIRMWARE_BASE_DIR / _active_fw_name
if not FIRMWARE_DIR.is_dir():
    FIRMWARE_DIR = FIRMWARE_BASE_DIR / "fan_controller"
FIRMWARE_SRC_FILE = find_firmware_src_file(FIRMWARE_DIR)



def is_internet_available(host: str = "8.8.8.8", port: int = 53, timeout: float = 1.5) -> bool:
    """Quick check for internet connectivity without throwing unhandled exceptions."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect((host, port))
        s.close()
        return True
    except Exception:
        return False


def log_ui_error(run_id: str, action: str, exc: Exception) -> Path:
    """Log full technical exception traceback to runs/<run_id>/error.log."""
    err_dir = RUNS_DIR / run_id
    err_dir.mkdir(parents=True, exist_ok=True)
    log_file = err_dir / "error.log"
    try:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().isoformat()}] Error during '{action}':\n")
            f.write(traceback.format_exc())
            f.write("\n" + "=" * 60 + "\n")
    except Exception:
        pass
    return log_file


def classify_error(exc: Exception) -> tuple[str, str]:
    """Convert an exception into a user-friendly (cause, hint) tuple with no traceback."""
    msg = str(exc)
    err_type = type(exc).__name__

    if "429" in msg or "RESOURCE_EXHAUSTED" in msg or "rate limit" in msg.lower():
        return (
            "Gemini API rate limit reached (429)",
            "The model quota is temporarily exhausted. Please wait a few seconds before retrying.",
        )
    if "503" in msg or "UNAVAILABLE" in msg or "overloaded" in msg.lower():
        return (
            "Gemini service temporarily unavailable (503)",
            "Google AI service is experiencing high load. FirmAgent will retry automatically, or you can try again shortly.",
        )
    if "API_KEY_INVALID" in msg or "API key not valid" in msg or "GEMINI_API_KEY" in msg:
        return (
            "Missing or invalid Gemini API key",
            "Please verify that GEMINI_API_KEY is correctly set in your .env file.",
        )
    if "WOKWI_CLI_TOKEN" in msg or ("token" in msg.lower() and "wokwi" in msg.lower()):
        return (
            "Wokwi CLI authentication error",
            "Ensure WOKWI_CLI_TOKEN is set in your .env file from wokwi.com/ci.",
        )
    if "wokwi-cli" in msg.lower() or ("FileNotFoundError" in err_type and "wokwi" in msg.lower()):
        return (
            "Wokwi CLI executable not found",
            "Install Wokwi CLI or configure WOKWI_CLI_PATH in your .env file.",
        )
    if "ConnectionError" in err_type or "socket" in msg.lower() or "Failed to establish a new connection" in msg:
        return (
            "No internet connection detected",
            "You are offline. Switch to Replay mode using 'Load golden run' in the sidebar.",
        )
    return (
        f"{err_type}: {msg[:100]}",
        "Technical diagnostics have been written to error.log in the active run folder.",
    )


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


def run_autonomous_pipeline(run_id: str, shared_state: dict[str, Any], stop_event: threading.Event) -> None:
    """Run the 5-step testing pipeline in a background thread with live state reporting."""
    try:
        fw_dir = shared_state.get("firmware_dir", FIRMWARE_DIR)
        fw_src = shared_state.get("firmware_src_file", FIRMWARE_SRC_FILE)

        shared_state["status"] = f"1. Build & Spec: Checking firmware source for {fw_dir.name}..."
        shared_state["progress"] = 10

        dev_dir = RUNS_DIR / "dev"
        dev_dir.mkdir(parents=True, exist_ok=True)

        # 1. Ensure Analysis and Tests exist (Check SQLite Database Cache first!)
        source_code = fw_src.read_text(encoding="utf-8")
        current_hash = hashlib.sha256(source_code.encode("utf-8")).hexdigest()
        cached_entry = get_firmware_cache(source_code)

        if cached_entry is not None:
            shared_state["status"] = f"1. Backend DB: Loaded cached analysis & tests (Hash: {cached_entry['firmware_hash'][:8]})... (Gemini Bypassed)"
            shared_state["progress"] = 25
            analysis = cached_entry["analysis"]
            tests = cached_entry["tests"]
            (dev_dir / "analysis.json").write_text(
                analysis.model_dump_json(indent=2), encoding="utf-8"
            )
            (dev_dir / "tests.json").write_text(
                TestList(tests=tests).model_dump_json(indent=2),
                encoding="utf-8",
            )
            (dev_dir / "firmware_hash.txt").write_text(current_hash, encoding="utf-8")
            (dev_dir / "firmware_source.txt").write_text(source_code, encoding="utf-8")
        elif (
            not (dev_dir / "analysis.json").is_file()
            or not (dev_dir / "tests.json").is_file()
            or not (dev_dir / "firmware_hash.txt").is_file()
            or (dev_dir / "firmware_hash.txt").read_text(encoding="utf-8").strip() != current_hash
        ):
            shared_state["status"] = f"1. Build & Spec: Analyzing {fw_dir.name} with Gemini..."
            shared_state["progress"] = 15
            analysis = analyze_firmware(source_code)
            (dev_dir / "analysis.json").write_text(
                analysis.model_dump_json(indent=2), encoding="utf-8"
            )

            if stop_event.is_set():
                shared_state["status"] = "Run stopped after analysis."
                shared_state["done"] = True
                return

            shared_state["status"] = "2. Test Generation: Synthesizing test cases with Gemini..."
            shared_state["progress"] = 25
            tests = generate_tests(analysis, source_code, target_count=16)
            (dev_dir / "tests.json").write_text(
                TestList(tests=tests).model_dump_json(indent=2),
                encoding="utf-8",
            )
            (dev_dir / "firmware_hash.txt").write_text(current_hash, encoding="utf-8")
            (dev_dir / "firmware_source.txt").write_text(source_code, encoding="utf-8")

            # Store into SQLite Backend Database
            lang = detect_firmware_language(fw_src)
            save_firmware_cache(
                source_code=source_code,
                firmware_name=fw_dir.name or "firmware",
                language=lang,
                analysis=analysis,
                tests=tests,
            )

        if stop_event.is_set():
            shared_state["status"] = "Run stopped before simulation."
            shared_state["done"] = True
            return

        # 2. Run simulation
        sim_name = shared_state.get("simulator_name", "wokwi")
        sim_engine = get_simulator(sim_name)
        sim_label = sim_engine.display_name

        shared_state["status"] = f"3. {sim_label}: Initializing hardware..."
        shared_state["progress"] = 30

        def on_sim_event(ev: dict[str, Any]) -> None:
            if ev.get("type") == "test_started":
                idx = ev.get("index", 1)
                tot = ev.get("total", 1)
                tid = ev.get("test_id", "")
                shared_state["status"] = f"3. {sim_engine.name.upper()}: Running [{idx}/{tot}] {tid}..."
                pct = int(30 + ((idx - 1) / max(1, tot)) * 45)
                shared_state["progress"] = min(pct, 75)
            elif ev.get("type") == "test_finished":
                idx = ev.get("index", 1)
                tot = ev.get("total", 1)
                tid = ev.get("test_id", "")
                res = ev.get("result")
                status = res.status if res else "DONE"
                pct = int(30 + (idx / max(1, tot)) * 45)
                shared_state["progress"] = min(pct, 75)
                shared_state["status"] = f"3. {sim_engine.name.upper()}: [{idx}/{tot}] {tid} -> {status}"
            elif ev.get("type") == "followup_started":
                shared_state["status"] = f"3. Follow-up: Probing failures with {ev.get('count')} tests..."

        followup_opt = shared_state.get("enable_followup", False)
        manifest = run_all(
            run_id=run_id,
            source_dir=dev_dir,
            firmware_dir=fw_dir,
            on_event=on_sim_event,
            stop_event=stop_event,
            enable_followup=followup_opt,
            simulator_name=sim_name,
        )
        new_run_dir = RUNS_DIR / manifest.run_id

        # 3. Root Cause Analysis (only if not stopped and has failures)
        if not stop_event.is_set() and manifest.status != "stopped" and manifest.failed > 0:
            shared_state["status"] = "4. Root Cause: Diagnosing bugs with Gemini..."
            shared_state["progress"] = 80
            try:
                run_root_cause(run_dir=new_run_dir)
            except Exception as rc_exc:
                log_ui_error(manifest.run_id, "root_cause", rc_exc)

        # 4. Generate Reports (even if stopped, generate partial report)
        shared_state["status"] = "5. Final Report: Compiling Markdown and HTML reports..."
        shared_state["progress"] = 95
        try:
            generate_reports(run_dir=new_run_dir)
        except Exception as rep_exc:
            log_ui_error(manifest.run_id, "generate_reports", rep_exc)

        shared_state["progress"] = 100
        shared_state["manifest"] = manifest
        shared_state["status"] = "Complete" if manifest.status != "stopped" else "Stopped"
        shared_state["done"] = True

    except Exception as exc:
        log_ui_error(run_id, "pipeline", exc)
        shared_state["error"] = exc
        shared_state["done"] = True


# ==========================================
# Sidebar: Settings, Preflight & Run Selection
# ==========================================
with st.sidebar:
    st.header("⚡ FirmAgent")
    st.caption("Autonomous Embedded Firmware Testing")

    # Preflight Panel
    with st.expander("🛠 Preflight Checks", expanded=True):
        checks = run_preflight()
        preflight_ok = all(check.ok for check in checks)
        failed_checks = [c for c in checks if not c.ok]

        for check in checks:
            if check.ok:
                st.markdown(f"✅ **{check.name}** (`{check.detail}`)")
            else:
                st.markdown(f"❌ **{check.name}** (`{check.detail}`)")
                if check.hint:
                    st.caption(f"💡 {check.hint}")

        # Internet check
        online = is_internet_available()
        if online:
            st.markdown("✅ **Internet Connection** (`online`)")
        else:
            st.markdown("❌ **Internet Connection** (`offline`)")
            st.caption("💡 Switch to Replay mode (Load golden run) for offline testing.")

    st.divider()
    st.subheader("Configuration")

    avail_fws = get_available_firmwares()

    def format_fw_opt(fw_key: str) -> str:
        if fw_key in FIRMWARE_PRESETS:
            return FIRMWARE_PRESETS[fw_key]["title"]
        return f"📁 {fw_key}"

    cur_fw_idx = 0
    if _active_fw_name in avail_fws:
        cur_fw_idx = avail_fws.index(_active_fw_name)

    chosen_fw = st.selectbox(
        "Target Firmware",
        options=avail_fws,
        index=cur_fw_idx,
        format_func=format_fw_opt,
        key="target_firmware_choice",
        help="Select target firmware. FirmAgent adapts simulator, compiler diagnostics, and test suites automatically.",
    )
    if chosen_fw in FIRMWARE_PRESETS:
        st.caption(f"💡 *{FIRMWARE_PRESETS[chosen_fw]['desc']}*")

    # Multi-Simulator Selector
    sim_options = {
        "wokwi": "Wokwi Hardware Simulator (Arduino Uno + Circuit)",
        "virtual_mock": "Universal Virtual Hardware Simulator (Zero-Dependency)",
        "native_c": "Native C/C++ Host Runner (GCC/Clang)",
        "python_sim": "MicroPython / Embedded Python Runner",
    }
    sim_keys = list(sim_options.keys())
    current_stored_sim = st.session_state.get("simulator_engine_choice")
    if current_stored_sim not in sim_keys:
        def_sim = FIRMWARE_PRESETS.get(chosen_fw, {}).get("default_sim", "wokwi")
        default_sim_idx = sim_keys.index(def_sim) if def_sim in sim_keys else 0
    else:
        default_sim_idx = sim_keys.index(current_stored_sim)

    selected_sim_id = st.selectbox(
        "Simulator Engine",
        options=sim_keys,
        format_func=lambda x: sim_options[x],
        index=default_sim_idx,
        key="simulator_engine_choice",
        help="Choose simulator engine. Use 'Universal Virtual Hardware' for instant execution without Wokwi CLI.",
    )

    # Backend Database Stats
    try:
        db_stats = get_db_stats()
        st.caption(f"💾 **Backend DB (`firmagent.db`):** {db_stats['cached_firmwares']} firmware(s) cached | {db_stats['recorded_runs']} run(s) archived")
    except Exception:
        pass

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

    # Golden Run button (Always enabled per TASK-021)
    golden_dir = RUNS_DIR / "golden"
    if golden_dir.is_dir():
        if st.button("🌟 Load Golden Run (Replay)", use_container_width=True):
            try:
                st.session_state["active_run_id"] = "golden"
                st.success("Loaded Golden Run.")
                st.rerun()
            except Exception as exc:
                log_ui_error("golden", "load_golden", exc)
                cause, hint = classify_error(exc)
                st.error(f"❌ Failed to load golden run: {cause}. 💡 *Hint:* {hint}")

    st.divider()
    regen_disabled = not preflight_ok or st.session_state.get("pipeline_running", False)
    if st.button("🔄 Regenerate Analysis & Tests", use_container_width=True, disabled=regen_disabled):
        if not FIRMWARE_SRC_FILE.is_file():
            st.error("Firmware source file not found.")
        else:
            try:
                with st.spinner(f"Analyzing {FIRMWARE_DIR.name} & generating tests..."):
                    source_code = FIRMWARE_SRC_FILE.read_text(encoding="utf-8")
                    analysis = analyze_firmware(source_code)
                    tests = generate_tests(analysis, source_code, target_count=16)
                    dev_dir = RUNS_DIR / "dev"
                    dev_dir.mkdir(parents=True, exist_ok=True)
                    (dev_dir / "analysis.json").write_text(
                        analysis.model_dump_json(indent=2), encoding="utf-8"
                    )
                    (dev_dir / "tests.json").write_text(
                        TestList(tests=tests).model_dump_json(indent=2),
                        encoding="utf-8",
                    )
                    current_hash = hashlib.sha256(source_code.encode("utf-8")).hexdigest()
                    (dev_dir / "firmware_hash.txt").write_text(current_hash, encoding="utf-8")
                    (dev_dir / "firmware_source.txt").write_text(source_code, encoding="utf-8")
                    lang = detect_firmware_language(FIRMWARE_SRC_FILE)
                    save_firmware_cache(
                        source_code=source_code,
                        firmware_name=FIRMWARE_DIR.name,
                        language=lang,
                        analysis=analysis,
                        tests=tests,
                    )
                    st.session_state["active_run_id"] = "dev"
                    st.success(
                        f"Generated {len(analysis.spec_rules)} rules & {len(tests)} tests for `{FIRMWARE_DIR.name}`!"
                    )
                    time.sleep(1)
                    st.rerun()
            except Exception as exc:
                log_ui_error("dev", "regenerate_tests", exc)
                cause, hint = classify_error(exc)
                st.error(f"❌ Analysis / Generation failed: {cause}\n\n💡 *Hint:* {hint}")


# Determine Active Run Directory
active_run_id = st.session_state.get("active_run_id", "dev")
active_run_dir = RUNS_DIR / active_run_id
if not active_run_dir.is_dir():
    active_run_dir = RUNS_DIR / "dev"


def load_run_file(filename: str):
    """Safely load JSON file from active run directory or fallback to dev."""
    p = active_run_dir / filename
    if not p.is_file():
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
fw_rel_src = FIRMWARE_SRC_FILE.relative_to(PROJECT_ROOT) if FIRMWARE_SRC_FILE.is_file() else f"firmware/{FIRMWARE_DIR.name}"
st.caption(
    f"Active Workspace: `{active_run_dir.name}` | Target: `{fw_rel_src}`"
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

    # Preflight Blocked State Warning (TASK-021 requirement 5)
    if not preflight_ok:
        st.error(
            f"⚠️ **Simulation is disabled: {len(failed_checks)} preflight check(s) failed.**\n\n"
            + "\n".join(f"- **{c.name}**: {c.hint or c.detail}" for c in failed_checks)
            + "\n\n💡 *Hint:* You can still click **🌟 Load Golden Run (Replay)** in the sidebar to inspect a complete pre-recorded test run offline."
        )

    # Firmware Target & Pre-Flight Syntax Check
    with st.expander("🔌 Target Firmware & Syntax Pre-Flight Validation", expanded=True):
        st.markdown(
            "Upload or verify the target Arduino/C++/Python firmware before testing. "
            "If the source has syntax errors (missing semicolons, braces, typos), click **🛠️ Auto-Fix Syntax Errors** to diagnose and repair them automatically with Gemini."
        )

        fw_content_current = FIRMWARE_SRC_FILE.read_text(encoding="utf-8") if FIRMWARE_SRC_FILE.is_file() else ""
        det_lang = detect_firmware_language(fw_content_current)
        cached_record = get_firmware_cache(fw_content_current) if fw_content_current else None
        current_sim_id = st.session_state.get("simulator_engine_choice", "wokwi")

        badge_c1, badge_c2 = st.columns(2)
        with badge_c1:
            st.markdown(f"🏷️ **Detected Language:** `{det_lang.upper()}` | **Selected Engine:** `{current_sim_id}`")
        with badge_c2:
            if cached_record is not None:
                st.markdown(f"⚡ **Backend DB Status:** `CACHED` (SHA: `{cached_record['firmware_hash'][:8]}`) — *Gemini Bypassed*")
            else:
                st.markdown("🌐 **Backend DB Status:** `FRESH` — *Will query Gemini & Cache to DB*")

        if cached_record is not None:
            col_msg, col_clr = st.columns([3, 1])
            with col_msg:
                st.caption("⚡ *Analysis & 16-test suite are cached in `runs/firmagent.db`. Re-running will load instantly from SQLite with 0 Gemini calls.*")
            with col_clr:
                if st.button("🗑️ Invalidate Cache", key="clear_cache_btn", help="Evict from SQLite cache and force fresh LLM analysis."):
                    delete_firmware_cache(fw_content_current)
                    st.success("Cache evicted! Next run will query Gemini.")
                    time.sleep(0.5)
                    st.rerun()

        st.divider()

        fw_col1, fw_col2 = st.columns([3, 2])

        with fw_col1:
            st.markdown("**📂 Firmware Source: Quick-Load or Upload**")
            up_mode = st.radio(
                "Source Mode",
                options=["📥 Load from Sample Library", "💻 Upload Local File from Disk"],
                horizontal=True,
                label_visibility="collapsed",
                key="fw_source_mode_radio",
            )
            if up_mode == "📥 Load from Sample Library":
                local_samples = get_local_sample_firmwares()
                sample_names = list(local_samples.keys())
                sel_sample = st.selectbox(
                    "Choose Pre-Packaged Sample Firmware",
                    options=sample_names,
                    format_func=lambda x: f"📄 {x}",
                    key="sel_sample_preset_box",
                    help="Select any sample firmware to immediately inject it into the active workspace.",
                )
                if st.button("📥 Load Sample into Active Workspace", use_container_width=True, key="load_sample_btn"):
                    if sel_sample and sel_sample in local_samples:
                        target_path = local_samples[sel_sample]
                        fw_content = target_path.read_text(encoding="utf-8")
                        det_lang = detect_firmware_language(target_path)

                        ext = target_path.suffix or ".cpp"
                        dest_file = FIRMWARE_DIR / "src" / ("main" + ext)
                        if not dest_file.parent.is_dir():
                            dest_file.parent.mkdir(parents=True, exist_ok=True)
                        if dest_file.is_file():
                            bak = dest_file.with_name(dest_file.name + ".bak")
                            bak.write_text(dest_file.read_text(encoding="utf-8"), encoding="utf-8")
                        dest_file.write_text(fw_content, encoding="utf-8")

                        # Remove stale dev firmware_hash to force fresh analysis
                        dev_dir = RUNS_DIR / "dev"
                        if (dev_dir / "firmware_hash.txt").is_file():
                            try:
                                (dev_dir / "firmware_hash.txt").unlink()
                            except Exception:
                                pass

                        # Auto-set simulator engine
                        if det_lang == "python":
                            st.session_state["simulator_engine_choice"] = "python_sim"
                        elif det_lang == "c":
                            st.session_state["simulator_engine_choice"] = "native_c"
                        else:
                            st.session_state["simulator_engine_choice"] = "virtual_mock"

                        st.success(f"✅ Loaded `{sel_sample}` into `{FIRMWARE_DIR.name}`! Detected: `{det_lang.upper()}`. Simulator: `{st.session_state['simulator_engine_choice']}`.")
                        time.sleep(0.5)
                        st.rerun()

            else:
                st.caption("📁 Browse files on your computer. You can also pick from the local `sample_firmwares/` folder:")
                uploaded_fw = st.file_uploader(
                    "Upload Custom Firmware Source (.cpp, .ino, .c, .py)",
                    type=["cpp", "ino", "c", "h", "py"],
                    key="fw_upload_file",
                    help="Upload a target firmware file. It will be loaded into the active firmware directory.",
                )
                if uploaded_fw is not None:
                    if st.session_state.get("last_uploaded_fw") != uploaded_fw.name:
                        try:
                            fw_content = uploaded_fw.getvalue().decode("utf-8", errors="replace")
                            ext = Path(uploaded_fw.name).suffix or ".cpp"
                            dest_file = FIRMWARE_DIR / "src" / ("main" + ext)
                            if not dest_file.parent.is_dir():
                                dest_file.parent.mkdir(parents=True, exist_ok=True)
                            if dest_file.is_file():
                                bak_path = dest_file.with_name(dest_file.name + ".bak")
                                bak_path.write_text(dest_file.read_text(encoding="utf-8"), encoding="utf-8")
                            dest_file.write_text(fw_content, encoding="utf-8")

                            # Detect language & configure simulator
                            det_lang = detect_firmware_language(fw_content)
                            if det_lang == "python":
                                st.session_state["simulator_engine_choice"] = "python_sim"
                            elif det_lang == "c":
                                st.session_state["simulator_engine_choice"] = "native_c"
                            else:
                                st.session_state["simulator_engine_choice"] = "virtual_mock"

                            dev_dir = RUNS_DIR / "dev"
                            if (dev_dir / "firmware_hash.txt").is_file():
                                try:
                                    (dev_dir / "firmware_hash.txt").unlink()
                                except Exception:
                                    pass

                            st.session_state["last_uploaded_fw"] = uploaded_fw.name
                            st.success(f"✅ Uploaded `{uploaded_fw.name}`! Language: `{det_lang.upper()}`. Simulator: `{st.session_state['simulator_engine_choice']}`.")
                            time.sleep(0.5)
                            st.rerun()
                        except Exception as up_exc:
                            st.error(f"Failed to save uploaded firmware: {up_exc}")

            # Undo / Restore Backup Button
            bak_file = FIRMWARE_SRC_FILE.with_name(FIRMWARE_SRC_FILE.name + ".bak")
            if bak_file.is_file():
                if st.button(f"⏮️ Restore Previous Code ({bak_file.name})", key="restore_bak_btn", use_container_width=True):
                    FIRMWARE_SRC_FILE.write_text(bak_file.read_text(encoding="utf-8"), encoding="utf-8")
                    bak_file.unlink()
                    st.success(f"Restored `{FIRMWARE_SRC_FILE.name}` from backup!")
                    time.sleep(0.5)
                    st.rerun()

        with fw_col2:
            st.markdown("**Syntax Diagnostics & Auto-Repair**")
            syntax_c1, syntax_c2 = st.columns(2)
            with syntax_c1:
                check_syntax_clicked = st.button("🔍 Check Syntax", use_container_width=True)
            with syntax_c2:
                fix_syntax_clicked = st.button("🛠️ Fix Syntax Errors", type="secondary", use_container_width=True)

        if check_syntax_clicked:
            with st.spinner("Checking firmware compilation with PlatformIO..."):
                syn_ok, syn_log = check_firmware_syntax(FIRMWARE_DIR)
                if syn_ok:
                    st.success("✅ **Firmware syntax is clean!** Compilation succeeded with 0 errors.")
                else:
                    st.error("❌ **Firmware compilation failed with syntax errors:**")
                    st.code(syn_log, language="text")
                    st.info("💡 Click **🛠️ Fix Syntax Errors** above to automatically diagnose and repair these errors.")

        if fix_syntax_clicked:
            with st.spinner("Diagnosing syntax errors and auto-repairing with Gemini..."):
                try:
                    fix_res = auto_fix_syntax_errors(FIRMWARE_DIR)
                    if fix_res["status"] == "CLEAN":
                        st.success("✅ **Firmware is already clean!** Compilation succeeded with 0 errors.")
                    elif fix_res["status"] == "FIXED":
                        st.success("🎉 **Syntax errors successfully repaired!** Firmware now compiles cleanly with 0 errors.")
                        if fix_res.get("explanation"):
                            st.markdown(f"**Fix Applied:** {fix_res['explanation']}")
                        if fix_res.get("errors_addressed"):
                            for err_desc in fix_res["errors_addressed"]:
                                st.markdown(f"- ✅ {err_desc}")
                        if fix_res.get("diff"):
                            with st.expander("📝 View Applied Syntax Diff", expanded=True):
                                st.code(fix_res["diff"], language="diff")
                        time.sleep(1)
                    else:
                        st.error("⚠️ **Could not automatically resolve all syntax errors.**")
                        st.code(fix_res.get("error_log", "Unknown compiler error"), language="text")
                except Exception as syn_exc:
                    cause, hint = classify_error(syn_exc)
                    st.error(f"❌ Syntax repair failed: {cause}\n\n💡 *Hint:* {hint}")

        with st.expander(f"📄 View Active Firmware Source (`{fw_rel_src}`)", expanded=False):
            if FIRMWARE_SRC_FILE.is_file():
                syntax_lang = "python" if FIRMWARE_SRC_FILE.suffix == ".py" else ("c" if FIRMWARE_SRC_FILE.suffix == ".c" else "cpp")
                st.code(FIRMWARE_SRC_FILE.read_text(encoding="utf-8"), language=syntax_lang)
            else:
                st.caption("No firmware source file found.")

    # Action Buttons: Run & Stop
    col_start, col_stop = st.columns([2, 1])
    is_running = st.session_state.get("pipeline_running", False)

    # Standalone simulators do not require Wokwi CLI or Wokwi token
    sim_is_standalone = current_sim_id in ("virtual_mock", "native_c", "python_sim")
    can_start = (preflight_ok or sim_is_standalone) and not is_running

    with col_start:
        start_btn = st.button(
            "🚀 Run Autonomous Test",
            type="primary",
            use_container_width=True,
            disabled=not can_start,
            help="Resolve preflight issues above before starting a Wokwi run, or switch to 'Universal Virtual Hardware Simulator' in the sidebar." if not can_start and not is_running else None,
        )

    with col_stop:
        stop_btn = st.button(
            "⏹ Stop Run",
            use_container_width=True,
            disabled=not is_running,
            help="Signals the simulation runner to stop after finishing the current test.",
        )

    enable_followup_val = st.checkbox(
        "Enable Autonomous Follow-Up Probing (+4 exploratory failure tests)",
        value=False,
        key="enable_followup_toggle",
        help="When enabled, if failures are detected, FirmAgent generates 4 targeted follow-up test cases (F01-F04) to probe root causes, expanding the suite from 16 to 20 tests.",
    )

    # Progress Stepper Display
    stepper_cols = st.columns(5)
    steps_labels = [
        "1. Build & Spec",
        "2. Test Generation",
        "3. Simulation Engine",
        "4. Root Cause",
        "5. Final Report",
    ]
    for col, lbl in zip(stepper_cols, steps_labels):
        with col:
            st.info(f"**{lbl}**")

    # Handle Stop Click
    if stop_btn:
        if st.session_state.get("stop_event"):
            st.session_state["stop_event"].set()
            st.warning("⏹ **Stop requested:** The currently running test will finish, then the pipeline will stop and compile partial reports.")

    # Handle Start Click
    if start_btn:
        try:
            new_run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
            stop_evt = threading.Event()
            st.session_state["stop_event"] = stop_evt
            shared_data = {
                "status": "Starting pipeline...",
                "progress": 5,
                "done": False,
                "manifest": None,
                "error": None,
                "run_id": new_run_id,
                "enable_followup": enable_followup_val,
                "simulator_name": current_sim_id,
                "firmware_dir": FIRMWARE_DIR,
                "firmware_src_file": FIRMWARE_SRC_FILE,
            }
            st.session_state["pipeline_shared"] = shared_data
            st.session_state["pipeline_running"] = True
            pipe_thread = threading.Thread(
                target=run_autonomous_pipeline,
                args=(new_run_id, shared_data, stop_evt),
                daemon=True,
            )
            pipe_thread.start()
            st.session_state["pipeline_thread"] = pipe_thread
            st.rerun()
        except Exception as exc:
            log_ui_error("pipeline_start", "start_pipeline", exc)
            cause, hint = classify_error(exc)
            st.error(f"❌ Could not start pipeline: {cause}\n\n💡 *Hint:* {hint}")

    # Live Spinner & Progress Bar while Running
    if is_running:
        shared = st.session_state.get("pipeline_shared", {})
        step_name = shared.get("status", "Executing pipeline...")
        pct = shared.get("progress", 10)

        with st.spinner(f"⏳ {step_name}"):
            st.progress(pct)
            st.caption(f"Status: **{step_name}**")

        if shared.get("done", False):
            st.session_state["pipeline_running"] = False
            run_id = shared.get("run_id")
            if shared.get("error"):
                exc = shared["error"]
                cause, hint = classify_error(exc)
                st.error(f"⚠️ **{cause}**\n\n💡 *Hint:* {hint} (Diagnostics written to `runs/{run_id}/error.log`)")
            else:
                st.session_state["active_run_id"] = run_id
                time.sleep(0.5)
                st.rerun()
        else:
            time.sleep(0.5)
            st.rerun()

    # Current Run Status & Summary Banner (TASK-021 requirement 7)
    manifest_data = load_run_file("manifest.json")
    results_data = load_run_file("results.json")
    if manifest_data:
        try:
            m = RunManifest.model_validate(manifest_data)
            st.divider()

            # Synchronize actual counts directly from results.json
            if results_data:
                r_objs = [TestResult.model_validate(r) for r in results_data]
                p_cnt = sum(1 for r in r_objs if r.status == "PASS")
                f_cnt = sum(1 for r in r_objs if r.status == "FAIL")
                e_cnt = sum(1 for r in r_objs if r.status == "ERROR")
                completed_cnt = len(r_objs)
            else:
                p_cnt = m.passed
                f_cnt = m.failed
                e_cnt = m.errors
                completed_cnt = p_cnt + f_cnt + e_cnt

            total_display = m.total_tests

            # Summary banner
            if m.status == "stopped":
                st.info(f"⏹ **Run stopped early: {completed_cnt} of {total_display} tests completed ({p_cnt} passed, {f_cnt} failed, {e_cnt} errors).**")
            elif f_cnt == 0 and e_cnt == 0:
                st.success(f"✅ **Run complete: {completed_cnt} tests executed, all passed (0 failures found).**")
            else:
                f_str = f"{f_cnt} failure{'s' if f_cnt != 1 else ''}"
                e_str = f", {e_cnt} simulator error{'s' if e_cnt != 1 else ''}" if e_cnt > 0 else ""
                st.warning(f"⚠️ **Run complete: {completed_cnt} tests executed, {f_str}{e_str} found.**")

            st.subheader(f"Current Run Status: `{active_run_dir.name}`")
            c1, c2, c3, c4, c5 = st.columns(5)
            if m.status == "stopped" and completed_cnt < total_display:
                c1.metric("Total Planned", total_display)
                c2.metric("Executed", f"{completed_cnt} / {total_display}")
                c3.metric("Passed", f"✅ {p_cnt}")
                c4.metric("Failed", f"❌ {f_cnt}")
                c5.metric("Status", "⏹ STOPPED")
            else:
                c1.metric("Total Tests", completed_cnt)
                c2.metric("Passed", f"✅ {p_cnt}")
                c3.metric("Failed", f"❌ {f_cnt}")
                c4.metric("Errors", f"⚠ {e_cnt}")
                status_icon = "✅" if m.status == "done" else ("⏹" if m.status == "stopped" else "⏳")
                c5.metric("Status", f"{status_icon} {m.status.upper()}")

            # Quick Re-run Section in Tab 1 (TASK-021 requirement 3)
            tests_data = load_run_file("tests.json")
            results_data = load_run_file("results.json")
            if tests_data and results_data:
                raw_t = tests_data.get("tests", []) if isinstance(tests_data, dict) else tests_data
                t_objs = [TestCase.model_validate(t) for t in raw_t]
                r_objs = [TestResult.model_validate(r) for r in results_data]
                r_map = {r.test_id: r for r in r_objs}

                with st.expander("🔄 Re-run Individual Test from this Run", expanded=False):
                    opt_labels = []
                    opt_map = {}
                    for t in t_objs:
                        res = r_map.get(t.id)
                        stat = res.status if res else "NOT RUN"
                        icon = "✅" if stat == "PASS" else ("❌" if stat == "FAIL" else ("⚠" if stat == "ERROR" else "⏳"))
                        lbl = f"{icon} {t.id} - {t.name} ({stat})"
                        opt_labels.append(lbl)
                        opt_map[lbl] = t

                    sel_opt = st.selectbox("Choose a test to re-run in simulator:", options=opt_labels, key="tab1_rerun_sel")
                    if sel_opt and sel_opt in opt_map:
                        target_t = opt_map[sel_opt]
                        if st.button(f"🔄 Re-run this test ({target_t.id})", key="tab1_rerun_btn"):
                            try:
                                with st.spinner(f"Re-running {target_t.id} in Wokwi simulator..."):
                                    rerun_res = run_test(test=target_t, firmware_dir=FIRMWARE_DIR, run_dir=active_run_dir)
                                    r_map[target_t.id] = rerun_res
                                    updated_results = [r_map.get(t.id, rerun_res) for t in t_objs]
                                    (active_run_dir / "results.json").write_text(
                                        json.dumps([r.model_dump() for r in updated_results], indent=2), encoding="utf-8"
                                    )
                                    m.passed = sum(1 for r in updated_results if r.status == "PASS")
                                    m.failed = sum(1 for r in updated_results if r.status == "FAIL")
                                    m.errors = sum(1 for r in updated_results if r.status == "ERROR")
                                    (active_run_dir / "manifest.json").write_text(m.model_dump_json(indent=2), encoding="utf-8")
                                    try:
                                        generate_reports(active_run_dir)
                                    except Exception:
                                        pass
                                    st.success(f"✅ Re-run complete for {target_t.id}: status is **{rerun_res.status}**.")
                                    time.sleep(1)
                                    st.rerun()
                            except Exception as exc:
                                log_ui_error(active_run_dir.name, f"tab1_rerun_{target_t.id}", exc)
                                cause, hint = classify_error(exc)
                                st.error(f"❌ Failed to re-run {target_t.id}: {cause}. 💡 *Hint:* {hint}")
        except Exception as exc:
            log_ui_error(active_run_dir.name, "tab1_render", exc)
            cause, hint = classify_error(exc)
            st.error(f"Error displaying run status: {cause}")
    else:
        st.divider()
        st.info(
            "ℹ️ **Welcome to FirmAgent!** Pick a target firmware above and click **🚀 Run Autonomous Test** to start the pipeline, "
            "or click **🌟 Load Golden Run** in the sidebar to inspect pre-recorded results."
        )


# ==========================================
# Tab 2: Analysis
# ==========================================
with tab_analysis:
    analysis_data = load_run_file("analysis.json")
    if not analysis_data:
        st.info(
            "ℹ️ **No firmware analysis available yet.**\n\n"
            "Pick a target firmware and click **🚀 Run Autonomous Test** in Tab 1 (or **🔄 Regenerate Analysis & Tests** in the sidebar) "
            "to analyze firmware source code and extract specification rules."
        )
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
            log_ui_error(active_run_dir.name, "tab2_analysis", exc)
            cause, hint = classify_error(exc)
            st.error(f"❌ Error displaying analysis: {cause}. 💡 *Hint:* {hint}")


# ==========================================
# Tab 3: Tests
# ==========================================
with tab_tests:
    tests_data = load_run_file("tests.json")
    if not tests_data:
        st.info(
            "ℹ️ **No test cases generated yet.**\n\n"
            "Pick a target firmware and click **🚀 Run Autonomous Test** in Tab 1 (or **🔄 Regenerate Analysis & Tests** in the sidebar) "
            "to automatically synthesize targeted test cases."
        )
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
            log_ui_error(active_run_dir.name, "tab3_tests", exc)
            cause, hint = classify_error(exc)
            st.error(f"❌ Error displaying test suite: {cause}. 💡 *Hint:* {hint}")


# ==========================================
# Tab 4: Live Execution
# ==========================================
with tab_live:
    tests_data = load_run_file("tests.json")
    results_data = load_run_file("results.json")

    if not tests_data or not results_data:
        st.info(
            "ℹ️ **No execution telemetry available yet.**\n\n"
            "Pick a firmware and click **🚀 Run Autonomous Test** in Tab 1 to run tests in the Wokwi simulator, "
            "or click **🌟 Load Golden Run** in the sidebar to inspect pre-recorded results."
        )
    else:
        try:
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
                        # Status banner with icon & text (TASK-021 requirement 6 & 9)
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
                            if sel_res.error_message:
                                st.caption(f"Fault detail: `{sel_res.error_message}`")

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

                        # Expandable raw serial log with monospace >=13px styling
                        with st.expander("📜 Raw Simulator Serial Log"):
                            st.code(
                                sel_res.serial_log or "(no log)", language="text"
                            )

                    # Re-run button for this test (TASK-021 requirement 3)
                    if st.button(f"🔄 Re-run this test ({sel_test.id})", key=f"rerun_{sel_test.id}"):
                        try:
                            with st.spinner(f"Running {sel_test.id} in simulator..."):
                                rerun_res = run_test(
                                    test=sel_test,
                                    firmware_dir=FIRMWARE_DIR,
                                    run_dir=active_run_dir,
                                )
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
                                manifest_obj = load_run_file("manifest.json")
                                if manifest_obj:
                                    m_model = RunManifest.model_validate(manifest_obj)
                                    m_model.passed = sum(1 for r in new_results if r.status == "PASS")
                                    m_model.failed = sum(1 for r in new_results if r.status == "FAIL")
                                    m_model.errors = sum(1 for r in new_results if r.status == "ERROR")
                                    (active_run_dir / "manifest.json").write_text(
                                        m_model.model_dump_json(indent=2), encoding="utf-8"
                                    )
                                try:
                                    generate_reports(active_run_dir)
                                except Exception:
                                    pass
                                st.success(f"✅ Re-run complete for {sel_test.id}: status is **{rerun_res.status}**.")
                                time.sleep(1)
                                st.rerun()
                        except Exception as exc:
                            log_ui_error(active_run_dir.name, f"rerun_{sel_test.id}", exc)
                            cause, hint = classify_error(exc)
                            st.error(f"❌ Failed to re-run {sel_test.id}: {cause}. 💡 *Hint:* {hint}")
        except Exception as exc:
            log_ui_error(active_run_dir.name, "tab4_live", exc)
            cause, hint = classify_error(exc)
            st.error(f"❌ Error displaying live execution telemetry: {cause}. 💡 *Hint:* {hint}")


# ==========================================
# Tab 5: Report
# ==========================================
with tab_report:
    manifest_data = load_run_file("manifest.json")
    results_data = load_run_file("results.json")
    tests_data = load_run_file("tests.json")
    findings_data = load_run_file("findings.json")

    if not manifest_data or not results_data:
        st.info(
            "ℹ️ **No test report available yet.**\n\n"
            "Run the autonomous test suite in Tab 1 or click **🌟 Load Golden Run** in the sidebar "
            "to inspect executive metric cards, coverage matrices, and root-cause bug diagnoses."
        )
    else:
        try:
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

            # Summary banner & Verified Counts (guarantees Total == Passed + Failed + Errors)
            p_cnt = sum(1 for r in results if r.status == "PASS")
            f_cnt = sum(1 for r in results if r.status == "FAIL")
            e_cnt = sum(1 for r in results if r.status == "ERROR")
            executed_cnt = len(results)
            total_planned = manifest.total_tests

            if manifest.status == "stopped":
                st.info(f"⏹ **Run stopped early: {executed_cnt} of {total_planned} tests completed ({p_cnt} passed, {f_cnt} failed, {e_cnt} errors).**")
            elif f_cnt == 0 and e_cnt == 0:
                st.success(f"✅ **Executive Summary: {executed_cnt} tests executed, all passed (0 failures found).**")
            else:
                fail_label = f"{f_cnt} failure{'s' if f_cnt != 1 else ''}"
                err_label = f", {e_cnt} error{'s' if e_cnt != 1 else ''}" if e_cnt > 0 else ""
                st.warning(f"⚠️ **Executive Summary: {executed_cnt} tests executed, {fail_label}{err_label} found.**")

            # Metric Cards
            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("Tests Executed", executed_cnt)
            pass_rate = (
                f"{(p_cnt / executed_cnt * 100):.0f}%"
                if executed_cnt
                else "0%"
            )
            c2.metric("Passed", p_cnt, delta=pass_rate)
            c3.metric("Failed", f_cnt)
            c4.metric("Errors", e_cnt)
            c5.metric("Defects Identified", len(findings))

            st.divider()

            # Test Coverage Matrix with icons & text (TASK-021 requirement 9)
            st.markdown("### 📊 Test Coverage Matrix")
            cov = compute_coverage(tests, results)
            cat_matrix = cov["categories"]
            rules_map = cov["rules"]

            cov_rows = []
            for cat, counts in sorted(cat_matrix.items()):
                rate = (
                    f"{(counts['passed'] / counts['total'] * 100):.0f}%"
                    if counts["total"]
                    else "0%"
                )
                if counts["total"] == 0:
                    status_str = "⚠️ NO TESTS"
                elif counts["passed"] == counts["total"]:
                    status_str = "✅ PASS"
                elif counts["failed"] > 0:
                    status_str = "❌ FAIL"
                elif counts["errors"] > 0:
                    status_str = "⚠️ ERROR"
                else:
                    status_str = "⏳ NOT RUN"

                cov_rows.append(
                    {
                        "Category": cat,
                        "Total": counts["total"],
                        "Passed": counts["passed"],
                        "Failed": counts["failed"],
                        "Errors": counts["errors"],
                        "Pass Rate": rate,
                        "Status": status_str,
                    }
                )
            st.dataframe(
                pd.DataFrame(cov_rows),
                use_container_width=True,
                hide_index=True,
            )

            # Specification Rule Coverage (R1 - R6)
            st.markdown("### 📜 Specification Rule Coverage (R1 - R6)")
            rule_rows = []
            for r_id in ["R1", "R2", "R3", "R4", "R5", "R6"]:
                desc = RULE_DESCRIPTIONS.get(r_id, "")
                if r_id == "R6":
                    rule_rows.append(
                        {
                            "Rule": r_id,
                            "Requirement": desc,
                            "Covering Tests": "(none)",
                            "Status": "ℹ️ not testable in simulator",
                        }
                    )
                else:
                    t_ids = rules_map.get(r_id, [])
                    if t_ids:
                        rule_rows.append(
                            {
                                "Rule": r_id,
                                "Requirement": desc,
                                "Covering Tests": ", ".join(t_ids),
                                "Status": "✅ COVERED",
                            }
                        )
                    else:
                        rule_rows.append(
                            {
                                "Rule": r_id,
                                "Requirement": desc,
                                "Covering Tests": "(none)",
                                "Status": "❌ MISSING",
                            }
                        )
            st.dataframe(
                pd.DataFrame(rule_rows),
                use_container_width=True,
                hide_index=True,
            )

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

            # ==========================================
            # Auto Fix Section (TASK-028b)
            # ==========================================
            st.markdown("### 🔧 Autonomous Firmware Bug Fix")
            st.markdown(
                "Generate, validate, and verify minimal C++ code patches directly addressing detected root-cause defects."
            )

            # Replay Mode / Existing Attempt Discovery
            attempt_key = f"fix_attempt_{active_run_id}"
            current_attempt: Optional[FixAttempt] = st.session_state.get(attempt_key)

            if current_attempt is None:
                # Check if an attempt already exists on disk (e.g. golden replay or saved fix)
                existing_att = load_fix_attempt(active_run_id, RUNS_DIR)
                if existing_att:
                    current_attempt = existing_att
                    st.session_state[attempt_key] = existing_att

            if active_run_id == "golden":
                st.info(
                    "🌟 **Offline Replay Mode**: Viewing pre-recorded golden fix attempt without network, Gemini, or Wokwi simulator calls."
                )

            # Check if there are failures in this run
            has_failures = manifest.failed > 0 or manifest.errors > 0

            # 1. Preview Fix Button
            btn_col1, btn_col2 = st.columns([1, 2])
            with btn_col1:
                preview_btn = st.button(
                    "🔍 Preview Auto Fix",
                    type="primary" if current_attempt is None else "secondary",
                    use_container_width=True,
                    disabled=not has_failures and current_attempt is None,
                    help="Synthesize a minimal patch with Gemini and execute 7 safety checks."
                    if has_failures
                    else "All tests passed in this run!",
                    key=f"btn_preview_{active_run_id}",
                )

            if preview_btn:
                try:
                    with st.spinner("🤖 Analyzing root causes and generating autonomous patch proposal with Gemini..."):
                        new_attempt = run_autofix(
                            run_id=active_run_id,
                            runs_base_dir=RUNS_DIR,
                            firmware_dir=FIRMWARE_DIR,
                        )
                        st.session_state[attempt_key] = new_attempt
                        current_attempt = new_attempt
                        st.rerun()
                except Exception as exc:
                    log_ui_error(active_run_id, "preview_autofix", exc)
                    cause, hint = classify_error(exc)
                    st.error(f"❌ Could not preview fix: **{cause}**\n\n💡 *Hint:* {hint}")

            if current_attempt is None:
                if not has_failures:
                    st.success("✅ No failed tests or errors detected in this run. No firmware fix is required.")
                else:
                    st.info("ℹ️ Click **🔍 Preview Auto Fix** to generate an autonomous patch proposal.")
            else:
                # 2. Show the Proposal
                st.markdown("#### 🧩 Patch Proposal")
                st.info(f"**Patch Summary:** {current_attempt.proposal.summary}")

                for h in current_attempt.proposal.hunks:
                    hunk_title = f"Hunk `{h.id}` (Lines {h.start_line}..{h.end_line})"
                    with st.expander(f"🧩 {hunk_title} — {h.explanation[:60]}...", expanded=True):
                        c_meta1, c_meta2, c_meta3 = st.columns(3)
                        c_meta1.markdown(f"**Lines**: `{h.start_line}..{h.end_line}`")
                        fixes_str = ", ".join(f"`{t}`" for t in h.fixes_tests) if h.fixes_tests else "*(none)*"
                        c_meta2.markdown(f"**Fixes Tests**: {fixes_str}")
                        c_meta3.markdown(f"**AI confidence (estimate)**: `{h.confidence * 100:.0f}%`")

                        st.markdown(f"**Explanation:** {h.explanation}")
                        if h.spec_ref:
                            st.markdown(f"**Spec Rule Reference:** `{h.spec_ref}`")

                        # Side-by-side rows
                        c_orig, c_sugg = st.columns(2)
                        with c_orig:
                            st.markdown(f"🔴 **Original Code (Lines {h.start_line}..{h.end_line})**")
                            st.code(h.original_code, language="cpp")
                        with c_sugg:
                            st.markdown("🟢 **Suggested Code (Replacement)**")
                            st.code(h.new_code, language="cpp")

                # Unified diff view
                with st.expander("📄 Unified Diff View", expanded=False):
                    src_text = ""
                    src_path = active_run_dir / "firmware_source.txt"
                    if not src_path.is_file():
                        src_path = FIRMWARE_SRC_FILE
                    if src_path.is_file():
                        src_text = src_path.read_text(encoding="utf-8")
                    diff_str = render_diff(src_text, current_attempt.proposal) if src_text else ""
                    st.code(diff_str or "(No diff)", language="diff")

                # 3. Show Validation as a Checklist with Icons & Text
                st.markdown("#### 🛡️ Safety & Build Validation Checklist")
                check_name_map = {
                    "hunk_limit": "Hunk Count Limit (≤ 3 hunks)",
                    "line_limit": "Line Count Limit (≤ 25 lines total)",
                    "exact_match": "Exact Match Against Source Code",
                    "non_overlapping": "No Overlapping Hunks",
                    "protected_ranges": "Protected Ranges Untouched (spec block, #includes, #defines)",
                    "scope_adherence": "Scope Adherence (within ±5 lines of suspect lines)",
                    "spec_block_integrity": "Spec Comment Block Byte-Identical",
                    "compilation": "PlatformIO Compilation",
                }

                for chk in current_attempt.validation.checks:
                    icon = "✅" if chk.ok else "❌"
                    label = check_name_map.get(chk.name, chk.name.replace("_", " ").title())
                    st.markdown(f"- {icon} **{label}**: {chk.detail}")

                if not current_attempt.validation.ok:
                    st.error("⚠️ **Validation Failed:** The proposal violated one or more safety constraints. Applying this patch is disabled.")

                st.divider()

                # 4. [Apply and verify] button
                st.markdown("#### ⚙️ Sandbox Verification")
                st.caption("⏱ **Note:** This runs real hardware simulations on a sandbox copy and takes about 5 minutes.")

                col_v1, col_v2 = st.columns([1, 2])
                with col_v1:
                    verify_btn = st.button(
                        "🛠️ Apply and Verify",
                        type="primary",
                        disabled=not current_attempt.validation.ok,
                        help="Compile sandbox copy and re-run failed tests + regression test suite."
                        if current_attempt.validation.ok
                        else "Cannot verify an invalid patch.",
                        key=f"btn_verify_{current_attempt.attempt_id}",
                        use_container_width=True,
                    )

                if verify_btn:
                    stop_evt = st.session_state.get("stop_event")
                    try:
                        with st.status("🛠️ Verifying fix in sandbox copy...", expanded=True) as status_box:
                            def on_verify_step(step: str):
                                if step == "build":
                                    st.write("1. 🔨 Compiling sandbox project copy with PlatformIO...")
                                elif step == "retest_failed":
                                    st.write("2. 🔄 Re-running failed tests in Wokwi simulator...")
                                elif step == "regression_check":
                                    st.write("3. 🛡️ Running full regression check on previously passing tests...")

                            verified_attempt = verify_fix(
                                attempt=current_attempt,
                                run_id=active_run_id,
                                runs_base_dir=RUNS_DIR,
                                stop_event=stop_evt,
                                on_step=on_verify_step,
                            )
                            st.session_state[attempt_key] = verified_attempt
                            current_attempt = verified_attempt

                            # Update report.md and report.html with before vs after section
                            src_text = FIRMWARE_SRC_FILE.read_text(encoding="utf-8") if FIRMWARE_SRC_FILE.is_file() else ""
                            diff_text = render_diff(src_text, verified_attempt.proposal)
                            update_reports_with_fix(active_run_id, verified_attempt, diff_text, RUNS_DIR)

                            if verified_attempt.status == "validated":
                                status_box.update(label="✅ Sandbox verification completed successfully!", state="complete", expanded=False)
                            else:
                                status_box.update(label="❌ Fix rejected during sandbox verification.", state="error", expanded=True)
                            st.rerun()
                    except Exception as exc:
                        log_ui_error(active_run_id, "verify_fix", exc)
                        cause, hint = classify_error(exc)
                        st.error(f"❌ Verification failed: **{cause}**\n\n💡 *Hint:* {hint}")

                # 5. Before vs After Table
                if current_attempt.after_counts is not None:
                    st.markdown("#### 📈 Before vs After Fix Verification")
                    b = current_attempt.before_counts
                    a = current_attempt.after_counts or {}

                    b_pass = b.get("passed", 0)
                    b_tot = b.get("total", 0)
                    a_pass = a.get("passed", 0)
                    a_tot = a.get("total", b_tot)

                    m1, m2, m3 = st.columns(3)
                    m1.metric("Test Score", f"{a_pass}/{a_tot}", delta=f"{a_pass - b_pass:+d}")
                    m2.metric("Fixed Tests", len(current_attempt.fixed_tests))
                    m3.metric(
                        "Regressions",
                        len(current_attempt.regressions),
                        delta=f"{len(current_attempt.regressions)}" if current_attempt.regressions else "0",
                        delta_color="inverse",
                    )

                    comp_rows = [
                        {
                            "Metric": "Passed Tests",
                            "Before Fix": f"✅ {b_pass}",
                            "After Fix": f"✅ {a_pass}",
                            "Delta": f"+{a_pass - b_pass}" if a_pass >= b_pass else f"{a_pass - b_pass}",
                        },
                        {
                            "Metric": "Failed Tests",
                            "Before Fix": f"❌ {b.get('failed', 0)}",
                            "After Fix": f"❌ {a.get('failed', 0)}",
                            "Delta": f"{a.get('failed', 0) - b.get('failed', 0):+d}",
                        },
                        {
                            "Metric": "Simulator Errors",
                            "Before Fix": f"⚠ {b.get('errors', 0)}",
                            "After Fix": f"⚠ {a.get('errors', 0)}",
                            "Delta": f"{a.get('errors', 0) - b.get('errors', 0):+d}",
                        },
                        {
                            "Metric": "Total Tests",
                            "Before Fix": str(b_tot),
                            "After Fix": str(a_tot),
                            "Delta": "0",
                        },
                    ]
                    st.dataframe(pd.DataFrame(comp_rows), use_container_width=True, hide_index=True)

                    fixed_label = ", ".join(f"`{t}`" for t in current_attempt.fixed_tests) if current_attempt.fixed_tests else "*(none)*"
                    reg_label = ", ".join(f"`{t}`" for t in current_attempt.regressions) if current_attempt.regressions else "*(none — 0 regressions)*"
                    st.markdown(f"- **Fixed Tests ({len(current_attempt.fixed_tests)})**: {fixed_label}")
                    st.markdown(f"- **Regressions ({len(current_attempt.regressions)})**: {reg_label}")

                    is_verified = (
                        current_attempt.status in ("validated", "applied")
                        and len(current_attempt.fixed_tests) > 0
                        and len(current_attempt.regressions) == 0
                    )

                    if is_verified:
                        st.success(f"✅ **STATUS: VERIFIED** — {len(current_attempt.fixed_tests)} tests fixed with 0 regressions! The patch is safe to apply.")
                    else:
                        rej_cause = ""
                        if current_attempt.regressions:
                            rej_cause = f"Regressions detected: tests {', '.join(current_attempt.regressions)} failed after applying patch."
                        elif len(current_attempt.fixed_tests) == 0:
                            rej_cause = "Zero failed tests were resolved by the patch."
                        else:
                            rej_cause = "Compilation failed on patched sandbox copy."
                        st.error(f"❌ **STATUS: REJECTED** — {rej_cause}")

                    # 6. Apply to Original, Revert, and Discard
                    st.divider()
                    if is_verified:
                        st.markdown("#### 🚀 Apply Fix to Original Firmware")
                        confirm_apply = st.checkbox(
                            "I understand this edits firmware/fan_controller/src/main.cpp, a backup is kept",
                            key=f"chk_confirm_{current_attempt.attempt_id}",
                        )
                        apply_orig_btn = st.button(
                            "💾 Apply to Original Firmware",
                            type="primary",
                            disabled=not confirm_apply or current_attempt.status == "applied",
                            key=f"btn_apply_orig_{current_attempt.attempt_id}",
                        )
                        if apply_orig_btn:
                            try:
                                orig_applied = apply_to_original(
                                    attempt=current_attempt,
                                    run_id=active_run_id,
                                    firmware_dir=FIRMWARE_DIR,
                                    runs_base_dir=RUNS_DIR,
                                )
                                st.success(f"✅ Patch applied to original firmware: `{orig_applied}`! Backup preserved at `main.cpp.bak`.")
                                st.rerun()
                            except Exception as exc:
                                log_ui_error(active_run_id, "apply_to_original", exc)
                                cause, hint = classify_error(exc)
                                st.error(f"❌ Apply failed: {cause}\n\n💡 *Hint:* {hint}")

                    # Action row: Revert, Discard, Save as Golden Fix
                    st.markdown("#### 🛠️ Maintenance & Offline Export")
                    col_act1, col_act2, col_act3 = st.columns(3)
                    with col_act1:
                        if st.button("⏮ Revert Original Firmware", key=f"btn_revert_{current_attempt.attempt_id}", use_container_width=True):
                            try:
                                revert_original(
                                    attempt=current_attempt,
                                    run_id=active_run_id,
                                    firmware_dir=FIRMWARE_DIR,
                                    runs_base_dir=RUNS_DIR,
                                )
                                st.success("✅ Original firmware restored from backup (`main.cpp.bak`).")
                                st.rerun()
                            except Exception as exc:
                                log_ui_error(active_run_id, "revert_original", exc)
                                cause, hint = classify_error(exc)
                                st.error(f"❌ Revert failed: {cause}\n\n💡 *Hint:* {hint}")

                    with col_act2:
                        if st.button("🗑 Discard Fix Proposal", key=f"btn_discard_{current_attempt.attempt_id}", use_container_width=True):
                            st.session_state.pop(attempt_key, None)
                            st.info("Fix proposal removed from active session.")
                            st.rerun()

                    with col_act3:
                        if is_verified:
                            if st.button("🌟 Save as Golden Fix", key=f"btn_save_gold_{current_attempt.attempt_id}", use_container_width=True):
                                try:
                                    g_dest = save_golden_fix_attempt(active_run_id, current_attempt, runs_base_dir=RUNS_DIR)
                                    st.success(f"✅ Saved fix attempt to `{g_dest}` for offline replay!")
                                except Exception as exc:
                                    log_ui_error(active_run_id, "save_golden_fix", exc)
                                    cause, hint = classify_error(exc)
                                    st.error(f"❌ Could not save golden fix: {cause}")

            st.divider()

            # Download Buttons
            st.markdown("### 📥 Download Reports")
            report_md_path = active_run_dir / "report.md"
            report_html_path = active_run_dir / "report.html"

            # Generate on demand if missing
            if not report_md_path.is_file() or not report_html_path.is_file():
                try:
                    generate_reports(active_run_dir)
                except Exception as g_exc:
                    log_ui_error(active_run_dir.name, "generate_reports", g_exc)

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
        except Exception as exc:
            log_ui_error(active_run_dir.name, "tab5_report", exc)
            cause, hint = classify_error(exc)
            st.error(f"❌ Error generating report tab: {cause}. 💡 *Hint:* {hint}")
