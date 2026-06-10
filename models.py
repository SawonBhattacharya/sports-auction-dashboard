import re
import pandas as pd
from pathlib import Path
from typing import Any, Optional
from db import connect, rows, one, execute, utc_now, clean_text, number_or_none, get_state, set_state
from config import TIER_COSTS, INITIAL_PURSE, CAPTAINS, MARQUEE_BASE_PRICE

def clean_excel_formula_price(val: Any, seeding: str) -> int:
    """Safely extracts raw base price from Excel values or formulas."""
    if val is None or pd.isna(val):
        return TIER_COSTS.get(seeding, 20_00_000)
    
    # If it's a float/int
    if isinstance(val, (int, float)):
        return int(val)
        
    s = str(val).strip()
    if not s:
        return TIER_COSTS.get(seeding, 20_00_000)
        
    # Check if it's a numeric string
    # Remove commas, symbols
    num_str = re.sub(r"[^\d]", "", s)
    if num_str:
        return int(num_str)
        
    # Fallback to Seeding mapping
    return TIER_COSTS.get(seeding, 20_00_000)

def _row_value(row: Any, *column_names: str) -> Any:
    for column_name in column_names:
        if column_name in row:
            return row.get(column_name)
    return None

def import_players_from_excel(path: Path, replace_existing: bool = True) -> int:
    """Reads the Clean_Player_DB sheet from the Excel file and imports players into DB."""
    workbook = pd.ExcelFile(path)
    if "Clean_Player_DB" not in workbook.sheet_names:
        raise ValueError("Workbook must include a Clean_Player_DB sheet.")

    stats = pd.read_excel(workbook, sheet_name="Clean_Player_DB")
    stats.columns = [clean_text(c).replace("\n", " ") for c in stats.columns]
    stats = stats.dropna(how="all")
    stats = stats[stats.get("Name").notna()]
    stats["Name"] = stats["Name"].map(clean_text)

    count = 0
    now = utc_now()
    
    with connect() as con:
        if replace_existing:
            con.execute("DELETE FROM players")
            set_state(con, "active_player_id", None)
            con.execute("DELETE FROM audit_log")
            con.execute("UPDATE teams SET purse_remaining = starting_purse, rtm_used = FALSE")
            
        for idx, row in stats.iterrows():
            name = clean_text(row.get("Name"))
            if not name:
                continue
                    
            player_id = clean_text(row.get("Player ID"))
            if not player_id:
                # If Player ID has decimals, format cleanly
                val = row.get("Player ID")
                if isinstance(val, float):
                    player_id = str(int(val))
                else:
                    player_id = f"P{idx + 1:03d}"
            else:
                # Strip decimal format if player_id is float representation
                if player_id.endswith(".0"):
                    player_id = player_id[:-2]
                    
            seeding = clean_text(row.get("Seeding")) or "Impact"
            if seeding not in TIER_COSTS:
                seeding = "Impact"
                
            base_price = clean_excel_formula_price(row.get("Base Price"), seeding)
            
            batting = clean_text(row.get("Batting"))
            bowling = clean_text(row.get("Bowling"))
            bowling_preference = clean_text(row.get("Bowling Preference"))
            fielding_dismissals = clean_text(row.get("Fielding Dismissals"))
            profile_url = clean_text(row.get("Profile"))
            # Extract URL if hyperlink formula
            url_match = re.search(r'HYPERLINK\("([^"]+)"', profile_url, re.IGNORECASE)
            if url_match:
                profile_url = url_match.group(1)
            elif not profile_url.startswith("http"):
                profile_url = ""

            con.execute(
                """
                INSERT INTO players (
                    id, name, seeding, base_price, matches, innings,
                    runs, average, strike_rate, best_score, wickets, economy,
                    fielding_dismissals, batting, bowling, bowling_preference,
                    profile_url, status, updated_at
                ) VALUES (
                    :id, :name, :seeding, :base_price, :matches, :innings,
                    :runs, :average, :strike_rate, :best_score, :wickets, :economy,
                    :fielding_dismissals, :batting, :bowling, :bowling_preference,
                    :profile_url, 'AVAILABLE', :updated_at
                )
                ON CONFLICT(id) DO UPDATE SET
                    name = EXCLUDED.name,
                    seeding = EXCLUDED.seeding,
                    base_price = EXCLUDED.base_price,
                    matches = EXCLUDED.matches,
                    innings = EXCLUDED.innings,
                    runs = EXCLUDED.runs,
                    average = EXCLUDED.average,
                    strike_rate = EXCLUDED.strike_rate,
                    best_score = EXCLUDED.best_score,
                    wickets = EXCLUDED.wickets,
                    economy = EXCLUDED.economy,
                    fielding_dismissals = EXCLUDED.fielding_dismissals,
                    batting = EXCLUDED.batting,
                    bowling = EXCLUDED.bowling,
                    bowling_preference = EXCLUDED.bowling_preference,
                    profile_url = EXCLUDED.profile_url,
                    updated_at = EXCLUDED.updated_at
                """,
                {
                    "id": player_id,
                    "name": name,
                    "seeding": seeding,
                    "base_price": base_price,
                    "matches": number_or_none(row.get("Matches")),
                    "innings": number_or_none(row.get("Innings")),
                    "runs": number_or_none(row.get("Runs")),
                    "average": number_or_none(row.get("Avg")),
                    "strike_rate": number_or_none(row.get("SR")),
                    "best_score": clean_text(row.get("Best Score")),
                    "wickets": number_or_none(row.get("Wickets")),
                    "economy": number_or_none(row.get("Economy")),
                    "fielding_dismissals": number_or_none(_row_value(row, "Fielding Dismissals", "Fielding  Dismissals")),
                    "batting": batting,
                    "bowling": bowling,
                    "bowling_preference": bowling_preference,
                    "profile_url": profile_url,
                    "updated_at": now
                }
            )
            count += 1
            
        con.execute(
            "INSERT INTO audit_log(action, note, created_at) VALUES (?, ?, ?)",
            ("SYNC", f"Imported {count} players from Excel file", now)
        )
        con.commit()
    return count

