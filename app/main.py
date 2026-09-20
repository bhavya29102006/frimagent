"""FirmAgent — Streamlit Application Entrypoint."""

import sys
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st
from agent.preflight import run_preflight

st.set_page_config(
    page_title="FirmAgent",
    page_icon="⚡",
    layout="wide",
)

# Sidebar: Preflight Panel
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

st.title("⚡ FirmAgent")
st.caption("Autonomous Embedded Firmware Testing Agent")
