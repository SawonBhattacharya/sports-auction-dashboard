LCL Auction 2026 — Enhanced Dashboard Implementation Plan v3
Goal Description
Enhance the LCL Auction 2026 application with committee-approved rules, strict UI constraints, secure credential storage, synchronized animated spin wheel drawing, comprehensive team/roster analytics across all views, and query-parameter-based routing to prevent session conflicts.

User Review Required
IMPORTANT

To ensure the application behaves exactly as expected, please verify the following:

Automated Surprise Players: The Admin panel will only have an "Auto-Assign Surprise Players" button. No manual override selectboxes will be provided.
Prediction Submission Warning: Captains can choose predictions for rival captains. If they try to submit predictions for all 3 rival captains, a warning will pop up and the "Submit Predictions" button will be disabled. They must predict for at most 2 rivals.
Player Photo Card: When a player is active or drawn on the block, their card will render their photo from images/players/{player_id}.png (or .jpg), falling back gracefully to a premium silhouette placeholder.
Live Bid Refresh: All views (Admin, Captain, and Viewer) will auto-refresh every 2 seconds during the live bidding phase, ensuring purses and maximum bids update immediately after every bid.
Proposed Changes
1. Database & Secrets Configuration
[MODIFY] 
.streamlit/secrets.toml
Move all captain passcodes from config.py into the secrets file:
toml

[
passcodes
]
admin = "LCL_Admin@2026#S2"
viewer = "LCL"
Sawon = "sawon123"
Dragleeoo = "drag123"
Swapneel = "swap123"
"Aman Jaiswal" = "aman123"
[MODIFY] 
config.py
Remove hardcoded passcodes. Read PASSCODES dynamically from st.secrets["passcodes"] with safe fallbacks.
2. Shared UI Components & Assets
[MODIFY] 
ui_components.py
Shared Team Progress Grid: Implement a unified function render_team_progress_grid(active_player_id) to draw the 4 squads, showing roster slots, remaining purse, and maximum allowed bid (calculated via safety engine).
Synchronized Spin Wheel: Refactor the Canvas-based Spin Wheel HTML/JS to:
Exclude captains and marquee players.
Track the current spin_target_player_id in localStorage to run the animation exactly once per draw per browser tab.
Automatically show the player's full stats and photo card once the wheel stops spinning.
Player Card Component: Create a standard render_player_card(player_id) displaying:
Player name, seeding, and base price.
Player stats (Matches, Runs, Average, Strike Rate, Wickets, Economy).
Player photo from /images/players/{player_id}.png or /images/players/{player_id}.jpg (if exists), otherwise fallback to local silhouette.
3. Routing & Session Management
[MODIFY] 
app.py
Detect st.query_params on load (e.g., ?role=Admin, ?role=Sawon). If present, automatically authenticate and route the tab to the corresponding view, solving multi-tab login overrides.
Implement @st.fragment(run_every=2) autorefresh sections for the Viewer, Captain, and Admin dashboards during live bidding to keep the consoles in sync without manual page reloads.
4. Admin Panel Enhancements
[MODIFY] 
views/admin.py
Surprise Player Setup: Add a system button to auto-assign 1 surprise player randomly to each captain. Remove manual overrides.
Bidding Enhancements: Add captain names next to team names on all bidding buttons (e.g. Team Alpha - Dragleeoo).
Dark Mode: Integrate inject_css() to keep the styling consistent with other views.
Joker & Strategy Dashboard: Render a summary panel showing:
RTM+ status (used/remaining) for all captains.
Joker card type (FN/LB) and usage status.
Active predictions made by captains (for admin oversight).
Roster Overview: Render the shared team progress grid.
Active Block Display: Render the render_player_card component when a player is active.
5. Captain Console Enhancements
[MODIFY] 
views/captain.py
Prediction Limit Warning: Provide a "Submit Predictions" button. If the captain has selected 3 predictions, show a warning: "⚠️ Cannot submit. Maximum 2 predictions allowed." and disable the button.
No Duplicate Marquees: Filter the marquee nomination dropdown to exclude players already nominated by other captains.
Assigned Surprise Player: Hide the surprise selector dropdown; display the admin-assigned surprise player instead.
Team Info & Logo: Render proper team names, captain details, and team logo from images/team_logo/ (with fallback).
Roster & Max Bid Widget: Render the shared team progress grid for the other 3 captains.
Active Block Display: Render the render_player_card component when a player is active.
6. Public Viewer Page
[MODIFY] 
views/viewer.py
Integrate the updated synchronized Spin Wheel, render_player_card, and shared team progress grid.
Verification Plan
Automated Verification
Run the integration test suite:

bash

$env:PYTHONIOENCODING="utf-8"; .venv\Scripts\python C:\Users\PC\.gemini\antigravity\brain\5d1cc98f-6f49-4e36-b0a8-e1474094188f\scratch\test_flow.py
Manual Verification Checklist
 Log in via URL parameter ?role=Admin and verify it bypasses the login screen.
 Assign surprise players from the Admin Panel. Verify they appear in the Captain consoles.
 Try to submit 3 predictions as a Captain. Verify that a warning pops up and the button is disabled. Submit 2 and verify success.
 Nominating a marquee player removes them from the dropdown of other captains.
 Verify that buying players correctly decrements their team's purse and adjusts the maximum allowed bid of all teams dynamically, refreshing all views every 2 seconds.
 Trigger a spin, verify the wheel spins and lands on the designated player on all tabs, then reveals the player card.