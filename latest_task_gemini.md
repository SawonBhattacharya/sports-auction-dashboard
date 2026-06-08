LCL Auction 2026 — v3 Enhancement Checklist
1. Secrets & Config
 Move passcodes from config.py to .streamlit/secrets.toml
 Update config.py to read PASSCODES from st.secrets with fallback
 Update login.py to use new PASSCODES source
2. Routing & Session Fix
 Add query_params routing in app.py (?role=Admin, ?role=Sawon, etc.)
 Add @st.fragment(run_every=2) for Admin view during LIVE_AUCTION
 Ensure all views auto-refresh purse/max-bid during live bidding
3. UI Components
 Add render_player_card() component with photo support + silhouette fallback
 Add render_team_progress_grid() shared component (roster, purse, max bid)
 Refactor Spin Wheel to show all remaining player names, animate, land on target
 Ensure inject_css() is called in Admin view for dark mode consistency
4. Admin Panel Enhancements
 Add inject_css() call for dark mode
 Add "Auto-Assign Surprise Players" button (no manual override)
 Add captain names beside team names on bid buttons
 Add Joker/RTM+ strategy dashboard panel
 Add prediction overview panel for admin
 Add team progress grid (roster, purse, max bid for all 4 teams)
 Add player card display when player is on block
5. Captain Console Enhancements
 Enforce 2-prediction limit with warning + disabled submit button
 Filter marquee dropdown to exclude already-nominated players
 Display admin-assigned surprise player (read-only)
 Add team logo rendering from images/team_logo/ with fallback
 Add other teams' roster/purse/max-bid grid
 Add player card display when player is on block
6. Viewer Page
 Integrate updated Spin Wheel with all player names
 Add player card on active block
 Ensure team progress grid shows updated purse/max-bid
7. Verification
 Run integration test suite
 Launch Streamlit and test multi-tab via ?role= params