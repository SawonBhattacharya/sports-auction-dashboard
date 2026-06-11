from numpy import empty
import streamlit as st
import json
import random
import re
from html import escape
from pathlib import Path
from config import format_inr, CAPTAINS, MARQUEE_BASE_PRICE
import models
from models import is_captain_player
import rules_engine
from db import connect, closing, get_state, set_state, init_db
import ui_components


@st.fragment(run_every="2s")
def admin_smart_watcher():
    live_state = models.get_live_bid_state()
    bets_count = len(models.rows("SELECT id FROM pre_auction_bets"))
    silent_bids_count = len(models.rows("SELECT player_id, captain_name FROM silent_bids"))
    
    current_hash = hash(str(live_state) + str(bets_count) + str(silent_bids_count))
    if st.session_state.get("admin_hash") != current_hash:
        if "admin_hash" in st.session_state:
            st.session_state["admin_hash"] = current_hash
            st.rerun()
        st.session_state["admin_hash"] = current_hash

def render_admin() -> None:
    admin_smart_watcher()
    # Initialize DB tables on first access
    init_db()
    ui_components.inject_css()
    
    st.html(
        """
        <style>
        .admin-section {
            background: rgba(31, 41, 55, 0.4);
            border: 1px solid rgba(255, 255, 255, 0.05);
            border-radius: 10px;
            padding: 15px;
            margin-bottom: 20px;
        }
        </style>
        """
    )
    
    global_status = models.get_global_status()
    
    # Render Admin Page Header
    st.html(
        f"""
        <div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid rgba(255,255,255,0.08); padding-bottom: 10px; margin-bottom: 20px;">
            <div style="font-size: 1.6rem; font-weight: 700; color: #ffffff; letter-spacing: 0.5px;">⚙️ ADMIN PANEL</div>
            <div style="font-size: 1rem; color: #9ca3af; font-weight: 500;">Status: {global_status.replace('_', ' ')}</div>
        </div>
        """
    )
    
    ui_components.render_sale_celebration()

    if st.button("Refresh Data", use_container_width=True):
        st.rerun()

    if global_status == 'PRE_AUCTION':
        tab_names = ["Manage Teams", "Live Auction Control", "Surprise Player", "Predict Audit Ledger", "Main Wheel Draw", "Settings & Reset"]
        tab_manage, tab_live, tab_surprise, tab_audit, tab_wheel, tab_settings = st.tabs(tab_names)
    else:
        tab_names = ["Live Auction Control", "Main Wheel Draw", "Manage Teams", "Surprise Player", "Predict Audit Ledger", "Settings & Reset"]
        tab_live, tab_wheel, tab_manage, tab_surprise, tab_audit, tab_settings = st.tabs(tab_names)

    with tab_manage:
        render_manage_teams_section()

    if global_status == 'PRE_AUCTION':
        with tab_live:
            render_pre_auction_wizard()
        with tab_surprise:
            render_surprise_player_section()
        with tab_audit:
            render_prediction_audit_ledger()
        with tab_wheel:
            st.info("Main wheel draw unlocks after pre-auction setup is launched.")
        with tab_settings:
            render_admin_reset_panel()
    else:
        with tab_live:
            render_live_auction_console(show_surprise=False, show_draw=False, show_reset=False, show_prediction_audit=False)
        with tab_surprise:
            render_surprise_player_section()
        with tab_audit:
            render_prediction_audit_ledger()            
        with tab_wheel:
            render_live_auction_console(show_rosters=False, show_surprise=False, show_bidding=False, show_reset=False, show_prediction_audit=False)
        with tab_settings:
            render_admin_reset_panel()
        
    # Render Footer
    st.html(
        """
        <div style="margin-top: 50px; text-align: center; font-size: 0.8rem; color: #6b7280; padding-bottom: 20px;">
            © 2026 Sawon & Ujjawal · Admin View Authorized
        </div>
        """
    )

def _safe_logo_filename(team_name: str, original_name: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9_-]+", "_", team_name.strip()).strip("_").lower() or "team_logo"
    suffix = Path(original_name).suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
        suffix = ".png"
    return f"{stem}{suffix}"

