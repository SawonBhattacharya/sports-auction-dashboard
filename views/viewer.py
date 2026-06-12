import streamlit as st
from config import format_inr
import models
from db import connect, closing, get_state
from ui_components import render_header, render_footer, render_spin_wheel, inject_css, render_team_progress_grid, render_team_squad_rows, render_player_card, render_sale_celebration,render_league_poster
import json

import concurrent.futures

@st.fragment(run_every="2s")
def viewer_live_console_fragment():
    """
    WHY: This fragment runs every 2 seconds but ONLY re-executes ~15 lines of code
    and fires 1-2 DB queries (get_live_bid_state + global_status) instead of 40+.
    The heavy Squad Roster and Top Header sections are NOT inside this fragment,
    so they are skipped on every bid tick. They only re-render when the fragment
    triggers a full st.rerun() — which only happens when a player is SOLD.
    """
    live_state = models.get_live_bid_state()
    global_status = models.get_global_status()

    # Build a lightweight signature: only current_bid + phase + bidder change on a bid
    bid_sig = (
        live_state["current_bid"] if live_state else 0,
        live_state["phase"] if live_state else "",
        live_state["current_bidder"] if live_state else "",
        global_status,
    )

    prev_sig = st.session_state.get("viewer_bid_sig")
    st.session_state["viewer_bid_sig"] = bid_sig

    if prev_sig is None:
        # First load — do nothing (page will already render fully below)
        return

    if bid_sig == prev_sig:
        return  # Nothing changed, skip render

    # Something changed. If a SOLD event just happened, do a full page rerun
    # (this refreshes the heavy Squad Rosters and Purse Header).
    # For a simple bid change, just rerun the fragment itself (default behaviour).
    prev_status = st.session_state.get("viewer_global_status_prev", global_status)
    st.session_state["viewer_global_status_prev"] = global_status
    player_just_sold = (
        prev_sig[1] in ("RTM_DECIDE", "RTM_REVISE", "LAST_BID", "BIDDING")
        and live_state is None  # live_bid_state cleared = SOLD
    )
    if player_just_sold:
        # Trigger full page rerun to refresh Purse Header + Squad Rosters
        st.rerun(scope="app")
    # Otherwise fragment reruns itself automatically — no full page reload needed

