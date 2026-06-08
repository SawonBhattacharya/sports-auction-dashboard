import streamlit as st
from config import PASSCODES, CAPTAINS
from ui_components import inject_css, render_footer

from ui_components import (
    inject_css,
    render_footer,
    render_league_poster
)

def render_login():
    inject_css()

    render_league_poster()

    st.html(
        """
        ...
        """
    )
    
def render_login() -> None:
    inject_css()
    
    st.html(
        """
        <div style="display:flex; justify-content:center; align-items:center; flex-direction:column; margin-top: 60px;">
            <div style="font-size: 2.2rem; font-weight: 800; color: #ffffff; letter-spacing: 1px; margin-bottom: 5px;">🏆 LCL AUCTION 2026</div>
            <div style="font-size: 1rem; color: #9ca3af; margin-bottom: 30px;">Sports Auction Control & Projection Portal</div>
        </div>
        """
    )
    
    col1, col2, col3 = st.columns([1, 1.5, 1])
    with col2:
        st.html('<div class="glass-card">')
        st.subheader("Sign In")
        
        role_options = ["Viewer", "Admin", "Sawon", "Dragleeoo", "Swapneel", "Harshit Agarwal"]
        selected_role = st.selectbox("Select Your Role", role_options)
        
        passcode = st.text_input("Enter Passcode", type="password")
        
        if st.button("Access Dashboard", use_container_width=True):
            # Try exact match first (e.g. "Admin")
            expected = PASSCODES.get(selected_role)
            # Fallback to case-insensitive if exact match fails
            if expected is None:
                expected = next((v for k, v in PASSCODES.items() if k.lower() == selected_role.lower()), None)
            
            # Simple check
            if expected is not None and passcode == expected:
                st.query_params["role"] = selected_role
                st.session_state["logged_in"] = True
                st.session_state["role"] = selected_role
                st.session_state["name"] = selected_role
                st.success("Access Granted! Redirecting...")
                st.rerun()
            else:
                st.error("❌ Incorrect Passcode. Please try again.")
        
        st.html('</div>')
        
    render_footer()