def render_manage_teams_section() -> None:
    st.html('<div class="admin-section">')
    st.markdown("### Manage Teams")
    st.caption("Edit team names, logo references, purse values, squad size, RTM+ state, and Joker card.")

    teams = models.get_all_teams()
    if not teams:
        st.info("No teams found. Initialize the database first.")
        st.html('</div>')
        return

    selected_name = st.selectbox("Select Team to Edit", [t["name"] for t in teams], key="manage_team_select")
    team = next(t for t in teams if t["name"] == selected_name)

    preview_col, form_col = st.columns([1, 2])
    with preview_col:
        logo_src = ui_components.find_team_logo(team)
        st.html(
            f"""
            <div class="glass-card" style="text-align:center;">
                <img src="{escape(logo_src or '', quote=True)}" style="width:96px;height:96px;object-fit:cover;border-radius:8px;border:1px solid rgba(255,255,255,0.12);">
                <h3 style="margin:10px 0 2px;color:#f3f4f6;">{escape(team['name'])}</h3>
                <div style="color:#9ca3af;">{escape(team['captain_name'])}</div>
            </div>
            """
        )

    with form_col:
        new_name = st.text_input("Team Name", value=team["name"], key=f"team_name_{team['name']}")
        st.text_input("Captain Login Name", value=team["captain_name"], disabled=True, key=f"team_cap_{team['name']}")
        logo_url = st.text_input(
            "Logo path or URL",
            value=team["logo_url"] or "",
            placeholder="images/team_logo/team_alpha.png or https://...",
            key=f"team_logo_{team['name']}",
        )
        uploaded_logo = st.file_uploader(
            "Upload Team Logo",
            type=["png", "jpg", "jpeg", "webp"],
            key=f"team_logo_upload_{team['name']}",
        )

        f1, f2 = st.columns(2)
        starting_purse = f1.number_input(
            "Starting Purse (INR)",
            min_value=0,
            value=int(team["starting_purse"]),
            step=10_00_000,
            key=f"team_start_{team['name']}",
        )
        purse_remaining = f2.number_input(
            "Current Purse (INR)",
            min_value=0,
            value=int(team["purse_remaining"]),
            step=10_00_000,
            key=f"team_purse_{team['name']}",
        )

        f3, f4, f5 = st.columns(3)
        squad_size = f3.number_input(
            "Squad Size Limit",
            min_value=1,
            max_value=25,
            value=int(team["max_squad_size"]),
            step=1,
            key=f"team_size_{team['name']}",
        )
        rtm_used = f4.checkbox("RTM+ Used", value=bool(team["rtm_used"]), key=f"team_rtm_{team['name']}")
        joker_options = ["", "FORCE_NOMINATION", "LAST_BID"]
        joker_value = team["joker_type"] or ""
        joker_type = f5.selectbox(
            "Joker",
            joker_options,
            index=joker_options.index(joker_value) if joker_value in joker_options else 0,
            key=f"team_joker_{team['name']}",
        )

        if st.button("Save Team Details", use_container_width=True, key=f"save_team_{team['name']}"):
            if not new_name.strip():
                st.error("Team name cannot be empty.")
            elif new_name.strip() != team["name"] and models.get_team(new_name.strip()):
                st.error("Another team already uses that name.")
            else:
                final_logo_url = logo_url.strip()
                if uploaded_logo:
                    logo_dir = Path("images/team_logo")
                    logo_dir.mkdir(parents=True, exist_ok=True)
                    logo_path = logo_dir / _safe_logo_filename(new_name, uploaded_logo.name)
                    logo_path.write_bytes(uploaded_logo.getbuffer())
                    final_logo_url = str(logo_path).replace("\\", "/")

                models.update_team_details(
                    original_name=team["name"],
                    name=new_name.strip(),
                    logo_url=final_logo_url,
                    starting_purse=int(starting_purse),
                    purse_remaining=int(purse_remaining),
                    max_squad_size=int(squad_size),
                    rtm_used=rtm_used,
                    joker_type=joker_type or None,
                )
                models.log_action("TEAM_UPDATE", team_name=new_name.strip(), note=f"Admin updated team details for {new_name.strip()}.")
                st.success("Team details saved.")
                st.rerun()

    st.html('</div>')

def render_surprise_assignments_table() -> None:
    assignments = models.rows(
        """
        SELECT b.captain_name, b.target_player_id, b.created_at,
               p.name AS player_name, p.seeding, p.base_price
        FROM pre_auction_bets b
        LEFT JOIN players p ON p.id = b.target_player_id
        WHERE b.bet_type = 'SURPRISE'
        ORDER BY b.captain_name
        """
    )

    by_captain = {
        row["captain_name"]: row
        for row in assignments
    }

    table_rows = []

    for team in models.get_all_teams():

        captain_name = team["captain_name"]

        row = by_captain.get(captain_name)

        table_rows.append(
            {
                "Captain": captain_name,
                "Team": team["name"],
                "Surprise Player": row["player_name"] if row and row["player_name"] else "Not assigned",
                "Seed": row["seeding"] if row and row["seeding"] else "-",
                "Base Price": format_inr(row["base_price"]) if row and row["base_price"] is not None else "-",
                "Assigned At": row["created_at"] if row and row["created_at"] else "-",
            }
        )

    st.dataframe(
        table_rows,
        hide_index=True,
        use_container_width=True
    )

def render_prediction_taxes_table() -> None:
    # 1. Fetch ALL predictions from the table
    assignments = models.rows(
        """
        SELECT b.captain_name, b.target_captain, b.target_player_id, b.created_at,
               p.name AS player_name, p.seeding, p.base_price
        FROM pre_auction_bets b
        LEFT JOIN players p ON p.id = b.target_player_id
        WHERE b.bet_type = 'PREDICTION'
        ORDER BY b.captain_name, b.created_at ASC
        """
    )

    if not assignments:
        st.info("No secret team prediction entries have been logged in the ledger yet.")
        return

    # 2. Map captain_name to team_name to prevent repeated DB hits inside our loop
    all_teams = models.get_all_teams()
    captain_to_team = {t["captain_name"]: t["name"] for t in all_teams}

    table_rows = []

    # 3. Iterate over the database assignments list directly so NO records are dropped
    for idx, row in enumerate(assignments, start=1):
        captain_name = row["captain_name"]
        team_name = captain_to_team.get(captain_name, "Unknown Team")
        
        table_rows.append(
            {
                "Sl No": idx,
                "Predicting Captain": captain_name,
                "Predicting Team": team_name,
                "Target Captain": row["target_captain"] if row["target_captain"] else "-",
                "Predicted Player": row["player_name"] if row["player_name"] else "Not assigned",
                "Tier/Seed": row["seeding"] if row["seeding"] else "-",
                "Base Price": format_inr(row["base_price"]) if row["base_price"] is not None else "-",
                "Timestamp": row["created_at"][:19].replace("T", " ") if row["created_at"] else "-",
            }
        )

    # 4. Render the fully preserved table array safely
    st.dataframe(
        table_rows,
        hide_index=True,
        use_container_width=True
    )
    st.caption(f"📊 Audit trail verified: Total of {len(table_rows)} predictive items currently registered.")


