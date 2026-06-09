Here is a formally structured, highly professional **UAT (User Acceptance Testing) Fault & Discrepancy Log**. It translates the raw observations from your testing team into precise engineering terminology, categorizing them by domain.

This clean documentation format is designed to be fed straight into an LLM or used directly for an efficient vibe-coding session.

---

# 🏆 LCL Auction Engine 2026: UAT Bug & Discrepancy Log

**Document Version:** 1.0.0

**Test Phase:** Comprehensive System Simulation

**Target Architecture:** Streamlit Multi-Device Frontend + SQLite/Supabase Backend

---

## 🟢 Section A: UI/UX & Data Formatting Issues

### 📑 1. Missing Analytics Columns

* **Defect Description:** The player card or player info layouts completely omit the `fielding_dismissals` metrics. Furthermore, while match counts are visible, the corresponding `innings` played are missing.
* **Engineering Impact:** Data parity is broken between the uploaded dataset and the frontend presentation layer.
* **Remediation:** Update `ui_components.py` (specifically `render_player_card`) to display `innings` directly adjacent to `matches`, and incorporate a metrics line for `fielding_dismissals`.

### 🔢 2. Floating-Point Format Inversion on Integer Metrics

* **Defect Description:** Count metrics such as `Runs`, `Matches`, and `Wickets` are casting as floats (e.g., `725.0`, `46.0`).
* **Engineering Impact:** Poor visual presentation. Decimal values should be preserved *only* for structural rates (`economy`, `average`, `strike_rate`) and fractional purse values.
* **Remediation:** Apply strict integer casting (`int(value)`) or explicit format string filtering (`{:.0f}`) to `runs`, `matches`, and `wickets` throughout the visualization modules.

### 🖼️ 3. Asymmetric Media Assets & Rendering Fails

* **Defect Description:** Asset fetching fails on specific players (e.g., *Subhashis Das*, *Abhik Ganguly*), leaving blank placeholders or broken image UI tags.
* **Engineering Impact:** Degraded immersion on client-side dashboards.
* **Remediation:** Verify explicit filename matching in the local storage static paths or check URL schema constraints. Ensure the rendering engine falls back to a clean default avatar vector silhouette if file queries fail.

### 🔄 4. Tab State Amnesia Post-Transaction

* **Defect Description:** Triggering an action like marking a player as `SOLD` forcibly resets the Admin View back to the first tab layout (`Manage Teams`).
* **Engineering Impact:** Extreme layout operational friction for the auctioneer who must continually re-select specific working tabs.
* **Remediation:** Utilize Streamlit's native `key` parameters within `st.tabs` or bind active tab indices to explicit `st.session_state` variables to preserve state memory across script reruns.

---

## 🟡 Section B: Concurrency, Deadlocks, & Synchronization

### 🔒 5. SQLite/Database Thread Contention & Transaction Deadlocks

* **Defect Description:** Spontaneous crash-to-screen failures occur, displaying raw red database exceptions (explicitly pointing to database lockups/deadlocks).
* **Engineering Impact:** Severe multi-device multi-user operations failure. Simultaneous reads/writes across 4+ running client sessions are hitting concurrency boundaries.
* **Remediation:** 1. If running on local SQLite, replace default connect schemes with a WAL (Write-Ahead Logging) configuration (`PRAGMA journal_mode=WAL;`).
2. Implement strict timeout overrides (`sqlite3.connect(..., timeout=30.0)`).
3. Ensure all write steps are executed via unified transaction context handlers inside `db.py`.

### ⏱️ 6. Manual Client-Side State Desynchronization

* **Defect Description:** Global status updates do not consistently propagate immediately down to the Captains' or Admins' client consoles without manual browser updates.
* **Engineering Impact:** Broken real-time coordination during rapid live bidding events.
* **Remediation:** Integrate a soft-polling framework via an invisible background execution loop using `st_autorefresh` or a timed session routine checkpoint to continuously sync state differentials with the central database.

---

## 🔵 Section C: State Machine & Core Rule Architecture Faults

### 🃏 7. Asymmetric RTM Handshakes Across Jokers