# ── Teams CRUD ──────────────────────────────────────────────────────────────

def get_all_teams() -> list[dict]:
    return rows("SELECT * FROM teams ORDER BY name")

def get_team(name: str) -> Optional[dict]:
    return one("SELECT * FROM teams WHERE name = ?", (name,))

def get_team_by_captain(captain_name: str) -> Optional[dict]:
    return one("SELECT * FROM teams WHERE captain_name = ?", (captain_name,))

def update_team_details(
    original_name: str,
    name: str,
    logo_url: str,
    starting_purse: int,
    purse_remaining: int,
    max_squad_size: int,
    rtm_used: bool,
    joker_type: Optional[str],
) -> None:
    """Update editable team fields and cascade team-name references used by auction state."""
    with connect() as con:
        con.execute(
            """
            UPDATE teams
            SET name = ?, logo_url = ?, starting_purse = ?, purse_remaining = ?,
                max_squad_size = ?, rtm_used = ?, joker_type = ?
            WHERE name = ?
            """,
            (
                name,
                logo_url,
                starting_purse,
                purse_remaining,
                max_squad_size,
                bool(rtm_used),
                joker_type,
                original_name,
            ),
        )
        if original_name != name:
            con.execute("UPDATE players SET sold_team = ? WHERE sold_team = ?", (name, original_name))
            con.execute("UPDATE audit_log SET team_name = ? WHERE team_name = ?", (name, original_name))
            con.execute("UPDATE live_bid_state SET current_bidder = ? WHERE current_bidder = ?", (name, original_name))
        con.commit()

def update_team_purse(team_name: str, purse_remaining: int) -> None:
    execute("UPDATE teams SET purse_remaining = ? WHERE name = ?", (purse_remaining, team_name))

def mark_rtm_used(team_name: str) -> None:
    execute("UPDATE teams SET rtm_used = TRUE WHERE name = ?", (team_name,))