def render_pre_auction_wizard() -> None:
    st.subheader("🏁 Pre-Auction Setup Wizard")
    
    # ── STEP 1: Excel Data Ingestion ──
    st.html('<div class="admin-section">')
    st.markdown("### 📥 Step 1: Ingest Player Database")
    
    default_excel = Path("Auction Tracker v3 latest.xlsx")
    st.write(f"Default Excel Path: `{default_excel.absolute()}`")
    
    # File Uploader
    st.caption("Imports players from the `Clean_Player_DB` sheet in the uploaded workbook.")
    uploaded_file = st.file_uploader("Upload Auction Tracker Excel File", type=["xlsx"])
    
    if st.button("Import / Sync Player Data", use_container_width=True):
        try:
            target_path = Path("Auction Tracker v3 latest.xlsx")
            if uploaded_file:
                # Save uploaded file
                target_path.write_bytes(uploaded_file.getbuffer())
                
            count = models.import_players_from_excel(target_path, replace_existing=True)
            st.success(f"Successfully imported {count} players into the database!")
        except Exception as e:
            st.error(f"Failed to load excel data: {e}")
            
    # Show active player count
    total_players = len(models.get_all_players())
    st.info(f"Current players in database: **{total_players}**")
    st.html('</div>')

    # ── STEP 2: Squad Size Configuration ──
    st.html('<div class="admin-section">')
    st.markdown("### 📏 Step 2: Squad Size Limits")
    st.caption("Decide the tournament squad size per team. All teams are seeded with captains.")
    
    current_teams = models.get_all_teams()
    curr_limit = current_teams[0]["max_squad_size"] if current_teams else 10
    
    limit_options = [10, 11]
    selected_limit = st.selectbox("Squad Size Limit (Captain + Buys)", limit_options, index=limit_options.index(curr_limit))
    
    if st.button("Apply Squad Size Limit", use_container_width=True):
        models.update_squad_size_limit(selected_limit)
        st.success(f"Roster limits updated to {selected_limit} players (including Captain) per team.")
    st.html('</div>')
    
    # ── STEP 3: Marquee Selection Order ──
    st.html('<div class="admin-section">')
    st.markdown("### 👑 Step 3: Marquee Draft Order")
    
    with connect() as con:
        order_json = get_state(con, "marquee_draft_order")
        completed = get_state(con, "marquee_draft_completed", "FALSE")
        
    if order_json:
        order = json.loads(order_json)
        st.write(f"Current Marquee Draft Order: **{' → '.join(order)}**")
        st.write(f"Draft Completed: **{completed}**")
    else:
        st.info("No Marquee Draft Order decided yet.")
        
    if st.button("Randomize & Set Marquee Draft Order", use_container_width=True):
        caps = [t["captain_name"] for t in models.get_all_teams()]

        random.shuffle(caps)
        with connect() as con:
            set_state(con, "marquee_draft_order", json.dumps(caps))
            set_state(con, "marquee_draft_turn_index", "0")
            set_state(con, "marquee_draft_completed", "FALSE")
            con.commit()
        st.success(f"Randomized Draft Order: {' → '.join(caps)}")
        st.rerun()
        
    st.html('</div>')
    
    # ── STEP 4: Joker Card Lottery ──
    st.html('<div class="admin-section">')
    st.markdown("### 🃏 Step 4: Joker Lottery Allocation")
    st.caption("Distributes exactly 2 Force Nomination and 2 Last Bid Jokers randomly among the 4 captains.")
    
    jokers_assigned = True
    for t in current_teams:
        if not t["joker_type"]:
            jokers_assigned = False
            
    if jokers_assigned:
        st.success("Jokers allocated to captains:")
        for t in current_teams:
            st.write(f"• **{t['captain_name']}** ({t['name']}): `{t['joker_type']}`")
    else:
        st.warning("Jokers not allocated yet.")
        
    if st.button("Distribute Jokers", use_container_width=True):
        pool = ["FORCE_NOMINATION", "FORCE_NOMINATION", "LAST_BID", "LAST_BID"]
        random.shuffle(pool)
        
        with connect() as con:
            teams = models.get_all_teams()

            for idx, team in enumerate(teams):
                cname = team["captain_name"]
                jt = pool[idx]
                con.execute("UPDATE teams SET joker_type = ? WHERE captain_name = ?", (jt, cname))
            con.commit()
            
        models.log_action("JOKER_LOTTERY", note="Jokers randomly distributed (2 Force Nomination, 2 Last Bid).")
        st.success("Jokers successfully distributed!")
        st.rerun()
        
    st.html('</div>')
    
    
    
    # ── STEP 5: Verification Checklist & Launch ──
    st.html('<div class="admin-section">')
    st.markdown("### 🛡️ Step 5: Verification & Launch")
    
    # Gather counts
    pred_count = len(models.get_all_predictions())
    surprise_count = len(models.get_all_surprise_players())
    marquees = models.get_marquee_players()
    marquee_count = len(marquees)
    
    st.write(f"• Players in DB: **{total_players}**")
    st.write(f"• Jokers Assigned: **{'YES' if jokers_assigned else 'NO'}**")
    st.write(f"• Marquee Players Drafted: **{marquee_count} / 4**")
    st.write(f"• Surprise Selections Submitted: **{surprise_count} / 4**")
    st.write(f"• Prediction Tax Submissions: **{pred_count} / 8** (Max)")
    
    is_ready = (
        total_players > 0
        and jokers_assigned
        and completed == 'TRUE'
        and surprise_count == len(models.get_all_teams())
        and pred_count == 8
    )

    
    if not is_ready:
        st.warning("All setups must be completed before starting the auction.")
        
    if st.button("🚀 Lock Pre-Auction & Launch Main Event", disabled=not is_ready, use_container_width=True):
        # Update status
        models.set_global_status("LIVE_AUCTION")
        # Clear live state
        models.clear_live_bid_state()
        # Reset team purses to starting purses (25cr)
        models.reset_teams()
        # Mark all players available (clear old sales history from testing)
        models.execute("UPDATE players SET status = 'AVAILABLE', sold_team = NULL, sold_price = NULL, sold_at = NULL")
        models.log_action("LAUNCH", note="LCL Auction 2026 launched! Status set to LIVE_AUCTION.")
        st.success("Main Event Launched!")
        st.rerun()
        
    st.html('</div>')

