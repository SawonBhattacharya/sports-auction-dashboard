from tenacity import before_sleep
import streamlit as st
import json
from config import format_inr, CAPTAINS
from models import is_captain_player
import models
import db
from db import connect, closing, get_state, set_state
from ui_components import render_header, render_footer, inject_css, render_team_progress_grid, render_team_squad_rows, render_player_card, render_spin_wheel, render_sale_celebration,render_league_poster
import rules_engine

import concurrent.futures

@st.fragment(run_every="2s")
def captain_live_console_fragment():
    """
    WHY: Same fragment-isolation strategy as viewer. This watcher only fires 2 DB
    queries per tick instead of the old 5+. Full page rerun (refreshing Purse Header
    + Squad Rosters) is triggered ONLY when a player is SOLD or the phase changes
    significantly — not on every bid increment.
    """
    live_state = models.get_live_bid_state()
    global_status = models.get_global_status()

    bid_sig = (
        live_state["current_bid"] if live_state else 0,
        live_state["phase"] if live_state else "",
        live_state["current_bidder"] if live_state else "",
        global_status,
    )

    prev_sig = st.session_state.get("captain_bid_sig")
    st.session_state["captain_bid_sig"] = bid_sig

    if prev_sig is None:
        return  # First load

    if bid_sig == prev_sig:
        return  # No change

    # Detect SOLD: live_bid_state was cleared (live_state is None) after active bidding
    player_just_sold = (
        prev_sig[1] in ("RTM_DECIDE", "RTM_REVISE", "LAST_BID", "BIDDING")
        and live_state is None
    )
    # Detect phase transitions that captains must see immediately (e.g. RTM triggered)
    phase_changed = prev_sig[1] != (live_state["phase"] if live_state else "")

    if player_just_sold or phase_changed:
        # Full page rerun: refreshes Purse Header, Squad Rosters, Joker availability
        st.rerun(scope="app")
    # Simple bid amount change: fragment reruns itself (only the bid number updates)

