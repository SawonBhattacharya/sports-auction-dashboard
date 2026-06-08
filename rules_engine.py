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
    
    # Slots needed *after* the active player is purchased
    slots_after_purchase = players_still_required - 1
    
    if slots_after_purchase <= 0:
        # No more players required or this is the last player, no reserve needed
        return current_purse

    # Get all unauctioned (AVAILABLE) players excluding the active player
    available_players = models.rows(
        "SELECT seeding FROM players WHERE status = 'AVAILABLE' AND id != ?",
        (active_player_id,)
    )
    
    # Count seedings in available pool
    seeding_counts = {"Impact": 0, "Rising": 0, "Premium": 0, "Icon": 0}
    for p in available_players:
        s = p["seeding"]
        if s in seeding_counts:
            seeding_counts[s] += 1
            
    # Calculate reserve required by filling slots_after_purchase using cheapest tiers first
    reserve_required = 0
    slots_to_fill = slots_after_purchase
    
    # 1. Fill with Impact (₹20 Lakh)
    impact_used = min(slots_to_fill, seeding_counts["Impact"])
    reserve_required += impact_used * TIER_COSTS["Impact"]
    slots_to_fill -= impact_used
    
    # 2. Fill with Rising (₹50 Lakh)
    if slots_to_fill > 0:
        rising_used = min(slots_to_fill, seeding_counts["Rising"])
        reserve_required += rising_used * TIER_COSTS["Rising"]
        slots_to_fill -= rising_used
        
    # 3. Fill with Premium (₹1 Crore)
    if slots_to_fill > 0:
        premium_used = min(slots_to_fill, seeding_counts["Premium"])
        reserve_required += premium_used * TIER_COSTS["Premium"]
        slots_to_fill -= premium_used
        
    # 4. Fill with Icon (₹2 Crore)
    if slots_to_fill > 0:
        icon_used = min(slots_to_fill, seeding_counts["Icon"])
        reserve_required += icon_used * TIER_COSTS["Icon"]
        slots_to_fill -= icon_used
        
    # 5. If we still have slots to fill (e.g. pool is depleted), fill with the average price or Icon price
    if slots_to_fill > 0:
        reserve_required += slots_to_fill * TIER_COSTS["Impact"]
        
    max_bid = current_purse - reserve_required
    return max(0, max_bid)

def check_surprise_bonus(team_name: str,
    player_id: str,
    sold_price: int) -> int:
    """Checks if the sold player matches the buyer's surprise player.
    If true, returns the bonus credit amount: Max(10% of sold price, ₹25 Lakhs).
    Otherwise returns 0.
    """
    from config import BONUS_FLOOR
    import models

    team = models.get_team(team_name)

    if not team:
        return 0

    captain_name = team["captain_name"]

    surprise_player = models.get_surprise_player(
        captain_name
    )

    if surprise_player != player_id:
        return 0

    return max(
        BONUS_FLOOR,
        int(sold_price * 0.10)
    )

def check_prediction_taxes(buyer_team_name: str, player_id: str, sold_price: int) -> list[dict]:
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
    
    # Find all predictions in pre_auction_bets where target_captain = buyer_captain AND target_player_id = player_id
    all_preds = models.rows(
        "SELECT captain_name FROM pre_auction_bets WHERE bet_type = 'PREDICTION' AND target_captain = ? AND target_player_id = ?",
        (buyer_captain, player_id)
    )
    
    triggered_predictions = []
    tax_penalty = max(int(0.10 * sold_price), TAX_FLOOR)
    
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
        
    # Find the maximum bid amount
    max_bid = max(b["bid_amount"] for b in bids)
    highest_bids = [b for b in bids if b["bid_amount"] == max_bid]
    
    # Get the active Last Bid Joker holder (who activated the joker for this player)
    # The active state tells us who has the Last Bid Joker active
    state = models.get_live_bid_state()
    joker_holder = state["last_bid_joker_captain"] if state else None
    
    winner_bid = None
    note = ""
    
    if len(highest_bids) == 1:
        winner_bid = highest_bids[0]
        note = f"Silent bid revealed. {winner_bid['captain_name']} won with a bid of {winner_bid['bid_amount']}."
    else:
        # Tie breaker! Check if one of the tied captains is the joker_holder
        tied_captains = [b["captain_name"] for b in highest_bids]
        if joker_holder and joker_holder in tied_captains:
            winner_bid = next(b for b in highest_bids if b["captain_name"] == joker_holder)
            note = f"Tie detected at {max_bid}. Joker owner {joker_holder} wins tie-breaker."
        else:
            # If joker owner is not in the tie, default to the one who submitted earliest
            # (or first in alphabetical order of captain name for simplicity)
            highest_bids_sorted = sorted(highest_bids, key=lambda x: x["submitted_at"])
            winner_bid = highest_bids_sorted[0]
            note = f"Tie detected at {max_bid}. Tie-broken by earliest submission: {winner_bid['captain_name']}."
            
    # Find winning team
    team = models.get_team_by_captain(winner_bid["captain_name"])
    winning_team_name = team["name"] if team else None
    
    return {
        "winning_captain": winner_bid["captain_name"],
        "winning_team": winning_team_name,
        "winning_price": winner_bid["bid_amount"],
        "note": note
    }