def live_auction_grid_fragment():
    ui_components.render_team_progress_grid(models, is_live=True)
    ui_components.render_team_squad_rows(models)

def render_surprise_player_section() -> None:
    st.html('<div class="admin-section">')
    st.markdown("### Surprise Player Assignments")
    render_surprise_assignments_table()
    st.html('</div>')

def render_prediction_audit_ledger() -> None:
    st.html('<div class="admin-section">')
    st.markdown("### Prediction Audit Ledger")
    render_prediction_taxes_table()
    st.html('</div>')

def render_live_auction_console(
    show_rosters: bool = True,
    show_surprise: bool = True,
    show_draw: bool = True,
    show_bidding: bool = True,
    show_reset: bool = True,
    show_prediction_audit: bool = True,
) -> None:
    if show_bidding:
        st.subheader("Live Auction Controls")
    elif show_draw:
        st.subheader("Main Wheel Draw")
    
    if show_rosters:
        live_auction_grid_fragment()

    if show_surprise:
        render_surprise_player_section()
    
    if show_prediction_audit:
        render_prediction_audit_ledger()
    
    live_state = models.get_live_bid_state()
    
    # ── PHASE 1: Marquee Auction Phase ──
    # Check if there are marquee players who are AVAILABLE
    available_marquees = models.rows("SELECT id, name, marquee_nominator FROM players WHERE is_marquee=TRUE AND status='AVAILABLE' ORDER BY name")
    
    if show_draw and available_marquees:
        st.html('<div class="admin-section">')
        st.markdown("### 👑 Phase: Marquee Auction")
        st.info("The marquee round is active first. Nominating captains are committed to purchase their marquee for ₹4.5 Crore unless someone bids higher.")
        
        # Admin selects marquee player to put on block
        m_opts = {f"{m['name']} (Nominated by {m['marquee_nominator']})": m for m in available_marquees}
        selected_m = st.selectbox("Select Marquee Player to Auction", list(m_opts.keys()))
        
        if st.button("Put Marquee Player on Block", use_container_width=True):
            m_player = m_opts[selected_m]
            nom_captain = m_player["marquee_nominator"]
            nom_team = models.get_team_by_captain(nom_captain)
            
            # Put player on block with opening bid of 4.5cr by nominating team
            models.update_live_bid_state(
                player_id=m_player["id"],
                current_bid=MARQUEE_BASE_PRICE,
                current_bidder=nom_team["name"],
                phase='BIDDING',
                bid_count=1
            )
            models.log_action("NOMINATE", player_id=m_player["id"], team_name=nom_team["name"], amount=MARQUEE_BASE_PRICE, note=f"Marquee {m_player['name']} on block. Committed opening bid of {format_inr(MARQUEE_BASE_PRICE)} by {nom_captain}.")
            st.success(f"{m_player['name']} is now active!")
            st.rerun()
        st.html('</div>')
        
    elif show_draw:
        # ── PHASE 2: Main Spin-Wheel Auction Phase ──
        st.html('<div class="admin-section">')
        st.markdown("### 🎯 Phase: Main Spin-Wheel Draw")
        
        # Get count of available non-marquee players
        available_normal = models.rows("SELECT id, name FROM players WHERE status='AVAILABLE' AND is_marquee=FALSE ORDER BY name")
        st.write(f"Available players remaining: **{len(available_normal)}**")
        
        with connect() as con:
            spin_target = get_state(con, "wheel_target_player_id")
            
        if spin_target:
            target_p = models.get_player(spin_target)
            
            # Fetch all available player names to populate the wheel segments
            available = models.get_available_players()
            from models import is_captain_player
            player_names = [p["name"] for p in available if p["id"] != spin_target and not p.get("is_marquee") and not is_captain_player(p["name"])]
            player_names = player_names[:7] + [target_p["name"]]
            
            st.html('<div class="glass-card" style="text-align: center; margin-bottom: 20px;">')
            ui_components.render_spin_wheel(player_names, target_p["name"], target_p["id"])
            st.html('</div>')
            
            st.warning(f"Spin Wheel drawn: **{target_p['name']}**")
            
            sc1, sc2 = st.columns(2)
            if sc1.button("🔥 Put Drawn Player on Auction Block", use_container_width=True):
                models.update_live_bid_state(
                    player_id=target_p["id"],
                    current_bid=0,
                    current_bidder=None,
                    phase='BIDDING'
                )
                with connect() as con:
                    set_state(con, "wheel_target_player_id", None)
                    con.commit()
                models.log_action("DRAW", player_id=target_p["id"], note=f"{target_p['name']} put on the auction block.")
                st.success(f"Placed {target_p['name']} on the block.")
                st.rerun()
                
            if sc2.button("❌ Cancel / Redraw", use_container_width=True):
                with connect() as con:
                    set_state(con, "wheel_target_player_id", None)
                    con.commit()
                st.info("Draw cancelled.")
                st.rerun()
        else:
            if available_normal:
                if st.button("🎡 Trigger Spin Wheel Random Draw", use_container_width=True):
                    # Randomly pick
                    drawn = random.choice(available_normal)
                    with connect() as con:
                        set_state(con, "wheel_target_player_id", drawn["id"])
                        con.commit()
                    st.success(f"Draw triggered! Cosmic wheel landing on {drawn['name']}.")
                    st.rerun()
            else:
                st.info("All players have been auctioned! The auction is complete.")
                if st.button("🏁 Mark Tournament Auction as COMPLETED", use_container_width=True):
                    models.set_global_status("COMPLETED")
                    st.success("Auction marked as Completed!")
                    st.rerun()
                    
        st.html('</div>')
        
    # ── LIVE BIDDING CONTROLS ──
    if show_bidding and live_state:
        st.html('<div class="admin-section">')
        active_p = models.get_player(live_state["player_id"])
        
        st.markdown(f"### Active Player: **{active_p['name']}**")
        ui_components.render_player_card(active_p)
        st.write(f"Base Price: {format_inr(active_p['base_price'])} | Seeding: {active_p['seeding']}")
        
        curr_bid = live_state["current_bid"]
        bidder = live_state["current_bidder"] or "No bids placed yet"
        st.markdown(f"**Current Bid: {format_inr(curr_bid)}** ({bidder})")
        
        phase = live_state["phase"]
        
        # ── 1. Standard Bidding Phase ──
        if phase == 'BIDDING':
            st.markdown("#### Record Bid Entry")
            
            b_cols = st.columns(4)
            teams = models.get_all_teams()
            
            # Cache all prediction taxes for the active player to avoid N+1 queries
            taxes = models.rows("SELECT target_captain FROM pre_auction_bets WHERE bet_type = 'PREDICTION' AND target_player_id = ?", (active_p["id"],))
            taxed_captains = {t["target_captain"] for t in taxes}
            
            for idx, t in enumerate(teams):
                tname = t["name"]
                tcap = t["captain_name"]
                
                # Calculate increment
                inc = rules_engine.get_min_increment(curr_bid)
                next_bid = curr_bid + inc if curr_bid > 0 else active_p["base_price"]
                
                # Check purse safety max bid
                max_bid = rules_engine.calculate_max_bid(tname, active_p["id"], t["max_squad_size"])
                
                # Hidden Penalty Logic (cached)
                is_taxed = tcap in taxed_captains
                adjusted_max_bid = max_bid - active_p["base_price"] if is_taxed else max_bid
                
                is_disabled = next_bid > adjusted_max_bid
                
                if is_disabled and is_taxed and next_bid <= max_bid:
                    # Hit hidden ceiling
                    b_cols[idx].error(f"🚨 Penalty Alert!\nAdjusted Max Bid: {format_inr(adjusted_max_bid)}")
                else:
                    # Show normal max bid to keep it secret, or if no penalty exists
                    b_cols[idx].write(f"**{tname}** ({tcap})  \nMax Bid: {format_inr(max_bid)}")
                    
                # Standard Bid Button
                if b_cols[idx].button(f"Bid {format_inr(next_bid)}", key=f"bid_btn_{tname}", disabled=is_disabled, use_container_width=True):
                    models.update_live_bid_state(
                        player_id=active_p["id"],
                        current_bid=next_bid,
                        current_bidder=tname,
                        phase='BIDDING',
                        bid_count=live_state["bid_count"] + 1
                    )
                    models.log_action("BID", player_id=active_p["id"], team_name=tname, amount=next_bid, note=f"{t['captain_name']} bid {format_inr(next_bid)}.")
                    st.rerun()
                    
                # Jump Buttons Row
                j1, j2 = b_cols[idx].columns(2)
                jump_50L = curr_bid + 50_00_000 if curr_bid > 0 else active_p["base_price"] + 50_00_000
                jump_1Cr = curr_bid + 1_00_00_000 if curr_bid > 0 else active_p["base_price"] + 1_00_00_000
                
                if j1.button("+50L", key=f"jump_50_{tname}", disabled=(jump_50L > adjusted_max_bid), use_container_width=True):
                    models.update_live_bid_state(
                        player_id=active_p["id"],
                        current_bid=jump_50L,
                        current_bidder=tname,
                        phase='BIDDING',
                        bid_count=live_state["bid_count"] + 1
                    )
                    models.log_action("BID", player_id=active_p["id"], team_name=tname, amount=jump_50L, note=f"{tcap} jump-bid {format_inr(jump_50L)}.")
                    st.rerun()
                    
                if j2.button("+1Cr", key=f"jump_1c_{tname}", disabled=(jump_1Cr > adjusted_max_bid), use_container_width=True):
                    models.update_live_bid_state(
                        player_id=active_p["id"],
                        current_bid=jump_1Cr,
                        current_bidder=tname,
                        phase='BIDDING',
                        bid_count=live_state["bid_count"] + 1
                    )
                    models.log_action("BID", player_id=active_p["id"], team_name=tname, amount=jump_1Cr, note=f"{tcap} jump-bid {format_inr(jump_1Cr)}.")
                    st.rerun()
                    
            # Custom Bid Entry
            st.markdown("##### Custom Bid Input")
            c_team = st.selectbox("Select Team", [t["name"] for t in teams])
            c_amount = st.number_input(
                "Enter Custom Bid Amount (INR)",
                min_value=int(curr_bid + 10_00_000 if curr_bid > 0 else active_p["base_price"]),
                step=10_00_000
            )
            
            c_team_d = models.get_team(c_team)
            c_max = rules_engine.calculate_max_bid(c_team, active_p["id"], c_team_d["max_squad_size"])
            is_taxed_c = models.rows("SELECT 1 FROM pre_auction_bets WHERE bet_type = 'PREDICTION' AND target_captain = ? AND target_player_id = ?", (c_team_d["captain_name"], active_p["id"]))
            adjusted_c_max = c_max - active_p["base_price"] if is_taxed_c else c_max
            
            if st.button("Submit Custom Bid", use_container_width=True):
                if c_amount > adjusted_c_max:
                    if is_taxed_c and c_amount <= c_max:
                        st.error(f"❌ Secret Penalty Revealed! {c_team} has a pending tax. Their adjusted max bid is {format_inr(adjusted_c_max)}.")
                    else:
                        st.error(f"❌ Custom bid exceeds maximum allowed bid ({format_inr(c_max)}) for {c_team}!")
                elif c_amount < (curr_bid + rules_engine.get_min_increment(curr_bid) if curr_bid > 0 else active_p["base_price"]):
                    st.error("❌ Custom bid amount is too low!")
                else:
                    models.update_live_bid_state(
                        player_id=active_p["id"],
                        current_bid=c_amount,
                        current_bidder=c_team,
                        phase='BIDDING',
                        bid_count=live_state["bid_count"] + 1
                    )
                    models.log_action("BID", player_id=active_p["id"], team_name=c_team, amount=c_amount, note=f"{c_team_d['captain_name']} submitted custom bid of {format_inr(c_amount)}.")
                    st.success(f"Recorded custom bid of {format_inr(c_amount)} for {c_team}.")
                    st.rerun()
                    
            st.html("<hr style='border-color: rgba(255,255,255,0.08);'>")
            
            # SOLD & UNSOLD Declarations
            sd1, sd2 = st.columns(2)
            
            if sd1.button(" Declare SOLD (Initiate RTM+ Check)", disabled=curr_bid == 0, use_container_width=True):
                # Put in RTM+ prompt phase
                models.update_live_bid_state(
                    player_id=active_p["id"],
                    current_bid=curr_bid,
                    current_bidder=bidder,
                    phase='RTM_PROMPT',
                    bid_count=live_state["bid_count"]
                )
                st.success("Standard bidding locked. Prompting for RTM+ triggers.")
                st.rerun()
                
            if sd2.button("Declare UNSOLD", use_container_width=True):
                models.update_player_status(active_p["id"], 'UNSOLD')
                models.log_action("UNSOLD", player_id=active_p["id"], note=f"{active_p['name']} declared unsold.")
                models.clear_live_bid_state()
                st.warning(f"{active_p['name']} is marked as UNSOLD.")
                st.rerun()
                
        
        # ── 2. RTM+ Prompting Phase (Standard Bid Concluded) ──
        elif phase == 'RTM_PROMPT':
            st.markdown("#### RTM+ (Right To Match Plus) Trigger Pending")
            st.write(f"Highest bidder: **{bidder}** for **{format_inr(curr_bid)}**.")
            st.write("Waiting to see if any opponent captain verbally triggers their RTM+ card on this player...")
            
            st.divider()
            
            # Fetch eligible captains (Has RTM left AND is not the current highest bidder)
            # Adjust the column name 'name' if your teams table uses 'team_name' instead
            eligible_teams = models.rows(
                "SELECT captain_name FROM teams WHERE rtm_used = False AND name != ?", 
                (bidder,)
            )
            
            rc1, rc2 = st.columns(2)
            
            with rc1:
                st.markdown("##### Verbal RTM+ Activation")
                if eligible_teams:
                    challenger_names = [t["captain_name"] for t in eligible_teams]
                    selected_challenger = st.selectbox("Select Captain triggering RTM+:", challenger_names)
                    
                    if st.button(f"Activate RTM+ for {selected_challenger}", type="primary", use_container_width=True):
                        # 1. Instant Burn: Mark this captain's RTM+ card as used immediately
                        models.execute("UPDATE teams SET rtm_used = True WHERE captain_name = ?", (selected_challenger,))
                        
                        # 2. Advance state to the Revision phase
                        models.update_live_bid_state(
                            player_id=active_p["id"],
                            current_bid=curr_bid,
                            current_bidder=bidder,
                            phase='RTM_REVISE',
                            rtm_captain=selected_challenger,
                            bid_count=live_state["bid_count"]
                        )
                        
                        models.log_action("RTM+ Activated", player_id=active_p["id"], note=f"Admin verbally activated RTM+ for {selected_challenger} against {bidder}.")
                        st.success(f"RTM+ locked in for {selected_challenger}. Moving to Revision Phase.")
                        st.rerun()
                else:
                    st.warning("No other captains have an RTM+ card available.")
            
            with rc2:
                st.markdown("##### No Challenge")
                # Add some vertical spacing to align the button with the dropdown on the left
                st.write("") 
                st.write("")
                if st.button("No RTM+ Triggered - Declare SOLD", use_container_width=True):
                    buyer_team = models.get_team(bidder)
                    models.update_player_status(active_p["id"], 'SOLD', sold_team=bidder, sold_price=curr_bid)
                    models.update_team_purse(bidder, buyer_team["purse_remaining"] - curr_bid)
                    
                    bonus = rules_engine.check_surprise_bonus(bidder, active_p["id"], active_p["base_price"], curr_bid)
                    if bonus > 0:
                        models.update_team_purse(bidder, models.get_team(bidder)["purse_remaining"] + bonus)
                        models.log_action("BONUS", player_id=active_p["id"], team_name=bidder, amount=bonus, note=f"Surprise Player Bonus: +{format_inr(bonus)}")
                        st.toast(f"🎉 Surprise Player Applied Successfully!", icon="🎁")
                    
                    current_teams = models.get_all_teams()
                    curr_limit = current_teams[0]["max_squad_size"] if current_teams else 10
                    taxes = rules_engine.check_prediction_taxes(bidder, active_p["id"], curr_limit, active_p["base_price"], curr_bid)
                    for tax in taxes:
                        b_t = models.get_team(bidder)
                        models.update_team_purse(bidder, b_t["purse_remaining"] - tax["tax_amount"])
                        models.log_action("TAX", player_id=active_p["id"], team_name=bidder, amount=tax["tax_amount"], note=f"Prediction Tax penalty: -{format_inr(tax['tax_amount'])} triggered by predictor {tax['predictor_captain']}.")
                        st.toast(f"⚠️ Roster Penalty Levied on Team!", icon="🛑")
                        
                    models.clear_live_bid_state()
                    models.log_action("SOLD", player_id=active_p["id"], team_name=bidder, amount=curr_bid, note=f"{active_p['name']} sold to {bidder} for {format_inr(curr_bid)}.")
                    st.success(f"Player SOLD to {bidder} for {format_inr(curr_bid)}!")
                    st.rerun()
                
        # ── 3. RTM+ Revision Phase ──
        elif phase == 'RTM_REVISE':
            st.markdown(f"#### RTM+ Activated by Captain **{live_state['rtm_captain']}**")
            st.write(f"Waiting for highest bidder **{bidder}** to enter their one-time revised bid on their console.")
            st.write("Alternatively, Admin can manually input the revised bid here:")
            
            h_team = models.get_team(bidder)
            h_max = rules_engine.calculate_max_bid(bidder, active_p["id"], h_team["max_squad_size"])
            
            man_rev_bid = st.number_input(
                "Manual Revised Bid (INR)",
                min_value=int(curr_bid + 10_00_000),
                max_value=int(h_max),
                step=10_00_000
            )
            if st.button("Submit Manual Revised Bid", use_container_width=True):
                models.update_live_bid_state(
                    player_id=active_p["id"],
                    current_bid=curr_bid,
                    current_bidder=bidder,
                    phase='RTM_DECIDE',
                    rtm_captain=live_state["rtm_captain"],
                    revised_bid=man_rev_bid,
                    bid_count=live_state["bid_count"]
                )
                models.log_action("REVISE", player_id=active_p["id"], team_name=bidder, amount=man_rev_bid, note=f"Admin entered revised RTM+ bid of {format_inr(man_rev_bid)} on behalf of {bidder}.")
                st.success("Revised bid submitted successfully! RTM+ decider active.")
                st.rerun()
                
        # ── 4. RTM+ Deciding Phase ──
        elif phase == 'RTM_DECIDE':
            st.markdown(f"#### RTM+ Match/Decline Decision Pending")
            st.write(f"RTM Challenger: **{live_state['rtm_captain']}**")
            st.write(f"Revised Bid Price: **{format_inr(live_state['revised_bid'])}**")
            st.write(f"Waiting for {live_state['rtm_captain']} to decide whether to Match or Decline...")
            
            # Overrides
            dc1, dc2 = st.columns(2)
            if dc1.button("Force Match (SOLD to Challenger)", use_container_width=True):
                c_capt = live_state["rtm_captain"]
                c_team = models.get_team_by_captain(c_capt)
                rev_price = live_state["revised_bid"]
                
                models.update_player_status(active_p["id"], 'SOLD', sold_team=c_team["name"], sold_price=rev_price)
                models.update_team_purse(c_team["name"], c_team["purse_remaining"] - rev_price)
                
                # Check surprise/taxes
                bonus = rules_engine.check_surprise_bonus(c_team["name"], active_p["id"],active_p["base_price"], rev_price)
                if bonus > 0:
                    models.update_team_purse(c_team["name"], models.get_team(c_team["name"])["purse_remaining"] + bonus)
                    models.log_action("BONUS", player_id=active_p["id"], team_name=c_team["name"], amount=bonus, note=f"Surprise Player Bonus: +{format_inr(bonus)}")
                current_teams = models.get_all_teams()
                curr_limit = current_teams[0]["max_squad_size"] if current_teams else 10    
                taxes = rules_engine.check_prediction_taxes(c_team["name"], active_p["id"],curr_limit,active_p["base_price"], rev_price)
                for tax in taxes:
                    b_t = models.get_team(c_team["name"])
                    models.update_team_purse(c_team["name"], b_t["purse_remaining"] - tax["tax_amount"])
                    models.log_action("TAX", player_id=active_p["id"], team_name=c_team["name"], amount=tax["tax_amount"], note=f"Prediction Tax penalty: -{format_inr(tax['tax_amount'])} triggered by predictor {tax['predictor_captain']}.")
                    st.toast(f"⚠️ Roster Penalty Levied on Team!", icon="🛑")
                    
                models.log_action("SOLD", player_id=active_p["id"], team_name=c_team["name"], amount=rev_price, note=f"{active_p['name']} sold to {c_team['name']} (Match Override) for {format_inr(rev_price)}.")
                models.clear_live_bid_state()
                st.success("Successfully completed sale to Challenger.")
                st.rerun()
                
            if dc2.button("Force Decline (SOLD to Highest Bidder)", use_container_width=True):
                rev_price = live_state["revised_bid"]
                models.update_player_status(active_p["id"], 'SOLD', sold_team=bidder, sold_price=rev_price)
                models.update_team_purse(bidder, models.get_team(bidder)["purse_remaining"] - rev_price)
                
                # Check surprise/taxes
                bonus = rules_engine.check_surprise_bonus(bidder, active_p["id"], active_p["base_price"], rev_price)
                if bonus > 0:
                    models.update_team_purse(bidder, models.get_team(bidder)["purse_remaining"] + bonus)
                    models.log_action("BONUS", player_id=active_p["id"], team_name=bidder, amount=bonus, note=f"Surprise Player Bonus: +{format_inr(bonus)}")
                    # Drop this straight into your allocation code handlers:
                    st.toast(f"🎉 Surprise Player Applied Successfully!", icon="🎁")

                    
                current_teams = models.get_all_teams()
                curr_limit = current_teams[0]["max_squad_size"] if current_teams else 10
                taxes = rules_engine.check_prediction_taxes(bidder, active_p["id"],curr_limit,active_p["base_price"], rev_price)
                for tax in taxes:
                    b_t = models.get_team(bidder)
                    models.update_team_purse(bidder, b_t["purse_remaining"] - tax["tax_amount"])
                    models.log_action("TAX", player_id=active_p["id"], team_name=bidder, amount=tax["tax_amount"], note=f"Prediction Tax penalty: -{format_inr(tax['tax_amount'])} triggered by predictor {tax['predictor_captain']}.")
                    st.toast(f"⚠️ Roster Penalty Levied on Team!", icon="🛑")
                    
                models.log_action("SOLD", player_id=active_p["id"], team_name=bidder, amount=rev_price, note=f"{active_p['name']} sold to {bidder} (Decline Override) for {format_inr(rev_price)}.")
                models.clear_live_bid_state()
                st.success("Successfully completed sale to Highest Bidder.")
                st.rerun()
                
        # ── 5. Last Bid Joker (Silent Bidding Reveal) ──
        elif phase == 'LAST_BID':
            st.markdown(f"#### 🔒 LAST BID Joker Activated by **{live_state['last_bid_joker_captain']}**")
            st.write("Captains are entering their silent maximum bids on their consoles.")
            
            # Fetch current silent bids count
            s_bids = models.get_silent_bids(active_p["id"])
            st.write(f"Silent bids submitted: **{len(s_bids)} / 4**")
            for sb in s_bids:
                st.write(f"• **{sb['captain_name']}**: *Submitted*")
                
            if st.button("👁️ Reveal Silent Bids & Finalize Sale", disabled=len(s_bids) == 0, use_container_width=True):
                res = rules_engine.resolve_last_bid_joker(active_p["id"])
                if res:
                    w_team = res["winning_team"]
                    w_price = res["winning_price"]
                    w_captain = res["winning_captain"]
                    rtm_available = models.rows(
                        "SELECT COUNT(*) as cnt FROM teams WHERE rtm_plus = 'AVAILABLE'"
                    )[0]["cnt"] > 0
                    if rtm_available:
                        models.update_live_bid_state(
                            player_id=active_p["id"],
                            current_bid=w_price,
                            current_bidder=w_team,
                            phase='RTM_PROMPT'
                        )

                        models.log_action(
                            "RTM_TRIGGER",
                            player_id=active_p["id"],
                            note=f"LAST_BID winner {w_team} at {format_inr(w_price)} routed to RTM phase"
                        )

                        st.info("RTM+ available → moving to RTM challenge phase")
                        st.rerun()
                    else:
                        team_d = models.get_team(w_team)
                        models.update_player_status(active_p["id"], 'SOLD', sold_team=w_team, sold_price=w_price)
                        models.update_team_purse(w_team, team_d["purse_remaining"] - w_price)
                        
                        # Apply surprise/prediction taxes
                        bonus = rules_engine.check_surprise_bonus(w_team, active_p["id"], active_p["base_price"], w_price)
                        if bonus > 0:
                            models.update_team_purse(w_team, models.get_team(w_team)["purse_remaining"] + bonus)
                            models.log_action("BONUS", player_id=active_p["id"], team_name=w_team, amount=bonus, note=f"Surprise Player Bonus: +{format_inr(bonus)}")
                            
                        current_teams = models.get_all_teams()
                        curr_limit = current_teams[0]["max_squad_size"] if current_teams else 10
                        taxes = rules_engine.check_prediction_taxes(w_team, active_p["id"],curr_limit,active_p["base_price"], w_price)
                        for tax in taxes:
                            b_t = models.get_team(w_team)
                            models.update_team_purse(w_team, b_t["purse_remaining"] - tax["tax_amount"])
                            models.log_action("TAX", player_id=active_p["id"], team_name=w_team, amount=tax["tax_amount"], note=f"Prediction Tax penalty: -{format_inr(tax['tax_amount'])} triggered by predictor {tax['predictor_captain']}.")
                            
                        models.log_action("SOLD", player_id=active_p["id"], team_name=w_team, amount=w_price, note=f"{active_p['name']} sold to {w_team} via LAST BID Joker for {format_inr(w_price)}. {res['note']}")
                        models.clear_silent_bids(active_p["id"])
                        models.clear_live_bid_state()
                        st.success(f"Revealed! {w_captain} won with {format_inr(w_price)}!")
                        st.rerun()
                    
            if st.button("Cancel Last Bid Joker State", use_container_width=True):
                models.update_live_bid_state(
                    player_id=active_p["id"],
                    current_bid=curr_bid,
                    current_bidder=live_state["current_bidder"],
                    phase='BIDDING',
                    bid_count=live_state["bid_count"]
                )
                models.clear_silent_bids(active_p["id"])
                st.warning("Last Bid Joker cancelled. Reverted to standard bidding.")
                st.rerun()
                
        st.html('</div>')
        
    if show_reset:
        render_admin_reset_panel()