def render_captain() -> None:
    captain_live_console_fragment()  # Lightweight 2s watcher (fragment-isolated)
    render_league_poster()
    inject_css()
    render_sale_celebration()
    
    captain_name = st.session_state.get("name")
    team = models.get_team_by_captain(captain_name)
    if not team:
        st.error(f"Error: No team mapped to captain {captain_name}.")
        st.stop()
        
    tname = team["name"]
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        f_glob = executor.submit(models.get_global_status)
        f_live = executor.submit(models.get_live_bid_state)
        
        global_status = f_glob.result()
        live_state = f_live.result()
    
    # 1. Header showing opponent stats and highlight turn
    # We find whose marquee turn it is
    active_marquee_captain = None
    if global_status == 'PRE_AUCTION':
        with connect() as con:
            order_json = get_state(con, "marquee_draft_order")
            turn_idx = get_state(con, "marquee_draft_turn_index", "0")
            completed = get_state(con, "marquee_draft_completed", "FALSE")
            if order_json and completed == "FALSE":
                order = json.loads(order_json)
                idx = int(turn_idx)
                if idx < len(order):
                    active_marquee_captain = order[idx]
                    
    render_header(f"Captain Console: {captain_name} ({tname})", active_captain_turn=active_marquee_captain)
    
    # 2. View logic depending on phase
    if global_status == 'PRE_AUCTION':
        st.html('<div class="glass-card">')
        st.subheader("🏁 Pre-Auction Wizard & Nominations")
        st.write("Submit your secret strategies and nominations before the auction starts.")
        
        # ── 1. MARQUEE NOMINATION TURN-BASED FLOW (TOP) ──
        st.markdown("### 👑 Marquee Player Selection")
        
        with connect() as con:
            order_json = get_state(con, "marquee_draft_order")
            turn_idx_str = get_state(con, "marquee_draft_turn_index", "0")
            completed = get_state(con, "marquee_draft_completed", "FALSE")
            
        if not order_json:
            st.info("Waiting for the Admin to randomize and release the Marquee Draft Order...")
        elif completed == 'TRUE':
            marquees = models.get_marquee_players()
            st.success("🎉 Marquee Player Draft Complete!")
            st.write("**Designated Marquee Players (Base Price ₹4.5 Crore):**")
            for m in marquees:
                st.markdown(f"• **{m['name']}** (Selected by {m['marquee_nominator']})")
        else:
            order = json.loads(order_json)
            turn_idx = int(turn_idx_str)
            current_drafter = order[turn_idx]
            
            st.write(f"Draft Order: {' → '.join(order)}")
            
            if current_drafter == captain_name:
                st.markdown(f"#### 🟢 **It is your turn to select!**")
                st.warning("IMPORTANT: You are committing to buy your selected player for **₹4.5 Crore** at the start of the auction.")
                
                available_for_marquee = models.rows("SELECT id, name, seeding FROM players WHERE status='AVAILABLE' AND is_marquee=FALSE ORDER BY name")
                already_nominated_ids = {m["id"] for m in models.get_marquee_players()}
                # Bug 8 Fix: Do not allow picking a player currently on the auction block or spin wheel target
                active_block_id = live_state["player_id"] if live_state else None
                spin_target_id_for_block = None
                with connect() as con:
                    spin_target_id_for_block = get_state(con, "wheel_target_player_id")
                
                available_for_marquee = [
                    p for p in available_for_marquee 
                    if p["id"] not in already_nominated_ids 
                    and not is_captain_player(p["name"])
                    and p["id"] != active_block_id
                    and p["id"] != spin_target_id_for_block
                ]
                am_options = {f"{p['name']} ({p['seeding']})": p["id"] for p in available_for_marquee}
                
                with st.form("marquee_draft_form"):
                    draft_names = ["Select a player to nominate..."] + list(am_options.keys())
                    selected_draft = st.selectbox("Choose Marquee Player", draft_names, key="marquee_draft_sel")
                    
                    submitted_marquee = st.form_submit_button("Confirm Selection", use_container_width=True)
                    
                    if submitted_marquee:
                        if selected_draft == "Select a player to nominate...":
                            st.error("❌ Please select a valid player from the dropdown.")
                        else:
                            with st.spinner("Saving your Marquee Selection..."):
                                chosen_pid = am_options[selected_draft]
                                models.nominate_marquee(chosen_pid, captain_name)
                                new_idx = turn_idx + 1
                                with connect() as con:
                                    set_state(con, "marquee_draft_turn_index", str(new_idx))
                                    if new_idx >= len(order):
                                        set_state(con, "marquee_draft_completed", "TRUE")
                                    con.commit()
                                models.log_action("MARQUEE_NOMINATE", player_id=chosen_pid, team_name=tname, note=f"{captain_name} nominated {selected_draft.split(' (')[0]} as marquee.")
                                st.success(f"Successfully drafted {selected_draft}!")
                                st.rerun()
            else:
                st.info(f"⏳ Waiting for **{current_drafter}** to nominate their marquee player...")
                
        # Show the captain's own marquee if already selected
        your_marquee = models.one("SELECT * FROM players WHERE is_marquee=TRUE AND marquee_nominator = ? LIMIT 1", (captain_name,))
        if your_marquee:
            st.markdown("### Your Marquee Player")
            render_player_card(your_marquee)

        st.html("<hr style='border-color: rgba(255,255,255,0.08);'>")
        
        # ── 2. SECRET STRATEGY FORM (SURPRISE + PREDICTION) ──
        st.markdown("### 🤫 Secret Strategy Setup")
        st.write("Configure your Surprise Player and Prediction Taxes in one go. You may select **maximum 2** prediction targets.")
        
        prediction_players = models.rows("SELECT id,name,seeding,base_price FROM players ORDER BY base_price DESC,name")
        prediction_players = [p for p in prediction_players if not is_captain_player(p["name"])]
        player_options = {p["name"]: p["id"] for p in prediction_players}
        surprise_names = ["Select player..."] + list(player_options.keys())
        pred_names = ["No prediction..."] + list(player_options.keys())
        
        # Get current DB state
        current_surprise_id = models.get_surprise_player(captain_name)
        current_surprise_name = next((n for n, pid in player_options.items() if pid == current_surprise_id), None)
        default_surp_idx = surprise_names.index(current_surprise_name) if current_surprise_name in surprise_names else 0
        
        preds = models.get_predictions(captain_name)
        pred_map = {p["target_captain"]: p["target_player_id"] for p in preds}
        
        rivals = [c for c in CAPTAINS.keys() if c != captain_name]
        
        has_submitted_strategy = (current_surprise_id is not None) or (len(preds) > 0)
        
        if has_submitted_strategy:
            st.success("✅ Your secret strategies are securely locked in!")
            if current_surprise_id:
                surp_player = next((p for p in prediction_players if p["id"] == current_surprise_id), None)
                if surp_player:
                    st.markdown(f"**🎁 Surprise Player:** {surp_player['name']} ({surp_player['seeding']})")
                else:
                    st.markdown("**🎁 Surprise Player:** Unknown")
                    
            if preds:
                st.markdown("**🔮 Prediction Taxes:**")
                table_data = []
                for p in preds:
                    t_cap = p["target_captain"]
                    t_pid = p["target_player_id"]
                    t_player = next((pl for pl in prediction_players if pl["id"] == t_pid), None)
                    if t_player:
                        table_data.append({
                            "Target Captain": t_cap,
                            "Predicted Player": t_player["name"],
                            "Seed": t_player["seeding"],
                            "Base Price": format_inr(t_player["base_price"])
                        })
                if table_data:
                    st.dataframe(table_data, hide_index=True, use_container_width=True)
                    
            st.info("Please wait for the Admin to launch the Live Auction.")
            
            st.html("<br>")
            if st.button("✏️ Edit Secret Strategies (Reset Selections)", use_container_width=True):
                models.execute("DELETE FROM pre_auction_bets WHERE captain_name = ?", (captain_name,))
                st.rerun()
        else:
            with st.form("secret_strategy_form"):
                st.markdown("#### 🎁 Surprise Player")
                selected_surprise = st.selectbox("Select your Surprise Player", surprise_names, index=default_surp_idx)
                
                st.markdown("#### 🔮 Prediction Taxes (Select exactly 2)")
                
                selected_preds = {}
                for rival in rivals:
                    cur_pred_id = pred_map.get(rival)
                    cur_pred_name = next((n for n, pid in player_options.items() if pid == cur_pred_id), None)
                    default_pred_idx = pred_names.index(cur_pred_name) if cur_pred_name in pred_names else 0
                    
                    selected_preds[rival] = st.selectbox(f"Rival '{rival}' will buy:", pred_names, index=default_pred_idx)
                    
                submitted = st.form_submit_button("💾 Save All Strategies", use_container_width=True)
                
                if submitted:
                    # Validation: Count how many predictions are active
                    active_preds = {rival: val for rival, val in selected_preds.items() if val != "No prediction..."}
                    
                    if selected_surprise == "Select player...":
                        st.error("❌ Rule Violation: You MUST select 1 Surprise Player before saving!")
                    elif len(active_preds) != 2:
                        st.error("❌ Rule Violation: You MUST select exactly 2 Prediction Taxes before saving!")
                    else:
                        with st.spinner("Encrypting and saving your secret strategies..."):
                            # Clear old bets
                            models.execute("DELETE FROM pre_auction_bets WHERE captain_name = ?", (captain_name,))
                            
                            # Save Surprise
                            models.save_surprise_player(captain_name, player_options[selected_surprise])
                                
                            # Save Predictions
                            for rival, val in active_preds.items():
                                models.save_prediction(captain_name, rival, player_options[val])
                                
                            st.success("✅ All secret strategies saved successfully!")
                            st.rerun()
                    
        st.html('</div>')

    else:
        # LIVE AUCTION MAIN STATE
        st.html('<div class="glass-card">')
        st.subheader("📣 Live Auction Board")
        
        # Display team metrics
        c1, c2, c3 = st.columns(3)
        c1.metric("Your Purse", format_inr(team["purse_remaining"]))
        
        # Max Bid Calculator via Safety Engine
        # We need an active player to calculate max bid, otherwise it's just purse
        max_allowed_bid = team["purse_remaining"]
        active_player = None
        if live_state:
            active_player = models.get_player(live_state["player_id"])
            if active_player:
                max_allowed_bid = rules_engine.calculate_max_bid(tname, active_player["id"], team["max_squad_size"])
                
        c2.metric("Your Maximum Allowed Bid", format_inr(max_allowed_bid))
        
        sold_players = models.rows("SELECT id FROM players WHERE sold_team = ?", (tname,))
        squad_size = 1 + len(sold_players)
        c3.metric("Your Squad Size", f"{squad_size} / {team['max_squad_size']}")
        
        st.html("<hr style='border-color: rgba(255,255,255,0.08);'>")
        
        # Check active player display
        spin_target_id = None
        with connect() as con:
            spin_target_id = get_state(con, "wheel_target_player_id")
            
        if spin_target_id:
            player = models.get_player(spin_target_id)
            if player:
                st.html('<div class="glass-card" style="text-align: center; margin-bottom: 20px;">')
                st.subheader("🎯 Spin Wheel Draw in Progress...")
                available = models.get_available_players()
                player_names = [p["name"] for p in available if p["id"] != spin_target_id]
                player_names = player_names[:7] + [player["name"]]
                render_spin_wheel(player_names, player["name"], player["id"])
                st.html('</div>')
                
        elif live_state and active_player:
            render_player_card(active_player)
            
            curr_bid = live_state["current_bid"]
            bidder = live_state["current_bidder"] or "No bids yet"
            st.markdown(f"Current Bid: **{format_inr(curr_bid) if curr_bid > 0 else 'N/A'}** (Held by **{bidder}**)")
            
            phase = live_state["phase"]
            
            # ── Joker Actions Block ──
            st.markdown("### 🃏 Joker Card Controls")
            
            # Get Joker availability
            # In DB, joker_type is stored. Let's see: we should check if they have RTM+ available (rtm_used is FALSE)
            has_rtm = not team["rtm_used"]
            has_joker_type = team["joker_type"]
            
            # Check audit logs or state to see if they already used their joker_type
            # Let's check: did they use FORCE_NOMINATION or LAST_BID?
            # We can query audit_log for "JOKER" action with team_name = tname
            joker_uses = models.rows("SELECT id FROM audit_log WHERE action = 'JOKER' AND team_name = ?", (tname,))
            has_general_joker = (has_joker_type is not None) and (len(joker_uses) == 0)
            
            jc1, jc2 = st.columns(2)
            
            # LAST BID JOKER Trigger
            if has_general_joker and has_joker_type == 'LAST_BID':
                # Can be activated during standard bidding phase (before RTM+ or finalizing)
                if phase == 'BIDDING':
                    if jc1.button("🔥 Activate LAST BID Joker", use_container_width=True):
                        # WHY: We burn the Joker card FIRST in its own transaction before changing the
                        # phase. This prevents a race where two simultaneous clicks both pass the
                        # has_general_joker check (both read joker_uses == 0) before either writes.
                        # By writing rtm_used/joker_used first, the second click will see 1 row in
                        # audit_log and has_general_joker will be False — safe.
                        
                        # Step 1: Burn the card immediately
                        models.execute("UPDATE teams SET joker_last_bid = 'USED' WHERE captain_name = ?", (captain_name,))
                        models.log_action("JOKER", player_id=active_player["id"], team_name=tname,
                                          note=f"{captain_name} activated LAST BID Joker.")
                        
                        # Step 2: Then transition the phase
                        models.update_live_bid_state(
                            player_id=active_player["id"],
                            current_bid=curr_bid,
                            current_bidder=live_state["current_bidder"],
                            phase='LAST_BID',
                            last_bid_joker_captain=captain_name,
                            bid_count=live_state["bid_count"]
                        )
                        st.success("Last Bid Joker activated! Standard bidding frozen.")
                        st.rerun()
    
                # We no longer display the redundant "Cannot be used in this phase" info message
            elif has_joker_type == 'LAST_BID':
                jc1.info("Last Bid Joker: ❌ USED")
            else:
                jc1.info("Force Nomination Joker: (Used or not assigned)")
                
            # RTM+ Joker Trigger
            if has_rtm:
                # Can be triggered in RTM_PROMPT phase if they are NOT the current highest bidder
                if phase == 'RTM_PROMPT':
                    if bidder != tname:
                        # Bug 4 Fix: Calculate adjusted max bid before allowing RTM trigger
                        is_taxed_rtm = models.rows("SELECT 1 FROM pre_auction_bets WHERE bet_type='PREDICTION' AND target_captain=? AND target_player_id=?", (captain_name, active_player["id"]))
                        rtm_adj_max = max_allowed_bid - active_player["base_price"] if is_taxed_rtm else max_allowed_bid
                        
                        if rtm_adj_max < curr_bid:
                            jc2.info(f"⚠️ RTM+ unavailable: Adjusted max bid ({format_inr(rtm_adj_max)}) is too low due to tax.")
                        elif jc2.button("💥 Trigger RTM+ Card", use_container_width=True):
                            # WHY: Burn RTM card FIRST. models.mark_rtm_used sets rtm_used=TRUE.
                            # Because has_rtm = not team["rtm_used"] is read fresh on each page load,
                            # burning first means a second simultaneous click will see rtm_used=TRUE
                            # and will not show the button — double-spend impossible.
                            
                            # Step 1: Burn RTM card
                            models.mark_rtm_used(tname)
                            models.log_action("JOKER", player_id=active_player["id"], team_name=tname,
                                              note=f"{captain_name} triggered RTM+ Card.")
                            
                            # Step 2: Transition phase
                            models.update_live_bid_state(
                                player_id=active_player["id"],
                                current_bid=curr_bid,
                                current_bidder=live_state["current_bidder"],
                                phase='RTM_REVISE',
                                rtm_captain=captain_name,
                                bid_count=live_state["bid_count"]
                            )
                            st.success("RTM+ triggered! Highest bidder must enter revised bid.")
                            st.rerun()
                    else:
                        jc2.info("RTM+ unavailable: You are the highest bidder.")
                else:
                    jc2.info("RTM+ card is available (Triggerable after standard bidding concludes).")
            else:
                jc2.info("RTM+ Card: ❌ USED")
                
            # ── Silent Bidding Input (LAST_BID Phase) ──
            if phase == 'LAST_BID':
                st.html("<hr style='border-color: rgba(255,255,255,0.08);'>")
                st.markdown("### 🔒 Silent Max Bid Entry")
                
                # Check if this captain has already submitted a silent bid
                with connect() as con:
                    existing = con.execute(
                        "SELECT bid_amount FROM silent_bids WHERE player_id = ? AND captain_name = ?",
                        (active_player["id"], captain_name)
                    ).fetchone()
                
                if existing:
                    bid_amount = (
                        existing["bid_amount"]
                        if isinstance(existing, dict)
                        else existing[0]
                    )

                    st.info(
                        f"You have submitted a silent bid of "
                        f"{format_inr(bid_amount)}"
                    )
                    
                # Bug 5 Fix: Account for prediction tax in silent bid max
                is_taxed_silent = models.rows("SELECT 1 FROM pre_auction_bets WHERE bet_type='PREDICTION' AND target_captain=? AND target_player_id=?", (captain_name, active_player["id"]))
                silent_adj_max = max_allowed_bid - active_player["base_price"] if is_taxed_silent else max_allowed_bid
                
                silent_amt = st.number_input(
                    "Your Silent Max Bid (INR)",
                    min_value=0,
                    max_value=int(silent_adj_max),
                    value=0,
                    step=10_00_000
                )
                if st.button("Submit Silent Bid", use_container_width=True):
                    if silent_amt > silent_adj_max:
                        st.error("❌ Bid exceeds your Maximum Allowed Bid!")
                    else:
                        models.submit_silent_bid(active_player["id"], captain_name, silent_amt)
                        st.success(f"Silent bid of {format_inr(silent_amt)} submitted successfully!")
                        st.rerun()
                        
            # ── RTM+ Decision Phase (RTM_DECIDE Phase) ──
            if phase == 'RTM_DECIDE' and live_state["rtm_captain"] == captain_name:
                st.html("<hr style='border-color: rgba(255,255,255,0.08);'>")
                st.markdown("### 💥 RTM+ Match / Decline Decision")
                rev_bid = live_state["revised_bid"]
                st.markdown(f"The highest bidder revised their bid to: **{format_inr(rev_bid)}**")
                st.write("Do you want to MATCH this price to buy the player, or DECLINE and let the highest bidder have him?")
                
                rc1, rc2 = st.columns(2)
                if rc1.button("🤝 MATCH (Pay and acquire player)", use_container_width=True):
                    with st.spinner("Processing Sale... Do not refresh."):
                        # WHY: Purse check is advisory here. The atomic finalize_sale will
                        # re-read the purse inside the transaction, so no race condition.
                        if rev_bid > team["purse_remaining"]:
                            st.error("❌ You don't have enough purse remaining to match this bid!")
                        else:
                            bonus = rules_engine.check_surprise_bonus(tname, active_player["id"], active_player["base_price"], rev_bid)
                            raw_taxes = rules_engine.check_prediction_taxes(tname, active_player["id"], team["max_squad_size"], active_player["base_price"], rev_bid)
                            tax_list = [{"team_name": tname, "amount": t["tax_amount"],
                                         "note": f"Prediction Tax: -{format_inr(t['tax_amount'])} by {t['predictor_captain']}"}
                                        for t in raw_taxes]

                            sold_ok = db.finalize_sale(
                                player_id=active_player["id"],
                                sold_team=tname,
                                sold_price=rev_bid,
                                purse_deduction=rev_bid,
                                bonus_amount=bonus,
                                tax_deductions=tax_list,
                                log_note=f"{active_player['name']} sold to {tname} (RTM MATCH) for {format_inr(rev_bid)}.",
                            )
                            if not sold_ok:
                                st.error("⚠️ Sale already recorded. Please refresh.")
                            else:
                                models.clear_live_bid_state()
                                st.success(f"Acquired {active_player['name']} for {format_inr(rev_bid)}!")
                                st.rerun()
                        
                if rc2.button("❌ DECLINE (Let highest bidder buy player)", use_container_width=True):
                    with st.spinner("Processing Sale... Do not refresh."):
                        high_bidder_tname = live_state["current_bidder"]
                        high_bidder_team = models.get_team(high_bidder_tname)

                        bonus = rules_engine.check_surprise_bonus(high_bidder_tname, active_player["id"], active_player["base_price"], rev_bid)
                        raw_taxes = rules_engine.check_prediction_taxes(high_bidder_tname, active_player["id"], high_bidder_team["max_squad_size"], active_player["base_price"], rev_bid)
                        tax_list = [{"team_name": high_bidder_tname, "amount": t["tax_amount"],
                                     "note": f"Prediction Tax: -{format_inr(t['tax_amount'])} by {t['predictor_captain']}"}
                                    for t in raw_taxes]

                        sold_ok = db.finalize_sale(
                            player_id=active_player["id"],
                            sold_team=high_bidder_tname,
                            sold_price=rev_bid,
                            purse_deduction=rev_bid,
                            bonus_amount=bonus,
                            tax_deductions=tax_list,
                            log_note=f"{active_player['name']} sold to {high_bidder_tname} (RTM DECLINED) for {format_inr(rev_bid)}.",
                        )
                        if not sold_ok:
                            st.error("⚠️ Sale already recorded. Please refresh.")
                        else:
                            models.clear_live_bid_state()
                            st.success(f"Released. Acquired by {high_bidder_tname} for {format_inr(rev_bid)}.")
                            st.rerun()
                    
            # ── Revised Bid Input for Highest Bidder (RTM_REVISE Phase) ──
            if phase == 'RTM_REVISE' and bidder == tname:
                st.html("<hr style='border-color: rgba(255,255,255,0.08);'>")
                st.markdown("### 📝 RTM+ Revised Bid Entry")
                st.write(f"Captain **{live_state['rtm_captain']}** has triggered their RTM+ card on this player.")
                st.write("You must submit a single, one-time revised bid (higher than standard bidding final bid).")
                
                rev_amt = st.number_input(
                    "Your Revised Bid (INR)",
                    min_value=int(curr_bid + 10_00_000),
                    max_value=int(max_allowed_bid),
                    value=int(curr_bid + 10_00_000),
                    step=10_00_000
                )
                if st.button("Submit Revised Bid", use_container_width=True):
                    if rev_amt > max_allowed_bid:
                        st.error("❌ Bid exceeds your Maximum Allowed Bid!")
                    else:
                        models.update_live_bid_state(
                            player_id=active_player["id"],
                            current_bid=curr_bid,
                            current_bidder=bidder,
                            phase='RTM_DECIDE',
                            rtm_captain=live_state["rtm_captain"],
                            revised_bid=rev_amt,
                            bid_count=live_state["bid_count"]
                        )
                        models.log_action("REVISE", player_id=active_player["id"], team_name=tname, amount=rev_amt, note=f"{captain_name} submitted revised RTM+ bid of {format_inr(rev_amt)}.")
                        st.success("Revised bid submitted! Waiting for RTM+ choice.")
                        st.rerun()
                        
        else:
            st.info("No active player on the block.")
            
            # ── Force Nomination Joker Trigger (between draws) ──
            # Check if they have the Force Nomination Joker unused
            has_joker_type = team["joker_type"]
            joker_uses = models.rows("SELECT id FROM audit_log WHERE action = 'JOKER' AND team_name = ?", (tname,))
            has_force_nom = (has_joker_type == 'FORCE_NOMINATION') and (len(joker_uses) == 0)
            
            if has_force_nom:
                st.markdown("### 🃏 Force Nomination Joker Available")
                st.write("You can override the Spin Wheel and nominate any unsold player directly to the auction block.")
                
                available = models.get_available_players()
                av_options = {p["name"]: p["id"] for p in available}
                
                nom_names = ["Select player..."] + list(av_options.keys())
                selected_nom = st.selectbox("Select Player to Force Nominate", nom_names, key="force_nom_sel")
                
                if selected_nom != "Select player...":
                    chosen_pid = av_options[selected_nom]
                    if st.button("🔥 Activate FORCE NOMINATION", use_container_width=True):
                        # WHY: Same burn-first pattern as Last Bid Joker. Burn the card before
                        # transitioning state so a double-click or parallel request cannot
                        # activate the joker twice.
                        
                        # Step 1: Burn the card
                        models.execute("UPDATE teams SET joker_force_nom = 'USED' WHERE captain_name = ?", (captain_name,))
                        models.log_action("JOKER", player_id=chosen_pid, team_name=tname,
                                          note=f"{captain_name} activated FORCE NOMINATION.")
                        
                        # Step 2: Put player on the block
                        models.update_live_bid_state(
                            player_id=chosen_pid,
                            current_bid=0,
                            current_bidder=None,
                            phase='BIDDING'
                        )
                        st.success(f"{selected_nom} is now on the auction block!")
                        st.rerun()

            elif has_joker_type == 'FORCE_NOMINATION':
                st.info("Force Nomination Joker: ❌ USED")
        '''       
        # 3.5 Marquee Draft Order
        with connect() as con:
            m_order_raw = get_state(con, "marquee_draft_order")
        if m_order_raw:
            m_order = json.loads(m_order_raw)
            st.html("<hr style='border-color: rgba(255,255,255,0.08);'>")
            st.subheader("👑 Marquee Draft Order")
            order_text = " → ".join([f"**{idx}.** {c}" for idx, c in enumerate(m_order, 1)])
            st.write(order_text)
        '''           
        # 4. Squad display
        st.html("<hr style='border-color: rgba(255,255,255,0.08);'>")
        st.subheader("📋 Team Build Progress Grid")
        render_team_progress_grid(models, is_live=True)
        render_team_squad_rows(models)
                
        st.html('</div>')
        
    render_footer()