def render_viewer() -> None:
    viewer_live_console_fragment()  # Lightweight 2s watcher (fragment-isolated)
    render_league_poster()
    inject_css()
    render_sale_celebration()
    
    # 1. Fetch live state from DB concurrently
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        f_live = executor.submit(models.get_live_bid_state)
        f_glob = executor.submit(models.get_global_status)
        f_top = executor.submit(models.rows, "SELECT name, sold_team, sold_price FROM players WHERE status = 'SOLD' ORDER BY sold_price DESC LIMIT 5")
        f_logs = executor.submit(models.rows, "SELECT note, created_at FROM audit_log ORDER BY id DESC LIMIT 8")
        
        live_state = f_live.result()
        global_status = f_glob.result()
        top_players = f_top.result()
        logs = f_logs.result()
    
    # Render the top captain headers
    # We pass active bidder if there is one
    render_header(f"Public Viewer ({global_status.replace('_', ' ')})")
    
    # 2. Layout: Left Column (Active Player / Spin Wheel), Right Column (Standings & Leaderboards)
    col1, col2 = st.columns([2, 1.2])
    
    with col1:
        # Check if a Spin Wheel is actively running (triggered by Admin)
        spin_target_id = None
        with connect() as con:
            spin_target_id = get_state(con, "wheel_target_player_id")
            
        if spin_target_id:
            # We are spinning!
            player = models.get_player(spin_target_id)
            if player:
                st.html('<div class="glass-card" style="text-align: center;">')
                st.subheader("🎯 Spin Wheel Draw in Progress...")
                
                # Fetch all available player names to populate the wheel segments
                available = models.get_available_players()
                from models import is_captain_player
                player_names = [p["name"] for p in available if p["id"] != spin_target_id and not p.get("is_marquee") and not is_captain_player(p["name"])]
                # Put the target player in a random spot or at the end
                player_names = player_names[:7] + [player["name"]]
                
                render_spin_wheel(player_names, player["name"], player["id"])
                st.html('</div>')
        
        elif live_state:
            # We have an active player on the auction block!
            player = models.get_player(live_state["player_id"])
            if player:
                render_player_card(player)
                
                st.html('<div class="glass-card">')
                
                # Current Bid
                curr_bid = live_state["current_bid"]
                bidder = live_state["current_bidder"] or "No bids placed yet"
                st.markdown(f"#### Current Bid ({bidder})<br><span style='font-size:2.2rem; font-weight:800; color:#22c55e;'>{format_inr(curr_bid) if curr_bid > 0 else 'N/A'}</span>", unsafe_allow_html=True)
                
                # Live State phase workflow banner
                phase = live_state["phase"]
                if phase == 'RTM_PROMPT':
                    st.warning("⚡ Standard bidding complete! Checking for RTM+ triggers...")
                elif phase == 'RTM_DECIDE':
                    st.info(f"⏳ Match or Decline: Captain {live_state['rtm_captain']} deciding on revised bid {format_inr(live_state['revised_bid'])}...")
                elif phase == 'LAST_BID':
                    st.error("🔒 Standard bidding frozen! Silent Last Bid Joker input active...")
                    
                st.html('</div>')
        else:
            # No active player
            if global_status == 'PRE_AUCTION':
                st.html('<div class="glass-card" style="text-align: center; padding: 50px 20px;">')
                st.info("🕒 Pre-Auction Setup Phase is active. Waiting for Admin to lock setups.")
                st.html('</div>')
            else:
                available = models.get_available_players()
                from models import is_captain_player
                available = [p for p in available if not p.get("is_marquee") and not is_captain_player(p["name"])]
                if available:
                    player_names = [p["name"] for p in available[:8]]
                    target = player_names[0]
                    st.html('<div class="glass-card" style="text-align: center;">')
                    st.subheader("🎡 Waiting for Next Draw...")
                    render_spin_wheel(player_names, target, "", auto_spin=False)
                    st.html('</div>')
                else:
                    st.html('<div class="glass-card" style="text-align: center; padding: 50px 20px;">')
                    st.info("🕒 All players have been drawn.")
                    st.html('</div>')
            
        # 3. Squad Progress Silhouettes Grid
        st.html('<div class="glass-card">')
        st.subheader("📋 Team Build Progress Grid")
        render_team_progress_grid(models, is_live=True)
        render_team_squad_rows(models)
        st.html('</div>')
        
    with col2:
        # 3.5 Marquee Draft Order
        with connect() as con:
            m_order_raw = get_state(con, "marquee_draft_order")
        if m_order_raw:
            m_order = json.loads(m_order_raw)
            st.html('<div class="glass-card">')
            st.subheader("👑 Marquee Draft Order")
            for idx, c in enumerate(m_order, 1):
                st.write(f"**{idx}.** {c}")
            st.html('</div>')
        # 4. Top 5 Highest Grossing Players
        st.html('<div class="glass-card">')
        st.subheader("🔥 Top 5 Highest Grossing")
        
        if top_players:
            for idx, p in enumerate(top_players, 1):
                st.markdown(
                    f"**{idx}. {p['name']}** \n"
                    f"└ {p['sold_team']} · <span style='color:#22c55e; font-weight:bold;'>{format_inr(p['sold_price'])}</span>",
                    unsafe_allow_html=True
                )
        else:
            st.info("No players sold yet.")
        st.html('</div>')
        
        # 5. Live Bidding Log
        st.html('<div class="glass-card">')
        st.subheader("📰 Live Audit Log")
        
        if logs:
            from datetime import datetime, timezone, timedelta
            ist_tz = timezone(timedelta(hours=5, minutes=30))
            
            for l in logs:
                try:
                    # Parse UTC isoformat
                    utc_str = l["created_at"]
                    if utc_str.endswith("Z"):
                        utc_str = utc_str[:-1] + "+0000"
                    dt = datetime.strptime(utc_str, "%Y-%m-%dT%H:%M:%S%z")
                    # Convert to IST
                    dt_ist = dt.astimezone(ist_tz)
                    time_str = dt_ist.strftime("%H:%M")
                except Exception:
                    time_str = l["created_at"].split('T')[-1][:-1][:5]
                    
                st.markdown(f"`[{time_str}]` {l['note']}")
        else:
            st.info("Audit log is empty.")
        st.html('</div>')
        
    render_footer()