* **Defect Description:** The `RTM_PROMPT` flow works cleanly when a player is placed on the block via a *Force Nomination Joker*, but completely fails to trigger or process when concluding a *Last Bid Joker* (Silent Bid resolution phase).
* **Engineering Impact:** Deep rules breach. Per tournament constraints, **all** final bids must pass through an RTM challenge if valid `RTM+` tokens exist.
* **Remediation:** Refactor the silent-bid reveal resolver inside `admin.py`. Instead of transitioning the target record directly to a completed `SOLD` status, reroute the resulting winning metadata into the active `RTM_PROMPT` phase handler.

### 🎡 8. Spin Wheel Rendering Latency Gap

* **Defect Description:** Sizable latency gaps appear between triggering the digital asset wheel spin and displaying the actual calculation outcome/placing the player onto the active bidding block across multiple edge devices.
* **Engineering Impact:** Visual feedback mismatch.
* **Remediation:** Decouple structural state mutation from UI rendering. Ensure that the definitive block placement occurs *only after* the localized client animation routine lifecycle runs its course.

---

## 🟣 Section D: Feedback Loops & Audit Integrity

### 🔔 9. Missing Event Feedback for Bonuses & Penalties

* **Defect Description:** Processing an unexpected *Surprise Player* acquisition or applying a regulatory roster *Penalty* adjusts backend wallets correctly, but fails to surface flash banners, popups, or dedicated toast notifications to the user interface.
* **Engineering Impact:** Confusion regarding account history updates.
* **Remediation:** Add `st.toast()` notices or explicitly place persistent state message widgets into the header sections of both Admin and Captain screens.

### 📝 10. Prediction Ledger Transparency Gap

* **Defect Description:** The Admin console features dedicated view modules for *Surprise Players*, but lacks a tracking interface for *Predictions*. If an algorithmic check fails later, no baseline ledger data is verifiable.
* **Engineering Impact:** Break in auditability and operational fallback safety.
* **Remediation:** Build a secondary structural tab titled `Predictions & Surprise Logs` that reads directly from the persistent `audit_log` or prediction data tables for quick physical cross-checking.

---

## 🔴 Section E: Complex Business Logic & Mathematical Rules

### 🛡️ 11. Verification Logic on Marquee Draft Constraints

* **Defect Description:** In pre-auction configurations, the warning framework that checks for illegal draft submissions (failing to pick the required amount of players) is incorrectly firing on the *Prediction* screen modules.
* **Engineering Impact:** Annoying layout friction that blocks admins from progressing.
* **Remediation:** Scope the validator rules dynamically so they evaluate *only* within the context of the explicit `MARQUEE_AUCTION` workflows.

### 📉 12. Dynamic Rules Engine Out of Sync on Minimum Purse Constraints

* **Defect Description:** The core calculation logic that guards minimum purse values does not adjust dynamically relative to live changes in current squad targets.
* **Engineering Impact:** Risk of critical roster math violations where teams run out of money to draft complete squads.
* **Remediation:** Audit and rewrite calculations inside `rules_engine.py` (specifically `calculate_max_bid`) to verify that the absolute reserve minimum is evaluated on the actual live dynamic squad sizing math.

### 📈 13. Mathematical Floor Defect on Surprise Bonuses

* **Defect Description:** A mathematical edge-case loop exists in the rule: *10% of base price or 25 Lakhs, whichever is higher*. If a player with a base price of 20 Lakhs is acquired and revealed as a *Surprise Player*, the system awards a flat 25 Lakh bonus, which paradoxically exceeds the player's intrinsic base cost.
* **Remediation:** Add a safeguarding logic ceiling rule:
```python
calculated_bonus = max(0.10 * base_price, 25_00_000)
final_bonus = min(calculated_bonus, base_price) # Optional capping step if needed

```



### 🛑 14. Regulatory Capping and Allocation Constraints on Penalties

* **Defect Description:** Financial penalties can mathematically exceed a player's initial valuation. If a penalty calculation causes a team's total cost to surpass their absolute maximum allowable bid parameter, the transaction breaks team minimum reserve requirements.
* **Remediation:** Introduce structural logical checkpoints inside transaction steps:
1. `Penalty` can never scale higher than the initial `base_price`.
2. If `Total Adjusted Cost` (Final Bid + Penalty) exceeds `Max Allowed Bid`, block the allocation completely, reject the purchase, and revert the state.



