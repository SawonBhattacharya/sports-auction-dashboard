import os

# Initial Purse: ₹25 Crore in raw INR
INITIAL_PURSE = 25_00_00_000

# Captain mappings
CAPTAINS = {
    "Sawon": "Team Delta",
    "Dragleeoo": "Team Alpha",
    "Swapneel": "Team Charlie",
    "Aman Jaiswal": "Team Bravo",
}

def get_passcodes() -> dict:
    """Read passcodes from st.secrets with fallback defaults."""
    try:
        import streamlit as st
        codes = dict(st.secrets.get("passcodes", {}))
        if codes:
            return codes
    except Exception:
        pass
    # Fallback for testing/CLI
    return {
        "admin": "admin123",
        "viewer": "viewer123",
        "Sawon": "sawon123",
        "Dragleeoo": "drag123",
        "Swapneel": "swap123",
        "Aman Jaiswal": "aman123",
    }

PASSCODES = get_passcodes()

# Seeding price tiers (in INR)
TIER_COSTS = {
    "Icon": 2_00_00_000,      # ₹2.0 Crore
    "Premium": 1_00_00_000,   # ₹1.0 Crore
    "Rising": 50_00_000,      # ₹50 Lakh
    "Impact": 20_00_00_00,     # ₹20 Lakh (2,000,000)
}

# Note: The typo in TIER_COSTS above for Impact: 20_00_00_00 is 2 Crore, it should be 20_00_000 (20 Lakh). Let's fix that.
TIER_COSTS["Impact"] = 20_00_000

# Marquee player base price
MARQUEE_BASE_PRICE = 4_50_00_000  # ₹4.5 Crore

# Bidding increment rules
# Range (ceiling_exclusive, minimum_increment)
BID_INCREMENTS = [
    (1_00_00_000, 10_00_000),      # ₹0 – ₹1 Crore -> +₹10 Lakhs
    (3_00_00_000, 25_00_000),      # ₹1 Crore – ₹3 Crore -> +₹25 Lakhs
    (6_00_00_000, 50_00_000),      # ₹3 Crore – ₹6 Crore -> +₹50 Lakhs
    (float('inf'), 1_00_00_000),   # Above ₹6 Crore -> +₹1 Crore
]

# Bonus and Tax limits
BONUS_FLOOR = 25_00_000  # ₹25 Lakh minimum for surprise player bonus
TAX_FLOOR = 25_00_000    # ₹25 Lakh minimum for prediction tax

def format_inr(amount: int) -> str:
    """Formats raw INR amount (integer) to Lakhs/Crores display.
    Example: 250000000 -> "25.0 Cr"
    Example: 5000000 -> "50 Lakh"
    """
    if amount is None:
        return "₹0"
    
    # Check if we should render in Crores
    if amount >= 1_00_00_000:
        cr = amount / 1_00_00_000
        # Format to 1 decimal place if it has a fraction, else whole number
        if cr == int(cr):
            return f"₹{int(cr)} Cr"
        else:
            return f"₹{cr:.2f} Cr".rstrip('0').rstrip('.')
            
    # Lakhs
    lakh = amount / 1_00_000
    if lakh == int(lakh):
        return f"₹{int(lakh)} Lakh"
    else:
        return f"₹{lakh:.2f} Lakh".rstrip('0').rstrip('.')

def is_captain_player(player_name: str) -> bool:
    """Returns True if the player_name matches or contains any captain name."""
    if not player_name:
        return False
    name_lower = player_name.lower()
    for cap in CAPTAINS.keys():
        if cap.lower() in name_lower:
            return True
    return False
