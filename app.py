import streamlit as st
import sys
from pathlib import Path
import os

# Set page config FIRST before any other streamlit calls
st.set_page_config(
    page_title="LCL Auction 2026",
    page_icon="🏆",
    layout="wide",
    initial_sidebar_state="expanded", # Forces sidebar open on initial load
)

st.markdown("""
<style>
/* 1. Sidebar button styling for dark mode */
section[data-testid="stSidebar"] button {
    color: white !important;
    background-color: #2d2d2d !important;
    border: 1px solid #555 !important;
}

/* Hover effect */
section[data-testid="stSidebar"] button:hover {
    background-color: #444 !important;
    border: 1px solid #888 !important;
}

/* Sidebar text visibility */
section[data-testid="stSidebar"] {
    color: white !important;
}

/* 2. THE FIX: Completely hide the collapse button so the sidebar stays permanently open/fixed */
button[data-testid="stSidebarCollapseButton"],
[data-testid="stSidebarCollapseButton"] {
    display: none !important;
    visibility: hidden !important;
}

/* Readjust main content padding slightly to blend perfectly with a permanent sidebar */
[data-testid="stAppViewBlockContainer"] {
    padding-top: 3rem !important;
}
</style>
""", unsafe_allow_html=True)

from views.login import render_login
from views.viewer import render_viewer
from views.captain import render_captain
from views.admin import render_admin
import db

# Initialize database on startup
db.init_db()

# Initialize session state keys
if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False
if "role" not in st.session_state:
    st.session_state["role"] = None
if "name" not in st.session_state:
    st.session_state["name"] = None

def run_viewer_screen() -> None:
    render_viewer()

def run_live_captain_screen() -> None:
    render_captain()

def main() -> None:
    role = st.query_params.get("role")
    
    if not role:
        render_login()
        return
        
    # Maintain session state for child components
    st.session_state["role"] = role
    st.session_state["name"] = role
    st.session_state["logged_in"] = True
        
    # Render Sidebar with User info and Logout
    st.sidebar.markdown(f"### 👤 User: **{role}**")
    st.sidebar.markdown(f"Role: `{role}`")
    
    if st.sidebar.button("Refresh Data", use_container_width=True):
        st.rerun()
    
    if st.sidebar.button("🚪 Log Out", use_container_width=True):
        st.query_params.clear()
        st.session_state["logged_in"] = False
        st.session_state["role"] = None
        st.session_state["name"] = None
        st.rerun()
        
    # Router
    if role == "Admin":
        render_admin()
    elif role == "Viewer":
        run_viewer_screen()
    else:
        # Captain roles (Sawon, Dragleeoo, Swapneel, Harshit Agarwal)
        global_status = db.one("SELECT value FROM auction_state WHERE key = 'auction_status'")
        status_val = global_status["value"] if global_status else "PRE_AUCTION"
        
        if status_val == "PRE_AUCTION":
            # Do not auto-refresh during pre-auction selections to avoid input focus loss
            render_captain()
        else:
            run_live_captain_screen()

def launched_by_streamlit() -> bool:
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
    except Exception:
        return False
    return get_script_run_ctx() is not None

def run_with_streamlit_cli() -> None:
    from streamlit.web import cli as streamlit_cli
    sys.argv = [
        "streamlit",
        "run",
        str(Path(__file__).resolve()),
        "--server.port",
        "8501",
        "--server.headless",
        "true",
    ]
    raise SystemExit(streamlit_cli.main())

if __name__ == "__main__":
    if launched_by_streamlit():
        main()
    else:
        run_with_streamlit_cli()