def render_admin_reset_panel() -> None:
    # ── RESET & CORRECTIONS PANEL ──
    st.html('<div class="admin-section">')
    st.markdown("### ⚠️ Emergency Corrections & Resets")
    
    ec1, ec2 ,ec3 = st.columns(3)
    if ec1.button("Reset Entire Application State", use_container_width=True):
        models.set_global_status("PRE_AUCTION")
        models.clear_live_bid_state()
        models.reset_teams()
        models.clear_marquee_nominations()
        
        # Clear secret bets
        models.execute("DELETE FROM pre_auction_bets")
        models.execute("DELETE FROM silent_bids")
        models.execute("DELETE FROM audit_log")
        
        # Mark all players available
        models.execute("UPDATE players SET status = 'AVAILABLE', sold_team = NULL, sold_price = NULL, sold_at = NULL")
        
        # Reset draft states
        with connect() as con:
            set_state(con, "marquee_draft_order", None)
            set_state(con, "marquee_draft_turn_index", "0")
            set_state(con, "marquee_draft_completed", "FALSE")
            set_state(con, "wheel_target_player_id", None)
            con.commit()
            
        models.log_action("RESET", note="Admin executed entire application state reset.")
        st.warning("Full State Reset Completed! Reverted to Pre-Auction Setup.")
        st.rerun()
        
    if ec2.button("Force Clear Live Bid State", use_container_width=True):
        models.clear_live_bid_state()
        st.info("Live bid state cleared.")
        st.rerun()
    
    # In admin.py under Emergency section
    if ec3.button("↩️ Undo Last Player Transaction", type="secondary", use_container_width=True):
        last_sale = models.one("SELECT * FROM audit_log WHERE action = 'SOLD' ORDER BY id DESC LIMIT 1")
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
            st.warning("No recorded sales matches found inside the audit ledger history.")
    st.html('</div>')