---

## 🛠️ Section F: Critical Operational Safe-Guards

### ↩️ 15. Transaction Failure/Undo Framework (Admin Reversal)

* **Defect Description:** If the auctioneer mistakenly marks a player as `SOLD` to the wrong team or enters an incorrect price parameter, there is no quick correction tool besides wiping the full database state.
* **Engineering Impact:** High Operational Risk. An administrative input typo can halt or ruin a live room draft.
* **Remediation:** Implement an **Undo Last Sale** feature within the Emergency tab. This module will read the last `SOLD` event from the `audit_log` table, restore that specific player's status parameter to `AVAILABLE`, and credit back the exact transaction balance to the buyer's `purse_remaining` column.

---

## 🟣 Section E: Complex Business Logic & Mathematical Rules *(Cont.)*

### 📉 16. Floor Logic Anomaly on Surprise Player Bonuses

* **Defect Description:** An edge case exists in the rule: *"Surprise player bonus is 10% of the player's base price or ₹25 Lakhs, whichever is higher."* If an Impact tier player is acquired for their base price of ₹20 Lakhs and is subsequently revealed to be a Surprise Player, the engine applies the flat ₹25 Lakh floor bonus. This creates a mathematical anomaly where the bonus payout paradoxically exceeds the player's entire base asset valuation.
* **Engineering Impact:** Unintended inflation of a team's remaining purse capacity, distorting the fair-play environment.
* **Remediation Requirement:** Implement a defensive mathematical ceiling constraint within `rules_engine.py` or the transaction handler so that the surprise bonus can never scale past the player’s intrinsic base cost:
```python
calculated_bonus = max(0.10 * base_price, 25_00_000)
final_bonus = min(calculated_bonus, base_price) # Prevents bonus exceeding base price

```



### 🛑 17. System Solvency & Reserve Capital Breach via Uncapped Penalties

* **Defect Description:** The roster penalty implementation lacks structural boundaries, leading to two major rule violations:
1. A penalty calculation can mathematically scale higher than a player's underlying base valuation.
2. If a post-transaction penalty causes a team's total adjusted outlay to cross into their absolute maximum allowed bid threshold, the system fails to intercept the transaction. The team is left with insufficient reserve funds to fulfill their mandatory minimum squad size.


* **Engineering Impact:** Catastrophic failure of the purse safety engine. Teams are allowed to go bankrupt or hold a negative maximum allowable bid, breaking tournament roster requirements.
* **Remediation Requirement:** Introduce a two-tier structural check during penalty processing loops:
* **Cap the Penalty:** Ensure the calculated penalty value is mathematically restricted to a maximum of the player’s `base_price` (`penalty = min(penalty, base_price)`).
* **Enforce Roster Solvency:** Run a transactional validator. If `Final Sold Price + Applied Penalty > Max Allowed Bid` (calculated relative to the remaining slots needed), the transaction must be blocked, the assignment aborted, and a hard validation error surfaced to the admin console.



---

## 🛠️ Section F: Critical Operational Safe-Guards *(Cont.)*

### ↩️ 18. Absence of Administrative Transaction Reversal Framework (Undo Last Sale)

* **Defect Description:** If the auctioneer accidentally records a player as `SOLD` to the wrong team name or registers an erroneous closing price parameter, there is no system-native mechanism to revert the state.
* **Engineering Impact:** High Operational Vulnerability. An human input error or accidental click by the admin freezes the app state, requiring full database wipes or manual manual data-table mutations mid-auction to correct the ledger.
* **Remediation Requirement:** Build an automated **"Undo Last Transaction"** fallback pipeline under the Emergency corrections block in `admin.py`.
* The handler must retrieve the single latest `SOLD` record from the `audit_log` table.
* It must read the associated `player_id`, `team_name`, and transaction `amount`.
* It must run a safe database wrapper transaction that reverts the player's state back to `AVAILABLE`, subtracts the player from the squad count, and refunds the exact transaction value back to the purchasing team's `purse_remaining` balance.
* Finally, it deletes or marks that specific row in the `audit_log` as voided and triggers a clean `st.rerun()`.