def reset_teams() -> None:
    """Resets all teams to starting purse, RTM unused, and default configuration."""
    execute("UPDATE teams SET purse_remaining = starting_purse, rtm_used = FALSE")

def update_squad_size_limit(limit: int) -> None:
    """Sets max squad size config for all teams."""
    execute("UPDATE teams SET max_squad_size = ?", (limit,))

# ── Players CRUD ────────────────────────────────────────────────────────────

def get_all_players() -> list[dict]:
    return rows("SELECT * FROM players ORDER BY name")

def get_player(player_id: str) -> Optional[dict]:
    return one("SELECT * FROM players WHERE id = ?", (player_id,))

def get_available_players() -> list[dict]:
    return rows("SELECT * FROM players WHERE status = 'AVAILABLE' ORDER BY name")

def get_marquee_players() -> list[dict]:
    return rows("SELECT * FROM players WHERE is_marquee = TRUE ORDER BY name")

def update_player_status(player_id: str, status: str, sold_team: Optional[str] = None, sold_price: Optional[int] = None) -> None:
    now = utc_now()
    if status == 'SOLD':
        execute(
            "UPDATE players SET status = ?, sold_team = ?, sold_price = ?, sold_at = ?, updated_at = ? WHERE id = ?",
            (status, sold_team, sold_price, now, now, player_id)
        )
    else:
        execute(
            "UPDATE players SET status = ?, sold_team = NULL, sold_price = NULL, sold_at = NULL, updated_at = ? WHERE id = ?",
            (status, now, player_id)
        )

# ── Pre-Auction Selection & Marquee ──────────────────────────────────────────

def nominate_marquee(player_id: str, captain_name: str) -> None:
    """Designates a player as marquee, updates base price to 4.5cr, and tracks nominator."""
    now = utc_now()
    execute(
        "UPDATE players SET is_marquee = TRUE, marquee_nominator = ?, base_price = ?, updated_at = ? WHERE id = ?",
        (captain_name, MARQUEE_BASE_PRICE, now, player_id)
    )

def clear_marquee_nominations() -> None:
    """Clears all marquee nominations and reverts base prices based on Seeding."""
    with connect() as con:
        # Fetch current marquee players
        marquees = con.execute("SELECT id, seeding FROM players WHERE is_marquee = TRUE").fetchall()
        for m in marquees:
            pid = m["id"]
            seeding = m["seeding"]
            original_price = TIER_COSTS.get(seeding, 20_00_000)
            con.execute(
                "UPDATE players SET is_marquee = FALSE, marquee_nominator = NULL, base_price = ? WHERE id = ?",
                (original_price, pid)
            )
        con.commit()

# ── Surprise Players & Predictions CRUD ──────────────────────────────────────

def save_surprise_player(
    captain_name: str,
    player_id: str
) -> None:

    now = utc_now()
    with connect() as con:
        con.execute("DELETE FROM pre_auction_bets WHERE captain_name = ? AND bet_type = 'SURPRISE'", (captain_name,))
        con.execute(
            "INSERT INTO pre_auction_bets (captain_name, bet_type, target_player_id, created_at) VALUES (?, 'SURPRISE', ?, ?)",
            (captain_name, player_id, now)
        )
        con.commit()

def get_surprise_player(captain_name: str) -> Optional[str]:
    row = one("SELECT target_player_id FROM pre_auction_bets WHERE captain_name = ? AND bet_type = 'SURPRISE'", (captain_name,))
    return row["target_player_id"] if row else None

def save_prediction(captain_name: str, target_captain: str, player_id: str) -> None:
    now = utc_now()
    with connect() as con:
        con.execute("DELETE FROM pre_auction_bets WHERE captain_name = ? AND bet_type = 'PREDICTION' AND target_captain = ?", (captain_name, target_captain))
        con.execute(
            "INSERT INTO pre_auction_bets (captain_name, bet_type, target_captain, target_player_id, created_at) VALUES (?, 'PREDICTION', ?, ?, ?)",
            (captain_name, target_captain, player_id, now)
        )
        con.commit()

