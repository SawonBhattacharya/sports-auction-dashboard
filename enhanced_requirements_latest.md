Here is the finalized system specification with the squad size configuration updated to be fully dynamic. The baseline is set to **10 players per team (40 total)**, but the architecture is explicitly defined to handle an runtime increase to **11 players per team (44 total)** via a single global configuration toggle.

---

# System Specification: LCL Auction 2026 Production Dashboard

## 1. Project Overview & Architecture

Transform the legacy Streamlit auction dashboard into a real-time, zero-latency, state-managed production application. The app must decouple frontend rendering from the **Supabase cloud SQL database** to maintain atomic state persistence while eliminating lag.

---

## 2. Core Constraints & Configuration

* **Captains (4 Teams):** Sawon, Dragleeoo, Swapneel, Aman Jaiswal.
* **Initial Purse:** ₹25 Crore per team.
* **Dynamic Squad Size Configuration:**
* **Baseline:** Exactly **10 players per team** (1 Captain + 9 Auction Buys) $\rightarrow$ Total Tournament Roster = **40 players**.
* **Scalability Buffer:** The system architecture must dynamically support an increase to **11 players per team** (1 Captain + 10 Auction Buys) $\rightarrow$ Total Tournament Roster = **44 players** via a single global configuration parameter in the database/environment settings without rewriting code logic.


* **Base Roster Rules:**
* Captains are part of the roster automatically but have **no base price** and do not drain the initial purse.
* Remove all player role categorizations (Batter, Bowler, All-Rounder) since every player bowls.
* Remove the "Exclude from Auction" feature. All players in the master pool (40 or 44) must be accessible in the Supabase database.


* **Database Schema Additions (Excel Ingestion):** The uploaded data pool includes two specific mandatory columns:
* `Seeding` (For player ranking/grouping)
* `Base Price` (Stored as raw numeric strings with zeros, e.g., `50,000,00` or `5000000`).



---

## 3. High-Performance Architecture & Caching Strategy

* **Targeted Rendering (`st.fragment`):** Wrap the active bidding block, live log ticker, visual analytics, and leaderboards in independent `@st.fragment` decorators. Clicks on bidding buttons must *only* rerun that specific fragment, preventing a full-page reload and eliminating visual stutter.
* **Database Connection Pooling:** Utilize `st.connection("sql", type="sql")` to handle persistent connection pooling to Supabase. Never open and close raw database connections on every user click.
* **Static Asset Caching & Pictures Rendering:** Cache all static player images, captain pictures, and team logos using `st.cache_data`. If a player picture fails to load or has a broken path, gracefully render a standard local silhouette placeholder instead of throwing a UI-breaking exception.
* **UI/UX Data Transformer:** Raw currency strings from the database containing complex trailing zeros (e.g., `50,000,00`) must be dynamically parsed on the backend and formatted into clean, highly readable UI strings (e.g., **50 Lakh** or **1.5 Cr**) before rendering on any screen.

---

## 4. Data Isolation & Security Boundaries (Zero Leakage)

Because this app runs on a shared server, data security must be handled at the database query level to prevent malicious or accidental data exposure via browser inspection:

* **Role Enforcement:** Authenticate views based on session state or secure URL parameters (e.g., `?role=captain&name=Sawon`).
* **Backend Data Masking:** When a user is in `Viewer` or a different `Captain` role, the SQL queries fetching data *must explicitly omit* columns related to secret choices. For example:

```sql
-- Executed ONLY when Captain 'Sawon' is logged in:
SELECT surprise_player FROM pre_auction_bets WHERE captain_name = 'Sawon';

-- Executed for Public Viewers (Completely blind to selections):
SELECT team_name, purse_remaining FROM teams;

```

* **No Client-Side Filtering:** Never download the full state table to Python and filter it in the UI. All filtering must happen on the secure database side.

---

## 5. Concurrency Control & Atomic Transactions

In a fast-paced live auction, two captains might hit the "Bid" button at the exact same millisecond. To prevent race conditions or phantom over-writes:

* **No Read-Then-Write in Python:** Do not fetch a purse value to Python, subtract the bid, and write it back.
* **Atomic SQL Updates:** Use atomic transactions with conditional `WHERE` clauses directly in SQL to evaluate validity instantly at the database engine level:

```sql
UPDATE teams 
SET purse_remaining = purse_remaining - :bid_amount 
WHERE team_id = :team_id AND (purse_remaining - :bid_amount) >= :reserve_required;

```

* If `rowcount == 0` is returned, the database blocked the transaction because the team didn't have enough money, allowing the UI to instantly trigger a safe error banner without breaking app state.

---

## 6. Pre-Auction Initialization Phase (Setup Wizard)

