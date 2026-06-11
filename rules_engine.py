from altair import datasets
from typing import Any, Optional, Tuple
from config import BID_INCREMENTS, TIER_COSTS, BONUS_FLOOR, TAX_FLOOR, CAPTAINS
import models

def get_min_increment(current_bid: int) -> int:
    """Calculates the minimum increment required based on the current bid value.
    ₹0 – ₹1 Crore -> +₹10 Lakhs
    Above ₹1 Crore – ₹3 Crore -> +₹25 Lakhs
    Above ₹3 Crore – ₹6 Crore -> +₹50 Lakhs
    Above ₹6 Crore -> +₹1 Crore
    """
    for limit, increment in BID_INCREMENTS:
        if current_bid < limit:
            return increment
    return 1_00_00_000  # Fallback just in case

def calculate_max_bid(team_name: str, active_player_id: str, squad_target: int) -> int:
    """Calculates the maximum allowed bid for a team, enforcing the purse safety engine.
    Formula: Maximum Allowed Bid = Current Purse - Reserve Required
    """
    team = models.get_team(team_name)
    if not team:
        return 0
        
    current_purse = team["purse_remaining"]
    
    # Roster size includes the captain + players purchased
    # Count how many players have been sold to this team
    sold_players = models.rows("SELECT id FROM players WHERE sold_team = ?", (team_name,))
    current_squad_size = 1 + len(sold_players)  # 1 (Captain) + sold buys
    
    players_still_required = squad_target - current_squad_size
    
    # Slots needed *after* the active player is successfully purchased
    slots_after_purchase = players_still_required - 1
    
    if slots_after_purchase <= 0:
        # No more players required or this is the final slot, entire purse is liquid
        return current_purse

    # Base reserve required calculated as 0.5 Cr (50 Lakhs) per remaining slot
    reserve_required = slots_after_purchase * 50_00_000
        
    max_bid = current_purse - reserve_required
    return max(0, max_bid)

def check_surprise_bonus(team_name: str, player_id: str, base_price:int, sold_price: int) -> int:
    """Checks if the sold player matches the buyer's surprise player.
    If true, returns the bonus credit amount: Max(10% of sold price, ₹25 Lakhs).
    Otherwise returns 0.
    """
    team = models.get_team(team_name)
    if not team:
        return 0

    captain_name = team["captain_name"]
    surprise_player = models.get_surprise_player(captain_name)

    if surprise_player != player_id:
        return 0
    # Bonus is MIN(Sold Price - Base Price, Base Price)
    amount_above_base = sold_price - base_price
    if amount_above_base <= 0:
        return 0
    return int(min(amount_above_base, base_price))

def check_prediction_taxes(buyer_team_name: str, player_id: str, squad_target:int,base_price:int, sold_price: int) -> list[dict]:
    """Checks if the sold player triggers any prediction tax penalty.
    A prediction tax is assessed when a captain correctly predicted that the buying captain
    would purchase the player.
    The buying captain (buyer_team_name) is penalized: Max(10% of sold price, ₹25 Lakhs).
    Returns a list of prediction records that came true, along with the tax penalty amount.
    """
    buyer_team = models.get_team(buyer_team_name)
    if not buyer_team:
        return []
        
    buyer_captain = buyer_team["captain_name"]
    
    all_preds = models.rows(
        "SELECT captain_name FROM pre_auction_bets WHERE bet_type = 'PREDICTION' AND target_captain = ? AND target_player_id = ?",
        (buyer_captain, player_id)
    )
    
    triggered_predictions = []
    # Penalty is MIN(Sold Price - Base Price, Base Price)
    amount_above_base = sold_price - base_price
    if amount_above_base <= 0:
        tax_penalty = 0
    else:
        tax_penalty = int(min(amount_above_base, base_price))
    
    for pred in all_preds:
        predictor_captain = pred["captain_name"]
        triggered_predictions.append({
            "predictor_captain": predictor_captain,
            "buying_captain": buyer_captain,
            "tax_amount": tax_penalty
        })
        
    return triggered_predictions

def resolve_last_bid_joker(player_id: str) -> Optional[dict]:
    """Evaluates the silent bids submitted for a player when the Last Bid Joker is active.
    Determines the winning bidder and price.
    Tie Rule: If a tie occurs and one of the tied captains is the original owner
    of the active Last Bid Joker, they win the tie-breaker.
    Returns: dict with 'winning_team', 'winning_price', and 'note'.
    """
    bids = models.get_silent_bids(player_id)
    if not bids:
        return None
        
    max_bid = max(b["bid_amount"] for b in bids)
    highest_bids = [b for b in bids if b["bid_amount"] == max_bid]
    
    state = models.get_live_bid_state()
    joker_holder = state["last_bid_joker_captain"] if state else None
    
    winner_bid = None
    note = ""
    
    if len(highest_bids) == 1:
        winner_bid = highest_bids[0]
        note = f"Silent bid revealed. {winner_bid['captain_name']} won with a bid of {winner_bid['bid_amount']}."
    else:
        tied_captains = [b["captain_name"] for b in highest_bids]
        if joker_holder and joker_holder in tied_captains:
            winner_bid = next(b for b in highest_bids if b["captain_name"] == joker_holder)
            note = f"Tie detected at {max_bid}. Joker owner {joker_holder} wins tie-breaker."
        else:
            highest_bids_sorted = sorted(highest_bids, key=lambda x: x["submitted_at"])
            winner_bid = highest_bids_sorted[0]
            note = f"Tie detected at {max_bid}. Tie-broken by earliest submission: {winner_bid['captain_name']}."
            
    team = models.get_team_by_captain(winner_bid["captain_name"])
    winning_team_name = team["name"] if team else None
    
    return {
        "winning_captain": winner_bid["captain_name"],
        "winning_team": winning_team_name,
        "winning_price": winner_bid["bid_amount"],
        "note": note
    }