def get_predictions(captain_name: str) -> list[dict]:
    return rows(
        "SELECT target_captain, target_player_id FROM pre_auction_bets WHERE captain_name = ? AND bet_type = 'PREDICTION'",
        (captain_name,)
    )

def get_all_predictions() -> list[dict]:
    return rows("SELECT * FROM pre_auction_bets WHERE bet_type = 'PREDICTION'")

def get_all_surprise_players() -> list[dict]:
    return rows("SELECT * FROM pre_auction_bets WHERE bet_type = 'SURPRISE'")

# ── Silent Bids CRUD ─────────────────────────────────────────────────────────

def submit_silent_bid(player_id: str, captain_name: str, bid_amount: int) -> None:
    now = utc_now()
    execute(
        "INSERT INTO silent_bids (player_id, captain_name, bid_amount, submitted_at) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(player_id, captain_name) DO UPDATE SET bid_amount = EXCLUDED.bid_amount, submitted_at = EXCLUDED.submitted_at",
        (player_id, captain_name, bid_amount, now)
    )

def get_silent_bids(player_id: str) -> list[dict]:
    return rows("SELECT * FROM silent_bids WHERE player_id = ? ORDER BY bid_amount DESC", (player_id,))

def clear_silent_bids(player_id: str) -> None:
    execute("DELETE FROM silent_bids WHERE player_id = ?", (player_id,))

# ── Live Bidding State CRUD ──────────────────────────────────────────────────

def get_live_bid_state() -> Optional[dict]:
    # Check if table has rows, if not return None
    row = one("SELECT * FROM live_bid_state LIMIT 1")
    return row

def update_live_bid_state(
    player_id: str,
    current_bid: int,
    current_bidder: Optional[str],
    phase: str,
    rtm_captain: Optional[str] = None,
    revised_bid: Optional[int] = None,
    last_bid_joker_captain: Optional[str] = None,
    bid_count: int = 0
) -> None:
    now = utc_now()
    # Since live_bid_state is a single-row state representation, we clear it and insert or update
    execute("DELETE FROM live_bid_state")
    execute(
        """
        INSERT INTO live_bid_state (
            player_id, current_bid, current_bidder, bid_count, phase, 
            rtm_captain, revised_bid, last_bid_joker_captain, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (player_id, current_bid, current_bidder, bid_count, phase, rtm_captain, revised_bid, last_bid_joker_captain, now)
    )

def clear_live_bid_state() -> None:
    execute("DELETE FROM live_bid_state")

def get_global_status() -> str:
    """Returns the current overall auction status (PRE_AUCTION, LIVE_AUCTION, COMPLETED)."""
    with connect() as con:
        return get_state(con, "auction_status", "PRE_AUCTION")

def set_global_status(status: str) -> None:
    with connect() as con:
        set_state(con, "auction_status", status)
        con.commit()

# ── Audit Log & History ──────────────────────────────────────────────────────

def log_action(action: str, player_id: Optional[str] = None, team_name: Optional[str] = None, amount: Optional[int] = None, note: Optional[str] = None) -> None:
    now = utc_now()
    execute(
        "INSERT INTO audit_log (action, player_id, team_name, amount, note, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (action, player_id, team_name, amount, note, now)
    )

def get_audit_logs() -> list[dict]:
    return rows("SELECT * FROM audit_log ORDER BY id DESC")

def get_all_captains() -> list[str]:
    rows_data = rows(
        "SELECT captain_name FROM teams ORDER BY captain_name"
    )
    return [r["captain_name"] for r in rows_data]

def get_team_names():
    return [
        t["name"]
        for t in get_all_teams()
    ]

def is_captain_player(player_name):

    if not player_name:
        return False

    name_lower = player_name.lower()

    for team in get_all_teams():

        captain = team["captain_name"]

        if captain.lower() in name_lower:
            return True

    return False

def any_captain_has_rtm_plus() -> bool:
    """Checks if at least one team still has an RTM+ card available."""
    res = rows("SELECT COUNT(*) as cnt FROM teams WHERE rtm_plus = 'AVAILABLE'")
    return res[0]["cnt"] > 0 if res else False