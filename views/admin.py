from numpy import empty
import streamlit as st
import json
import random
import re
from html import escape
from pathlib import Path
from config import format_inr, CAPTAINS, MARQUEE_BASE_PRICE
import db
import models
from models import is_captain_player
import rules_engine
from db import connect, closing, get_state, set_state, init_db
import ui_components


import concurrent.futures

@st.fragment(run_every="10s")
def admin_smart_watcher():
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        f_live = executor.submit(models.get_live_bid_state)
        f_bets = executor.submit(lambda: len(models.rows("SELECT id FROM pre_auction_bets")))
        f_silent = executor.submit(lambda: len(models.rows("SELECT player_id, captain_name FROM silent_bids")))
        
        live_state = f_live.result()
        bets_count = f_bets.result()
        silent_bids_count = f_silent.result()
        
    current_hash = hash(str(live_state) + str(bets_count) + str(silent_bids_count))
    if st.session_state.get("admin_hash") != current_hash:
        if "admin_hash" in st.session_state:
            st.session_state["admin_hash"] = current_hash
            st.rerun()
        else:
            st.session_state["admin_hash"] = current_hash

def render_admin_panel():
    st.title("🎛️ LCL 2026 Admin Control Panel")
    
    # Quick Watcher Fragment
    admin_smart_watcher()
    
    # 1. State / Phase Control
    st.header("🎯 Auction Phase Control")
    with connect() as con:
        current_phase = get_state(con, "global_status")
        current_pid = get_state(con, "live_current_player_id")
    
    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        if st.button("⏸️ Reset to IDLE", use_container_width=True):
            set_state("global_status", "IDLE")
            set_state("live_current_player_id", 0)
            models.execute("UPDATE live_bid SET current_bid = 0, highest_bidder_team = NULL, rtm_status = 'NONE'")
            st.rerun()
    with col2:
        if st.button("👑 Marquee Phase", use_container_width=True):
            set_state("global_status", "MARQUEE_DRAFT")
            st.rerun()
    with col3:
        if st.button("⚡ Live Auction", use_container_width=True):
            set_state("global_status", "LIVE_AUCTION")
            st.rerun()
    with col4:
        if st.button("🤫 Silent Phase", use_container_width=True):
            set_state("global_status", "SILENT_BIDS")
            st.rerun()
    with col5:
        if st.button("🏁 End Auction", use_container_width=True):
            set_state("global_status", "COMPLETED")
            st.rerun()

    st.write(f"**Current System Phase:** `{current_phase}` | **Live Player ID:** `{current_pid}`")
    
    st.html("<hr style='border-color: rgba(255,255,255,0.08);'>")
    
    # 2. Live Auction Action / Bidding Console
    if current_phase in ["LIVE_AUCTION", "MARQUEE_DRAFT"]:
        st.header("🔨 Active Player & Live Bid Console")
        
        # Select player to put on block if idle
        all_players = models.rows("SELECT id, name, category, base_price, status FROM players ORDER BY name ASC")
        available_players = [p for p in all_players if p["status"] == "AVAILABLE"]
        
        if current_pid == 0:
            st.subheader("Bring Player to Auction Block")
            if not available_players:
                st.info("No available players remaining!")
            else:
                p_options = {f"{p['name']} ({p['category']} - {format_inr(p['base_price'])})": p['id'] for p in available_players}
                selected_p_text = st.selectbox("Select Player", list(p_options.keys()))
                chosen_pid = p_options[selected_p_text]
                
                col_b1, col_b2 = st.columns(2)
                with col_b1:
                    if st.button("🚀 Push to Live Block", type="primary", use_container_width=True):
                        chosen_player = [p for p in available_players if p['id'] == chosen_pid][0]
                        set_state("live_current_player_id", chosen_pid)
                        # Reset live bid state to baseline
                        models.execute("UPDATE live_bid SET current_bid = ?, highest_bidder_team = NULL, rtm_status = 'NONE'", (chosen_player["base_price"],))
                        st.success(f"{chosen_player['name']} is now live!")
                        st.rerun()
        else:
            # Active live block controls
            chosen_player = models.row("SELECT * FROM players WHERE id = ?", (current_pid,))
            live_bid = models.get_live_bid_state()
            
            st.markdown(f"### 🛑 On Block: **{chosen_player['name']}** ({chosen_player['category']})")
            st.write(f"Base Price: **{format_inr(chosen_player['base_price'])}**")
            
            st.html("<div style='background-color:rgba(255,255,255,0.03); padding:15px; border-radius:5px; margin-bottom:15px;'>")
            st.write(f"Current Live Bid: **{format_inr(live_bid['current_bid'])}**")
            st.write(f"Highest Bidder Team: **{live_bid['highest_bidder_team'] or 'None'}**")
            st.write(f"RTM Status: **{live_bid['rtm_status']}**")
            st.html("</div>")
            
            # Form to update or override current bid state
            with st.form("bid_override_form"):
                st.subheader("Manual Bid / State Override")
                teams_list = [t["name"] for t in models.rows("SELECT name FROM teams")]
                
                ov_bid = st.number_input("Override Current Bid Amount (INR)", min_value=0, value=int(live_bid["current_bid"]), step=50000)
                ov_team = st.selectbox("Highest Bidder Team", ["None"] + teams_list, index=0 if not live_bid["highest_bidder_team"] else teams_list.index(live_bid["highest_bidder_team"])+1)
                ov_rtm = st.selectbox("RTM Status Override", ["NONE", "ELIGIBLE", "MATCHED", "DECLINED"], index=["NONE", "ELIGIBLE", "MATCHED", "DECLINED"].index(live_bid["rtm_status"]))
                
                if st.form_submit_button("💾 Save Bid State Override", use_container_width=True):
                    final_team = None if ov_team == "None" else ov_team
                    models.execute("UPDATE live_bid SET current_bid = ?, highest_bidder_team = ?, rtm_status = ?", (ov_bid, final_team, ov_rtm))
                    st.success("Live bid engine state updated successfully!")
                    st.rerun()
            
            # Adjudication Buttons
            st.subheader("⚖️ Finalize Sale Adjudication")
            chosen_pid = chosen_player["id"]
            base_price = chosen_player["base_price"]
            winning_bid = live_bid["current_bid"]
            tname = live_bid["highest_bidder_team"]
            
            col_adj1, col_adj2, col_adj3 = st.columns(3)
            
            with col_adj1:
                # Base Price Award Logic (Marquee Phase style choice)
                st.markdown("**Option A: Award directly at Base**")
                teams_eligible = models.rows("SELECT name FROM teams")
                tname_base = st.selectbox("Assign Team (Base)", [t["name"] for t in teams_eligible], key="base_team_sel")
                
                if st.button("🤝 Award at Base Price", key=f"base_award_{chosen_pid}", use_container_width=True):
                    # 🏁 CHANGE 4A: Atomic transactional refactor
                    db.finalize_sale(chosen_pid, tname_base, base_price, "BASE_PRICE")
                    st.success(f"Sold {chosen_player['name']} to {tname_base} for {format_inr(base_price)}!")
                    st.rerun()
                    
            with col_adj2:
                # Standard Auction Winner
                st.markdown("**Option B: Standard Sale**")
                if not tname:
                    st.warning("No highest bidder yet.")
                else:
                    st.write(f"Sell to **{tname}** for **{format_inr(winning_bid)}**")
                    if st.button("🔨 SOLD", key=f"sold_{chosen_pid}", type="primary", use_container_width=True):
                        # 🏁 CHANGE 4B: Atomic transactional refactor
                        db.finalize_sale(chosen_pid, tname, winning_bid, "AUCTION")
                        st.success(f"Sold {chosen_player['name']} to {tname} for {format_inr(winning_bid)}!")
                        st.rerun()
                        
            with col_adj3:
                # Right to match calculation path
                st.markdown("**Option C: RTM Execution**")
                rtm_team = chosen_player.get("original_lcl_team") or chosen_player.get("prev_team")
                current_bid = live_bid["current_bid"]
                highest_bidder = live_bid["highest_bidder_team"]
                
                rtm_available = False
                if rtm_team and highest_bidder and (rtm_team != highest_bidder):
                    # Check if team actually holds an unspent RTM card
                    t_card = models.row("SELECT COUNT(*) as rtm_remaining FROM teams WHERE name = ? and rtm_used=False", (rtm_team,))
                    if t_card and t_card["rtm_remaining"] > 0:
                        rtm_available = True
                
                if not rtm_available:
                    st.info("RTM configuration not met or card exhausted.")
                else:
                    st.write(f"RTM Holder: **{rtm_team}**")
                    if st.button(f"🟢 Sell via RTM to {rtm_team}", key=f"rtm_{chosen_pid}", use_container_width=True):
                        # 🏁 CHANGE 4C: Atomic transactional refactor
                        db.finalize_sale(chosen_pid, rtm_team, current_bid, "RTM_MATCH")
                        st.success(f"Sold {chosen_player['name']} to {rtm_team} (RTM) for {format_inr(current_bid)}!")
                        st.rerun()

            if st.button("❌ Mark Player as UNSOLD", key=f"unsold_{chosen_pid}", use_container_width=True):
                models.execute("UPDATE players SET status = 'UNSOLD', sold_team = NULL, sold_price = NULL WHERE id = ?", (chosen_pid,))
                models.log_action("UNSOLD", player_id=chosen_pid, note="Passed / Unsold in live auction block")
                set_state("global_status", "IDLE")
                set_state("live_current_player_id", 0)
                st.warning(f"{chosen_player['name']} marked as UNSOLD.")
                st.rerun()

    st.html("<hr style='border-color: rgba(255,255,255,0.08);'>")
    
    # 2.5 Marquee Draft Order Configuration Engine
    if current_phase == "MARQUEE_DRAFT":
        st.header("👑 Marquee Phase Engine Setup")
        with connect() as con:
            m_order_raw = get_state(con, "marquee_draft_order")
            m_turn_idx = get_state(con, "marquee_draft_turn_index") or 0
        
        st.write(f"**Current Turn Index:** `{m_turn_idx}`")
        if m_order_raw:
            m_order = json.loads(m_order_raw)
            st.write("Current Sequence: " + " → ".join([f"**{idx}.** {c}" for idx, c in enumerate(m_order, 1)]))
            if m_turn_idx < len(m_order):
                st.info(f"Up Next to Nominate/Pick: **{m_order[m_turn_idx]}**")
            else:
                st.success("Draft order sequence complete!")
        else:
            st.warning("No draft sequence generated yet.")
            
        with st.form("marquee_sequence_form"):
            st.subheader("Generate / Override Draft Sequence")
            captains_list = list(CAPTAINS.keys())
            
            st.markdown("*Rearrange or seed captains dynamically or randomize order*")
            shuffled_caps = list(captains_list)
            
            if st.form_submit_button("🎲 Generate Random Draft Sequence"):
                random.shuffle(shuffled_caps)
                set_state("marquee_draft_order", json.dumps(shuffled_caps))
                set_state("marquee_draft_turn_index", 0)
                st.success(f"Generated Order: {shuffled_caps}")
                st.rerun()
                
        col_m1, col_m2, col_m3 = st.columns(3)
        with col_m1:
            if st.button("⬅️ Step Turn Back", use_container_width=True):
                new_idx = max(0, int(m_turn_idx) - 1)
                set_state("marquee_draft_turn_index", new_idx)
                st.rerun()
        with col_m2:
            if st.button("➡️ Advance Turn Forward", use_container_width=True):
                if m_order_raw:
                    m_len = len(json.loads(m_order_raw))
                    new_idx = min(m_len, int(m_turn_idx) + 1)
                    set_state("marquee_draft_turn_index", new_idx)
                    st.rerun()
        with col_m3:
            if st.button("🔄 Reset Turn to 0", use_container_width=True):
                set_state("marquee_draft_turn_index", 0)
                st.rerun()

        st.html("<hr style='border-color: rgba(255,255,255,0.08);'>")

    # 3. Silent Bid Consolidation Interface
    if current_phase == "SILENT_BIDS":
        st.header("🤫 Silent Bid Management Engine")
        
        silent_bids_raw = models.rows("""
            SELECT sb.*, p.name as player_name, p.category, p.base_price 
            FROM silent_bids sb
            JOIN players p ON sb.player_id = p.id
            ORDER BY p.name ASC, sb.bid_amount DESC
        """)
        
        if not silent_bids_raw:
            st.info("No silent bids submitted yet.")
        else:
            # Regroup by player
            grouped_silent = {}
            for b in silent_bids_raw:
                pid = b["player_id"]
                if pid not in grouped_silent:
                    grouped_silent[pid] = {
                        "name": b["player_name"],
                        "base_price": b["base_price"],
                        "bids": []
                    }
                grouped_silent[pid]["bids"].append(b)
                
            st.subheader("Review Submitted Secret Bids")
            for pid, pdata in grouped_silent.items():
                with st.expander(f"📦 Bids for {pdata['name']} (Base: {format_inr(pdata['base_price'])})"):
                    # Sorted naturally by bid amount desc
                    sorted_bids = pdata["bids"]
                    
                    # Highlight winning candidate
                    top_bid = sorted_bids[0]
                    st.success(f"🥇 Highest Bidder: **{top_bid['captain_name']}** with **{format_inr(top_bid['bid_amount'])}**")
                    
                    # Check for collisions/ties
                    is_tied = False
                    if len(sorted_bids) > 1 and sorted_bids[1]["bid_amount"] == top_bid["bid_amount"]:
                        is_tied = True
                        st.error(f"⚠️ TIE DETECTED! Multiple bids found at {format_inr(top_bid['bid_amount'])}")
                    
                    # Render small summary table
                    for b in sorted_bids:
                        st.write(f"- **{b['captain_name']}**: {format_inr(b['bid_amount'])} *(Submitted: {b['timestamp']} )*")
                        
                    # Action blocks
                    player_id = pid
                    silent_winner = top_bid["captain_name"]
                    silent_bid = top_bid["bid_amount"]
                    
                    if is_tied:
                        st.warning("Please resolve tie manually via override console if necessary before awarding.")
                    
                    if st.button(f"🏆 Award to {silent_winner} at {format_inr(silent_bid)}", key=f"award_silent_{player_id}"):
                        # 🏁 CHANGE 4D: Atomic transactional refactor
                        db.finalize_sale(player_id, silent_winner, silent_bid, "SILENT_BID")
                        st.success(f"Successfully awarded player to {silent_winner}!")
                        st.rerun()

        if st.button("🗑️ Clear ALL Submitted Silent Bids", type="secondary", use_container_width=True):
            models.execute("DELETE FROM silent_bids")
            st.warning("All silent bid logs purged.")
            st.rerun()

        st.html("<hr style='border-color: rgba(255,255,255,0.08);'>")

    # 4. Global Roster Realignment & Purse Overrides
    st.header("🛠️ Global Team Balance Overrides")
    teams_data = models.rows("SELECT * FROM teams ORDER BY name ASC")
    
    for t in teams_data:
        with st.expander(f"🛡️ Modify {t['name']} (Purse: {format_inr(t['purse_remaining'])})"):
            with st.form(f"team_override_form_{t['name']}"):
                new_purse = st.number_input("Purse Balance Remaining (INR)", value=int(t["purse_remaining"]), step=100000)
                new_rtm = st.number_input("RTM Cards Remaining", min_value=0, max_value=5, value=int(t["rtm_remaining"]))
                
                if st.form_submit_button(f"Update parameters for {t['name']}"):
                    models.execute("UPDATE teams SET purse_remaining = ?, rtm_remaining = ? WHERE name = ?", (new_purse, new_rtm, t["name"]))
                    st.success(f"Parameters for {t['name']} adjusted explicitly!")
                    st.rerun()

    st.html("<hr style='border-color: rgba(255,255,255,0.08);'>")

    # 5. Pre-Auction Draft Pick Bets Console
    st.header("🎯 Pre-Auction Bets Verification Registry")
    bets = models.rows("""
        SELECT pab.*, p.name as player_name, p.base_price 
        FROM pre_auction_bets pab
        JOIN players p ON pab.player_id = p.id
        ORDER BY pab.captain_name ASC
    """)
    if not bets:
        st.info("No draft choices predicted in Registry yet.")
    else:
        for b in bets:
            st.write(f"- **{b['captain_name']}** guessed **{b['player_name']}** slot multiplier bracket at index `{b['slot_index']}`")
        if st.button("🗑️ Purge Predictions Registry", use_container_width=True):
            models.execute("DELETE FROM pre_auction_bets")
            st.success("Registry cleared clean.")
            st.rerun()

    st.html("<hr style='border-color: rgba(255,255,255,0.08);'>")

    # 6. Audit Trail Transaction Reversal Safe Rollbacks
    st.header("🔄 Transaction Rollback Ledger")
    st.markdown("Revert the *most recent single complete player sale transaction* safely to completely restore purse balances and clear roster locks.")
    
    with connect() as con:
        last_sale = models.row("SELECT * FROM audit_log WHERE action = 'SOLD' ORDER BY id DESC LIMIT 1")
        if last_sale:
            p_id = last_sale["player_id"]
            t_name = last_sale["team_name"]
            refund_amt = last_sale["amount"]

            # Safe transactional reversal block
            models.execute("UPDATE players SET status = 'AVAILABLE', sold_team = NULL, sold_price = NULL WHERE id = ?", (p_id,))
            models.execute("UPDATE teams SET purse_remaining = purse_remaining + ? WHERE name = ?", (refund_amt, t_name))
            models.execute("DELETE FROM audit_log WHERE id = ?", (last_sale["id"],))

            related_entries = models.rows("SELECT * FROM audit_log WHERE player_id = ? AND action IN ('BONUS', 'TAX') ORDER BY id DESC", (p_id,))
            for entry in related_entries:
                if entry["action"] == "BONUS":
                    models.execute("UPDATE teams SET purse_remaining = purse_remaining - ? WHERE name = ?", (entry["amount"], entry["team_name"]))
                elif entry["action"] == "TAX":
                    models.execute("UPDATE teams SET purse_remaining = purse_remaining + ? WHERE name = ?", (entry["amount"], entry["team_name"]))
                models.execute("DELETE FROM audit_log WHERE id = ?", (entry["id"],))

            st.success(f"Successfully reverted sale of player! Refunded {refund_amt} back to {t_name}.")
            st.rerun()
        else:
            st.warning("No recent sales transactions recorded to rollback.")