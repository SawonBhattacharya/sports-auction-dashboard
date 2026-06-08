# LCL Auction 2026 – Official Guidebook

Welcome to the comprehensive guidebook for the **LCL Auction 2026 Dashboard**. This portal is a custom-built, real-time sports auction control and projection application. It provides a seamless, transparent, and highly interactive bidding experience for administrators, team captains, and audiences.

---

## 1. Overall Application Architecture

### **Tech Stack**
- **Frontend & Routing:** [Streamlit](https://streamlit.io/) (v1.33+)
- **Backend & State:** Python 3.12
- **Database:** SQLite (local fallback) or PostgreSQL (via Supabase) with real-time state tracking tables (`live_bid_state`, `audit_log`, `auction_state`).
- **Styling:** Custom CSS injected globally (`ui_components.py`) using modern glassmorphism UI, vibrant gradients, and responsive layouts.

### **Image & Asset Handling**
The app handles team logos and player avatars robustly:
- **Team Logos:** Managed by the Admin. When a team's logo URL is blank, the app gracefully falls back to local placeholders located in `assets/teams/{team_name}.png`.
- **Player Avatars:** Player profiles are pulled from a configured database URL. If a player is missing an image URL, the app automatically generates a sleek, initial-based placeholder using the `ui_components.py` rendering engine.
- **Safe Rendering:** All images are rendered using safe HTML strings securely parsed via Streamlit's native `st.html()` and `st.image()`, ensuring strict sanitization without sacrificing visual quality.

---

## 2. Authentication & Roles

The platform is gated by a central **Login Portal**. Roles are defined by passcode configurations in `config.py` (which can be overridden by Streamlit secrets for production security).

**Available Roles:**
1. **Admin** (Control center)
2. **Viewer** (Read-only audience interface)
3. **Captains** (Sawon, Dragleeoo, Swapneel, Harshit Agarwal)

*Upon logging in, the app securely stores the role in the session state and updates URL parameters to route the user to their designated dashboard.*

---

## 3. Pre-Auction Setup & Strategy

Before the live auction begins, the dashboard operates in **PRE-AUCTION** mode. This allows captains to finalize their strategic moves in secret. 

### **Captain Tasks in Pre-Auction:**
- **Marquee Player Nomination:** Each captain can nominate one "Marquee Player". This locks the player's base price to a premium **₹4.5 Crore** and guarantees they will be the first players auctioned.
- **Surprise Player Submission:** Captains secretly select one player they intend to aggressively target. 
- **Captain Predictions:** Captains predict *who* the other captains have chosen as their Surprise Player. Correct predictions can impose a **"Tax"** (reducing the target captain's purse) or award a **"Bonus"** to the predicting captain during the live auction.

### **Team Constraints:**
- **Initial Purse:** ₹25 Crore per team.
- **Squad Size limit:** 10 Players (Admin can dynamically alter this to 11 if required).
- **Cards:** Each team gets one **RTM+** (Right To Match Plus) and one **Joker Card** (Silent Bid / Forced Nomination).

---

## 4. The Live Auction Flow & The Transparency of the Wheel

Once the Admin launches the auction, the global status shifts to **LIVE_AUCTION**.

### **Phase 1: The Marquee Round**
The auction strictly begins with the Marquee players. 
- The captain who nominated a Marquee player is legally committed to placing the opening bid of ₹4.5 Crore. 
- If no one outbids them, the player is sold to the nominating captain.

### **Phase 2: The Main Spin-Wheel Draw**
To ensure absolute fairness and transparency, all standard players are drawn using a **Randomized Spin Wheel**.
- **Transparency Mechanics:** When the Admin triggers a draw, the backend queries the database for all players with the status `AVAILABLE`. 
- **Filtering:** The system meticulously filters out any players tagged as Marquee or recognized as Team Captains. 
- **The Draw:** The backend securely saves the drawn `target_player_id` into the `auction_state` table.
- **Real-Time View:** Because the target is stored in the central state, the Spin Wheel animation identically triggers on the **Admin**, **Captain**, and **Viewer** screens simultaneously. Everyone watches the wheel spin and land on the exact same player in real-time.

### **Bidding Rules & Tiers**
Bidding increments automatically scale based on the current price:
- **₹0 – ₹1 Cr:** +₹10 Lakhs per bid
- **₹1 Cr – ₹3 Cr:** +₹25 Lakhs per bid
- **₹3 Cr – ₹6 Cr:** +₹50 Lakhs per bid
- **Above ₹6 Cr:** +₹1 Crore per bid

### **The RTM+ and Joker Phases**
If standard bidding ceases on a player, two special phases can be triggered:
1. **RTM+ Phase:** The Admin pauses the block. Opposing captains can choose to burn their RTM+ card to hijack the highest bid. If triggered, the original highest bidder can either match the new inflated price or let the player go.
2. **Last Bid Joker:** If standard bidding is locked, a captain can activate their Joker card. This forces the auction into a **Silent Bid** phase where captains submit blind/sealed bids to secure the player.

---

## 5. Interface Guidebooks

### 🛠️ **Admin Dashboard**
*The command center. Only accessible by the Admin.*
- **Manage Teams:** Edit team names, sync local/remote logo URLs, manually adjust remaining purses, and refund burned RTM+/Joker cards.
- **Live Auction Control:** 
  - Admin controls the tempo. They manually register incoming bids from the floor, advance the bidding tiers, and declare players **SOLD** or **UNSOLD**.
  - They control the UI state for RTM+ prompts and Joker phase reveals.
- **Main Wheel Draw:** The Admin owns the physical button that spins the wheel. They can also cancel/redraw if a technical error occurs.
- **Database Tools:** Sync the Excel Player DB, wipe the auction history, or hard-reset team budgets.

### 🧠 **Captain Dashboard**
*The tactical cockpit.*
- **My Squad Overview:** Displays a live grid of purchased players, tracking total money spent, remaining purse, and remaining squad slots.
- **Pre-Auction Hub:** Where captains submit their secret Marquee, Surprise, and Prediction bets.
- **Live Auction UI:** Watch the current player on the block. Captains track the highest bidder. If they wish to use their Joker or RTM+, they physically trigger it via their dashboard, instantly alerting the Admin screen.

### 📺 **Viewer Dashboard**
*The audience experience.*
- **Live State Rendering:** A beautiful, read-only interface displaying the currently auctioned player, their stats, their base price, and the towering current bid value.
- **Spin Wheel Spectator:** Viewers watch the wheel spin live whenever the Admin triggers a draw.
- **Live Audit Log:** A dynamic, scrolling ledger tracking every bid, draw, and sale. Timestamps are automatically localized to **Indian Standard Time (IST)**.
- **Top 5 Leaderboard:** A live-updating tracker of the highest grossing players sold in the auction.

---

## 6. Technical Maintenance & Troubleshooting
- **Raw HTML / Styling Issues:** The dashboard heavily relies on Streamlit's `st.html()` for rendering complex CSS grids and `<div>` layouts. Never revert structural HTML blocks to `st.markdown(..., unsafe_allow_html=True)` as Streamlit's sanitizer will strip out layout tags and break the UI.
- **Database Resets:** If an auction goes awry, the Admin can safely use the "Reset Auction History" button in the Settings tab. This wipes the audit log and live bid state without deleting the master player roster.
