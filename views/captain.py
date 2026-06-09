from tenacity import before_sleep
import streamlit as st
import json
from config import format_inr, CAPTAINS
from models import is_captain_player
import models
from db import connect, closing, get_state, set_state
from ui_components import render_header, render_footer, inject_css, render_team_progress_grid, render_team_squad_rows, render_player_card, render_spin_wheel, render_sale_celebration,render_league_poster
import rules_engine

def render_captain() -> None:
    render_league_poster()
    inject_css()
    render_sale_celebration()
    
    captain_name = st.session_state.get("name")
    team = models.get_team_by_captain(captain_name)
    if not team:
        st.error(f"Error: No team mapped to captain {captain_name}.")
        st.stop()
        
    tname = team["name"]
    global_status = models.get_global_status()
    live_state = models.get_live_bid_state()
    
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
        
        # 2a. Surprise Player Selection
        st.markdown("### 🎁 Surprise Player Selection")
        st.write("Select one player secretly. If you buy him, you get a bonus of 10% of his purchase price or ₹25 Lakhs (whichever is higher).")
        
        prediction_players = models.rows("""
            SELECT id,name,seeding,base_price
            FROM players
            ORDER BY base_price DESC,name
            """
        )
               
        before = len(prediction_players)

        prediction_players = [
            p for p in prediction_players
            if not is_captain_player(p["name"])
        ]

        st.write("Before filter:", before)
        st.write("After filter:", len(prediction_players))
        
        player_options = {
            p["name"]: p["id"]
            for p in prediction_players
        }
        
        
        st.markdown("### 🎁 Surprise Player Selection")

        current_surprise_id = models.get_surprise_player(captain_name)

        surprise_names = ["Select your surprise player..."] + list(player_options.keys())

        current_surprise_name = next(
            (
                name
                for name, pid in player_options.items()
                if pid == current_surprise_id
            ),
            None
        )

        default_idx = (
            surprise_names.index(current_surprise_name)
            if current_surprise_name in surprise_names
            else 0
        )

        selected_surprise = st.selectbox(
            "Choose your Surprise Player",
            surprise_names,
            index=default_idx,
            key="surprise_player"
        )

        if st.button("💾 Save Surprise Player"):
            # Remove old surprise choice
            models.execute(
                """
                DELETE FROM pre_auction_bets
                WHERE captain_name = ?
                AND bet_type = 'SURPRISE'
                """,
                (captain_name,)
            )

            # Save new surprise choice
            if selected_surprise != "Select player...":
                models.save_surprise_player(
                    captain_name,
                    player_options[selected_surprise]
                )
                st.success("Surprise Player saved.")
                st.rerun()

        your_marquee = models.one(
            "SELECT * FROM players WHERE is_marquee=TRUE AND marquee_nominator = ? LIMIT 1",
            (captain_name,),
        )
        if your_marquee:
            st.markdown("### Your Marquee Player")
            render_player_card(your_marquee)
                
        st.html("<hr style='border-color: rgba(255,255,255,0.08);'>")
        
        # 2b. Prediction Tax Entries
        st.markdown("### 🔮 Prediction Tax Entries")
        st.write("Predict which rival captain will buy which player. (Submit up to 2 secret predictions).")
        st.caption("If they buy that player, they will be penalized 10% of the purchase price or ₹25 Lakhs.")
        
        rivals = [c for c in CAPTAINS.keys() if c != captain_name]
        
        # Fetch current predictions
        preds = models.get_predictions(captain_name)
        pred_map = {p["target_captain"]: p["target_player_id"] for p in preds}
        num_preds = len(pred_map)
        
        for idx, rival in enumerate(rivals, 1):
            cur_pred_id = pred_map.get(rival)
            cur_pred_name = next((name for name, pid in player_options.items() if pid == cur_pred_id), None)
            
            pred_names = ["No prediction..."] + list(player_options.keys())
            default_pred_idx = pred_names.index(cur_pred_name) if cur_pred_name in pred_names else 0
            
            is_disabled = (num_preds >= 2 and not cur_pred_id)
            
            selected_pred = st.selectbox(
                f"Prediction {idx}: Rival '{rival}' will buy:",
                pred_names,
                index=default_pred_idx,
                key=f"pred_{rival}",
                disabled=is_disabled
            )
            
            if st.button(
                f"Save Prediction for {rival}",
                key=f"save_pred_{rival}"
            ):
                if selected_pred == "No prediction...":
                    models.execute(
                        """
                        DELETE FROM pre_auction_bets
                        WHERE captain_name = ?
                        AND bet_type = 'PREDICTION'
                        AND target_captain = ?
                        """,
                        (captain_name, rival)
                    )

                    st.success(f"Prediction cleared for {rival}")
                    st.rerun()

                else:
                    pred_pid = player_options[selected_pred]

                    models.save_prediction(
                        captain_name,
                        rival,
                        pred_pid
                    )

                    st.success(
                        f"Prediction saved: {rival} → {selected_pred}"
                    )
                    st.rerun()
                
        if num_preds >= 2:
            st.warning("You have reached the maximum of 2 prediction taxes. Other options are disabled.")
                
        st.html("<hr style='border-color: rgba(255,255,255,0.08);'>")
        
        # 2c. Marquee Nomination Turn-Based Flow
        st.markdown("### 👑 Marquee Player Selection")
        
        with connect() as con:
            order_json = get_state(con, "marquee_draft_order")
            turn_idx_str = get_state(con, "marquee_draft_turn_index", "0")
            completed = get_state(con, "marquee_draft_completed", "FALSE")
            
        if not order_json:
            st.info("Waiting for the Admin to randomize and release the Marquee Draft Order...")
        elif completed == 'TRUE':
            # Display all selections
            marquees = models.get_marquee_players()
            st.success("🎉 Marquee Player Draft Complete!")
            st.write("**Designated Marquee Players (Base Price ₹4.5 Crore):**")
            for m in marquees:
                st.markdown(f"• **{m['name']}** (Selected by {m['marquee_nominator']})")
        else:
            order = json.loads(order_json)
            turn_idx = int(turn_idx_str)
            current_drafter = order[turn_idx]
            
            # Show the drafting order
            st.write(f"Draft Order: {' → '.join(order)}")
            
            if current_drafter == captain_name:
                st.markdown(f"#### 🟢 **It is your turn to select!**")
                st.warning("IMPORTANT: You are committing to buy your selected player for **₹4.5 Crore** at the start of the auction.")
                
                # Filter players: only AVAILABLE, and NOT already marquee
                available_for_marquee = models.rows("SELECT id, name, seeding FROM players WHERE status='AVAILABLE' AND is_marquee=FALSE ORDER BY name")
                already_nominated_ids = {m["id"] for m in models.get_marquee_players()}
                available_for_marquee = [p for p in available_for_marquee if p["id"] not in already_nominated_ids and not is_captain_player(p["name"])]
                am_options = {f"{p['name']} ({p['seeding']})": p["id"] for p in available_for_marquee}
                st.write("Raw player count:",len(models.rows("SELECT id FROM players")))

                st.write("Available count:",
                        len(models.rows("""
                            SELECT id
                            FROM players
                            WHERE status='AVAILABLE'
                        """)))

                st.write("Marquee candidates:",len(available_for_marquee))

                draft_names = ["Select a player to nominate..."] + list(am_options.keys())
                selected_draft = st.selectbox("Choose Marquee Player", draft_names, key="marquee_draft_sel")
                
                if selected_draft != "Select a player to nominate...":
                    chosen_pid = am_options[selected_draft]
                    if st.button("Confirm Selection", use_container_width=True):
                        # Nominate
                        models.nominate_marquee(chosen_pid, captain_name)
                        
                        # Advance turn index
                        new_idx = turn_idx + 1
                        with connect() as con:
                            set_state(con, "marquee_draft_turn_index", str(new_idx))
                            if new_idx >= len(order):
                                set_state(con, "marquee_draft_completed", "TRUE")
                            con.commit()
                            
                        # Log action
                        models.log_action("MARQUEE_NOMINATE", player_id=chosen_pid, team_name=tname, note=f"{captain_name} nominated {selected_draft.split(' (')[0]} as marquee.")
                        st.success(f"Successfully drafted {selected_draft}!")
                        st.rerun()
            else:
                st.info(f"⏳ Waiting for **{current_drafter}** to nominate their marquee player...")
                
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
                        # Freeze standard bidding, open silent bidding
                        models.update_live_bid_state(
                            player_id=active_player["id"],
                            current_bid=curr_bid,
                            current_bidder=live_state["current_bidder"],
                            phase='LAST_BID',
                            last_bid_joker_captain=captain_name,
                            bid_count=live_state["bid_count"]
                        )
                        models.execute("UPDATE teams SET joker_last_bid = 'USED' WHERE captain_name = ?", (captain_name,))
                        models.log_action("JOKER", player_id=active_player["id"], team_name=tname, note=f"{captain_name} activated LAST BID Joker.")
                        st.success("Last Bid Joker activated! Standard bidding frozen.")
                        st.rerun()
                        # 🟢 ADD THIS LINE TO BURN THE CARD IMMEDIATELY:
    
    
                else:
                    jc1.info("Last Bid Joker is available but cannot be used in this phase.")
            elif has_joker_type == 'LAST_BID':
                jc1.info("Last Bid Joker: ❌ USED")
            else:
                jc1.info("Force Nomination Joker: (Used or not assigned)")
                
            # RTM+ Joker Trigger
            if has_rtm:
                # Can be triggered in RTM_PROMPT phase if they are NOT the current highest bidder
                if phase == 'RTM_PROMPT':
                    if bidder != tname:
                        if jc2.button("💥 Trigger RTM+ Card", use_container_width=True):
                            models.update_live_bid_state(
                                player_id=active_player["id"],
                                current_bid=curr_bid,
                                current_bidder=live_state["current_bidder"],
                                phase='RTM_REVISE',
                                rtm_captain=captain_name,
                                bid_count=live_state["bid_count"]
                            )
                            # Mark team's RTM+ as used
                            models.mark_rtm_used(tname)
                            models.log_action("JOKER", player_id=active_player["id"], team_name=tname, note=f"{captain_name} triggered RTM+ Card.")
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
                    
                silent_amt = st.number_input(
                    "Your Silent Max Bid (INR)",
                    min_value=int(active_player["base_price"]),
                    max_value=int(max_allowed_bid),
                    value=int(max(active_player["base_price"], curr_bid)),
                    step=10_00_000
                )
                if st.button("Submit Silent Bid", use_container_width=True):
                    if silent_amt > max_allowed_bid:
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
                    if rev_bid > team["purse_remaining"]:
                        st.error("❌ You don't have enough purse remaining to match this bid!")
                    else:
                        # Process Match: B gets the player at rev_bid
                        models.update_player_status(active_player["id"], 'SOLD', sold_team=tname, sold_price=rev_bid)
                        models.update_team_purse(tname, team["purse_remaining"] - rev_bid)
                        
                        # Apply Surprise player check
                        bonus = rules_engine.check_surprise_bonus(tname, active_player["id"], rev_bid)
                        if bonus > 0:
                            models.update_team_purse(tname, models.get_team(tname)["purse_remaining"] + bonus)
                            models.log_action("BONUS", player_id=active_player["id"], team_name=tname, amount=bonus, note=f"Surprise Player Bonus activated: +{format_inr(bonus)}")
                            
                        # Apply Prediction Tax check (Buying captain penalized)
                        current_teams = models.get_all_teams()
                        curr_limit = current_teams[0]["max_squad_size"] if current_teams else 10
                        taxes = rules_engine.check_prediction_taxes(tname, active_player["id"],curr_limit,active_player["base_price"], rev_bid)
                        for tax in taxes:
                            buyer_t = models.get_team(tname)
                            models.update_team_purse(tname, buyer_t["purse_remaining"] - tax["tax_amount"])
                            models.log_action("TAX", player_id=active_player["id"], team_name=tname, amount=tax["tax_amount"], note=f"Prediction Tax penalty: -{format_inr(tax['tax_amount'])} triggered by predictor {tax['predictor_captain']}.")
                            
                        models.log_action("SOLD", player_id=active_player["id"], team_name=tname, amount=rev_bid, note=f"{active_player['name']} sold to {tname} (RTM MATCH) for {format_inr(rev_bid)}.")
                        models.clear_live_bid_state()
                        st.success(f"Acquired {active_player['name']} for {format_inr(rev_bid)}!")
                        st.rerun()
                        
                if rc2.button("❌ DECLINE (Let highest bidder buy player)", use_container_width=True):
                    # Process Decline: A gets the player at rev_bid
                    high_bidder_tname = live_state["current_bidder"]
                    high_bidder_team = models.get_team(high_bidder_tname)
                    
                    models.update_player_status(active_player["id"], 'SOLD', sold_team=high_bidder_tname, sold_price=rev_bid)
                    models.update_team_purse(high_bidder_tname, high_bidder_team["purse_remaining"] - rev_bid)
                    
                    # Apply Surprise player check
                    bonus = rules_engine.check_surprise_bonus(high_bidder_tname, active_player["id"], rev_bid)
                    if bonus > 0:
                        models.update_team_purse(high_bidder_tname, models.get_team(high_bidder_tname)["purse_remaining"] + bonus)
                        models.log_action("BONUS", player_id=active_player["id"], team_name=high_bidder_tname, amount=bonus, note=f"Surprise Player Bonus activated: +{format_inr(bonus)}")
                        
                    # Apply Prediction Tax check (Buying captain penalized)
                    taxes = rules_engine.check_prediction_taxes(high_bidder_tname, active_player["id"],curr_limit,active_player["base_price"], rev_bid)
                    for tax in taxes:
                        buyer_t = models.get_team(high_bidder_tname)
                        models.update_team_purse(high_bidder_tname, buyer_t["purse_remaining"] - tax["tax_amount"])
                        models.log_action("TAX", player_id=active_player["id"], team_name=high_bidder_tname, amount=tax["tax_amount"], note=f"Prediction Tax penalty: -{format_inr(tax['tax_amount'])} triggered by predictor {tax['predictor_captain']}.")
                        
                    models.log_action("SOLD", player_id=active_player["id"], team_name=high_bidder_tname, amount=rev_bid, note=f"{active_player['name']} sold to {high_bidder_tname} (RTM DECLINED) for {format_inr(rev_bid)}.")
                    models.clear_live_bid_state()
                    st.success(f"Released player. Acquired by {high_bidder_tname} for {format_inr(rev_bid)}.")
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
                        # Put on the block
                        models.update_live_bid_state(
                            player_id=chosen_pid,
                            current_bid=0,
                            current_bidder=None,
                            phase='BIDDING'
                        )
                        # 🟢 ADD THIS LINE TO BURN THE CARD IMMEDIATELY:
                        models.execute("UPDATE teams SET joker_force_nom = 'USED' WHERE captain_name = ?", (captain_name,))
                        
                        models.log_action("JOKER", player_id=chosen_pid, team_name=tname, note=f"{captain_name} activated FORCE NOMINATION.")
                        st.success(f"{selected_nom} is now on the auction block!")
                        st.rerun()

            elif has_joker_type == 'FORCE_NOMINATION':
                st.info("Force Nomination Joker: ❌ USED")
                
        # 4. Squad display
        st.html("<hr style='border-color: rgba(255,255,255,0.08);'>")
        st.subheader("📋 Team Build Progress Grid")
        render_team_progress_grid(models, is_live=True)
        render_team_squad_rows(models)
                
        st.html('</div>')
        
    render_footer()
