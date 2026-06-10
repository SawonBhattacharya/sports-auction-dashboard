import streamlit as st
import sys
from pathlib import Path
import os
import streamlit.components.v1 as components

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

/* 2. Hide native sidebar toggle (replaced by custom JS toggle) */
[data-testid="stSidebarCollapseButton"],
[data-testid="collapsedControl"],
[data-testid="stSidebarCollapsedControl"] {
    opacity: 0 !important;
    position: absolute !important;
    z-index: -100 !important;
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
        
    # ── Custom Sidebar Toggle Button (injected into parent DOM via JS) ──
    components.html("""
    <script>
    (function() {
        const pd = window.parent.document;

        // Clean up any previous instance on Streamlit rerun
        const old = pd.getElementById('lcl-sidebar-toggle');
        if (old) old.remove();

        // SVG icons
        const MENU = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="4" y1="6" x2="20" y2="6"/><line x1="4" y1="12" x2="20" y2="12"/><line x1="4" y1="18" x2="20" y2="18"/></svg>';
        const CLOSE = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="6" y1="6" x2="18" y2="18"/><line x1="6" y1="18" x2="18" y2="6"/></svg>';

        const btn = pd.createElement('button');
        btn.id = 'lcl-sidebar-toggle';
        btn.setAttribute('aria-label', 'Toggle sidebar');
        Object.assign(btn.style, {
            position:  'fixed',
            top:       '14px',
            left:      '14px',
            zIndex:    '1000001',
            width:     '40px',
            height:    '40px',
            background:'linear-gradient(135deg,rgba(31,41,55,.95),rgba(17,24,39,.98))',
            border:    '1px solid rgba(255,255,255,.18)',
            borderRadius:'10px',
            color:     '#e5e7eb',
            cursor:    'pointer',
            display:   'flex',
            alignItems:'center',
            justifyContent:'center',
            backdropFilter:'blur(12px)',
            WebkitBackdropFilter:'blur(12px)',
            boxShadow: '0 4px 15px rgba(0,0,0,.4)',
            transition:'all .3s cubic-bezier(.4,0,.2,1)',
            padding:   '0',
            outline:   'none'
        });

        function isOpen() {
            const sb = pd.querySelector('[data-testid="stSidebar"]');
            if (!sb) return false;
            const exp = sb.getAttribute('aria-expanded');
            if (exp !== null) return exp === 'true';
            return sb.getBoundingClientRect().width > 100;
        }

        function refresh() {
            const open = isOpen();
            btn.innerHTML = open ? CLOSE : MENU;
            btn.title     = open ? 'Close menu' : 'Open menu';
        }

        btn.addEventListener('mouseenter', function() {
            Object.assign(this.style, {
                background:'linear-gradient(135deg,rgba(34,197,94,.25),rgba(22,163,74,.3))',
                borderColor:'#22c55e', transform:'scale(1.08)',
                boxShadow:'0 4px 20px rgba(34,197,94,.3)'
            });
        });
        btn.addEventListener('mouseleave', function() {
            Object.assign(this.style, {
                background:'linear-gradient(135deg,rgba(31,41,55,.95),rgba(17,24,39,.98))',
                borderColor:'rgba(255,255,255,.18)', transform:'scale(1)',
                boxShadow:'0 4px 15px rgba(0,0,0,.4)'
            });
        });

        btn.addEventListener('click', function() {
            const sels = [
                '[data-testid="stSidebarCollapseButton"] button',
                'button[data-testid="stBaseButton-headerNoPadding"]',
                '[data-testid="collapsedControl"] button',
                '[data-testid="stSidebarCollapsedControl"] button',
                '[data-testid="stSidebarCollapseButton"]' // fallback
            ];
            for (const s of sels) {
                const n = pd.querySelector(s);
                if (n) { 
                    n.click(); 
                    break; 
                }
            }
            setTimeout(refresh, 350);
        });

        pd.body.appendChild(btn);
        refresh();

        // Watch sidebar attribute changes
        const sb = pd.querySelector('[data-testid="stSidebar"]');
        if (sb) {
            new MutationObserver(function() { setTimeout(refresh, 50); })
                .observe(sb, { attributes: true, subtree: false });
        }
        // Backup poll
        setInterval(refresh, 500);
    })();
    </script>
    """, height=0)
        
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