Before the main auction engine unlocks, the application must enter a formal **Pre-Auction State**. The app will handle a step-by-step setup wizard to finalize the following 4 parameters. All inputs must be saved securely to Supabase before the main auction can begin:

1. **Lottery of Joker:** An Admin button trigger that randomly distributes exactly 1 Joker card to each of the 4 captains from the global pool (2 Force Nomination Jokers, 2 Last Bid Jokers).
2. **Nomination of Marquee:** An interface to designate or review the top-tier Marquee players within the initial pool, locking their positions/status based on their `Seeding` before the standard draw loop.
3. **Prediction Tax Entries:** Submitted securely and privately via individual Captain Views. Captains submit up to 2 secret predictions matching a rival Captain $\rightarrow$ Player. *(Rule: Captains cannot select themselves).*
4. **Surprise Player Selection:** Submitted securely and privately via individual Captain Views. Each of the 4 captains secretly selects exactly 1 unique player from the master list.

*State Lock:* Once all four tasks are complete, an Admin action button **"Lock Pre-Auction & Launch Main Event"** will flip the database global state flag to `LIVE_AUCTION`, clearing the setup screen and opening the main auction dashboards.

---

## 7. Bid Validation & Increment Rule Engine

### A. Bid Increment Rules

Bidding buttons must dynamically calculate and enforce minimum increment boundaries based on the current active bid value:

| Current Bid Range | Minimum Allowed Increment |
| --- | --- |
| ₹0 – ₹1 Crore | + ₹10 Lakhs |
| Above ₹1 Crore – ₹3 Crore | + ₹25 Lakhs |
| Above ₹3 Crore – ₹6 Crore | + ₹50 Lakhs |
| Above ₹6 Crore | + ₹1 Crore |

*Note: Captains can always type/submit a custom bid higher than the minimum threshold.*

### B. Dynamic Minimum Purse Rule (Safety Engine)

To prevent a team from running out of money before completing their total squad requirements, the system must calculate a real-time validation check on *every single bid attempt*. This algorithm adapts dynamically whether the configuration target ($T$) is set to 10 or 11 players.

**Player Cost Tiers:**

* **Impact:** ₹0.2 Cr each
* **Rising:** ₹0.5 Cr each
* **Premium:** ₹1.0 Cr each
* **Icon:** ₹2.0 Cr each

**The Formula:**
When checking a live bid, assume the active player is successfully purchased. Calculate the slots remaining *after* this theoretical purchase based on current rules:

$$\text{SlotsAfterPurchase} = \text{PlayersStillRequired} - 1$$

Calculate the minimum reserve required sequentially from the remaining unauctioned player pool ($R_{\text{Tier}}$):

1. $\text{ImpactUsed} = \min(\text{SlotsAfterPurchase}, R_{\text{Impact}})$
2. $\text{RisingUsed} = \min(\max(\text{SlotsAfterPurchase} - R_{\text{Impact}}, 0), R_{\text{Rising}})$
3. $\text{PremiumUsed} = \min(\max(\text{SlotsAfterPurchase} - R_{\text{Impact}} - R_{\text{Rising}}, 0), R_{\text{Premium}})$
4. $\text{IconUsed} = \min(\max(\text{SlotsAfterPurchase} - R_{\text{Impact}} - R_{\text{Rising}} - R_{\text{Premium}}, 0), R_{\text{Icon}})$

$$\text{Reserve Required} = (\text{ImpactUsed} \times 0.2) + (\text{RisingUsed} \times 0.5) + (\text{PremiumUsed} \times 1.0) + (\text{IconUsed} \times 2.0)$$

$$\text{Maximum Allowed Bid} = \text{Current Purse} - \text{Reserve Required}$$

*Enforcement: If a captain attempts a manual or incremental bid that exceeds $\text{Maximum Allowed Bid}$, the system must reject the bid, trigger a warning flag, and disable the bidding button for that captain.*

---

## 8. Gamification & Special Rules Engines

### Rule 1: Player Selection System

* Implement a visual **Spin Wheel UI component** (using HTML/JS via components or high-performance CSS animation) to select the next player from the remaining active roster.
* *Exception:* Provide a "Force Nomination Joker" toggle that allows a captain to override the wheel outcome and pull any unsold player directly to the auction block.

### Rule 2: RTM+ (Right To Match Plus)

Every captain possesses exactly 1 RTM+ Card. Implement this multi-stage workflow:

1. Standard bidding concludes with a highest bidder (Captain A) at a closing price (Price X).
2. Before declaring "SOLD", display a prompt on the screens: *"Does any other captain want to trigger RTM+?"*
3. If Captain B activates RTM+, Captain A gets a **one-time option** to input a *Revised Bid* (Price Y, where Y > X).
4. Captain B must then choose:
* **Match:** Captain B pays Price Y and wins the player.
* **Decline:** Captain A pays Price Y and wins the player.


5. Mark Captain B's RTM+ card as used in the database state.

### Rule 3: Surprise Player Bonus

* **Trigger Phase:** The moment a player is marked as "SOLD" in the database, check if that player belongs to the purchasing captain's secret pre-auction choice list.
* **Execution:** If true, instantly calculate a bonus credit: `Max(10% of Final Price, ₹25 Lakhs)`. Add this bonus back into that captain's active auction purse.

### Rule 4: Prediction Tax Rule

* **Trigger Phase:** When a player is sold, verify if the purchase matches a prediction submitted during the pre-auction phase.
* **Execution:** If a prediction comes true, assess a penalty tax on the predicting captain: `Max(10% of Final Price, ₹25 Lakhs)`. Automatically deduct this amount from the predicting captain's active auction purse.

### Rules 5 & 6: Joker Lottery & Force Nomination

* **Force Nomination Execution:** A one-time action that overrides the Spin Wheel. It forces an immediate auction block for an unsold player. Ensure this button is completely disabled during an ongoing live auction.

### Rule 7: Last Bid Joker

* **Trigger Phase:** Can be activated by a captain right before an asset is finalized as "SOLD".
* **Execution Workflow:**
1. Freeze standard public bidding.
2. Open an isolated/silent bidding input for interested captains to submit a hidden maximum bid.
3. Evaluate inputs: The highest silent bid wins the player.
4. *Tie Rule:* If a tie occurs and one of the tied captains is the original holder of the active Last Bid Joker, they automatically win the tie-breaker and secure the player at that bid amount.



---

## 9. Role-Based Access Control & App Views

The interface must branch into 3 separate view structures based on a user role selection component (or secure URL parameters like `?role=viewer`, `?role=captain&id=Sawon`, or `?role=admin`).

### A. Viewer / Public View (Read-Only Screen)

* Optimized for a projection screen or regular users enjoying the auction.
* **Completely Read-Only:** Contains absolutely no action buttons, inputs, or text forms.
* Displays the active player block, live bidding logs, real-time updated leaderboards (purses, remaining spots), and the visual animated Spin Wheel.
* Hides all confidential info (secret inputs, active countdowns for silent bidding until revealed by the admin).
* **Live Analytics Widgets Panel:**
* **4 Captain Thumbnail Cover:** A prominent top-level grid header display showcasing high-res profile shortcuts of all 4 captains (Sawon, Dragleeoo, Swapneel, Aman Jaiswal) alongside their real-time remaining purse (formatted cleanly) and total secured player counts.
* **Top 5 Highest Grossing Players:** A live leaderboard tracker capturing the top 5 most expensive player acquisitions of the night, detailing player names, buying teams, and the final formatted sale amount.
* **Team Build Progress Grid:** A visual progress matrix or squad gallery showing how close each team is to completing their full roster slots (**scaling automatically to 10 or 11 empty slots** depending on active constraints), displaying acquired player pictures side-by-side with empty placeholder silhouettes.



### B. Captain View (Interactive Console)

* Features a login select dropdown at initialization to pick which Captain is active (Sawon, Dragleeoo, Swapneel, Aman Jaiswal).
* Includes the top-level **4 Captain Thumbnail Summary** as a header widget for tracking opponent resources in real time.
* **Pre-Auction Interface:** Renders the private fields for submitting the **Prediction Tax Entries** and the **Surprise Player Selection** without showing rival captains' choices.
* **Live Auction Interface:** Displays standard live bidding buttons (+10L, +25L, etc.) along with custom bid text inputs.
* **Team Build Tracker:** A personal visual workspace grid showing their current roster status towards the configured 10 or 11-player limit.
* **Joker Actions:** Contains individual toggle triggers for activating the *Force Nomination Joker*, *Last Bid Joker*, and *RTM+* if available.
* **Silent Bidding Mask:** When the Last Bid Joker is active, a temporary pop-up modal or dedicated text input block appears allowing *only* this specific captain to submit a hidden bid directly to the database.

### C. Admin Control Panel

* Dashboard interface reserved for the auctioneer/coordinator.
* Houses the initial **Excel File Uploader** to map the master spreadsheet into Supabase, automatically verifying the parsing of `Seeding` and raw `Base Price` string formats.
* **Global Target Configuration Dropdown:** Allows the Admin to select/toggle between **10 Players (40 Total)** and **11 Players (44 Total)** configurations before freezing the pre-auction phase.
* Displays full administrative overviews of the **Team Build Progress** grids and **Top 5 Highest Grossing** stats.
* Controls the lifecycle of the auction: manually triggers the Joker Lottery distribution, triggers the Spin Wheel spin, opens/closes RTM+ windows, and officially clicks the **"SOLD"** or **"UNSOLD"** master validation buttons.