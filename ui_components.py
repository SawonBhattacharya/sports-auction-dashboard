import streamlit as st
import streamlit.components.v1 as components
import json
import base64
import textwrap
from html import escape
from pathlib import Path
from typing import Optional
from config import format_inr, CAPTAINS
import models

IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".PNG", ".JPG", ".JPEG", ".WEBP")

def image_file_to_data_uri(path: str | Path) -> Optional[str]:
    """Return a local image as a data URI so it renders reliably inside markdown HTML."""
    img_path = Path(path)
    if not img_path.exists() or not img_path.is_file():
        return None

    ext = img_path.suffix.lower().lstrip(".")
    if ext == "jpg":
        ext = "jpeg"
    try:
        encoded_img = base64.b64encode(img_path.read_bytes()).decode("utf-8")
    except OSError:
        return None
    return f"data:image/{ext};base64,{encoded_img}"

def _normalize_asset_name(value: str) -> str:
    return "".join(ch.lower() for ch in value if ch.isalnum())

def find_team_logo(team: dict) -> Optional[str]:
    """Resolve a team's logo from DB value, known asset names, and local logo folder."""
    logo_url = (team.get("logo_url") or "").strip()
    if logo_url:
        if logo_url.startswith(("http://", "https://", "data:image/")):
            return logo_url
        local_logo = image_file_to_data_uri(logo_url)
        if local_logo:
            return local_logo

    logo_dir = Path("images/team_logo")
    candidates = [team.get("captain_name", ""), team.get("name", "")]
    for raw_name in candidates:
        if not raw_name:
            continue
        for ext in IMAGE_EXTENSIONS:
            local_logo = image_file_to_data_uri(logo_dir / f"{raw_name}{ext}")
            if local_logo:
                return local_logo

    if logo_dir.exists():
        target_names = {_normalize_asset_name(name) for name in candidates if name}
        try:
            for file_path in logo_dir.iterdir():
                if file_path.is_file() and file_path.suffix in IMAGE_EXTENSIONS:
                    if _normalize_asset_name(file_path.stem) in target_names:
                        return image_file_to_data_uri(file_path)
        except OSError:
            pass

    captain = team.get("captain_name", "")
    return "https://ui-avatars.com/api/?name=" + captain.replace(" ", "+") + "&background=1f2937&color=38bdf8"

def inject_css() -> None:
    """Injects a premium, modern glassmorphic CSS styling system for the dashboard."""
    css = """
    <style>
    /* Overall Theme and Background */
    .stApp {
        background: radial-gradient(circle at top right, rgba(34, 197, 94, 0.08), transparent 45rem),
                    linear-gradient(135deg, #070e1b 0%, #0c1220 50%, #050a14 100%);
        color: #e5e7eb;
        font-family: 'Outfit', 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    }
    
    /* Hide default Streamlit decoration and footer */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    
    /* Glassmorphism Panel Cards */
    .glass-card {
        background: rgba(17, 24, 39, 0.65);
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 12px;
        padding: 18px;
        box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.37);
        backdrop-filter: blur(8px);
        -webkit-backdrop-filter: blur(8px);
        margin-bottom: 15px;
        transition: transform 0.2s ease, border-color 0.2s ease;
    }
    .glass-card:hover {
        border-color: rgba(34, 197, 94, 0.3);
    }
    
    /* Metrics block override */
    [data-testid="stMetric"] {
        background: rgba(17, 24, 39, 0.7);
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 10px;
        padding: 12px;
        box-shadow: 0 4px 15px rgba(0, 0, 0, 0.2);
    }
    [data-testid="stMetricValue"] {
        font-weight: 700;
        color: #ffffff;
    }
    [data-testid="stMetricLabel"] {
        color: #9ca3af;
        font-size: 0.85rem;
    }
    
    /* Captain Thumbnails Cover Grid */
    .captain-grid {
        display: grid;
        grid-template-columns: repeat(4, 1fr);
        gap: 15px;
        margin-bottom: 25px;
    }
    .captain-card {
        background: rgba(17, 24, 39, 0.65);
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 12px;
        padding: 12px;
        display: flex;
        align-items: center;
        gap: 15px;
        box-shadow: 0 4px 20px rgba(0,0,0,0.25);
    }
    .captain-card.active-turn {
        border-color: #22c55e;
        box-shadow: 0 0 15px rgba(34, 197, 94, 0.3);
    }
    .captain-avatar {
        width: 50px;
        height: 50px;
        border-radius: 50px;
        background: #1f2937;
        display: flex;
        align-items: center;
        justify-content: center;
        border: 2px solid rgba(255, 255, 255, 0.1);
        font-weight: bold;
        color: #38bdf8;
        font-size: 1.2rem;
        overflow: hidden;
        flex-shrink: 0;
    }
    .captain-avatar img {
        width: 100%;
        height: 100%;
        object-fit: cover;
        display: block;
    }
    .captain-info {
        flex-grow: 1;
    }
    .captain-name {
        font-weight: 600;
        font-size: 0.95rem;
        color: #f3f4f6;
        margin: 0;
    }
    .captain-team {
        font-size: 0.75rem;
        color: #9ca3af;
        margin: 0;
    }
    .captain-purse {
        font-weight: bold;
        font-size: 1rem;
        color: #22c55e;
        margin: 0;
    }
    .captain-spots {
        font-size: 0.75rem;
        color: #38bdf8;
        margin: 0;
    }
    
    /* Copyright Footer Style */
    .lcl-footer {
        position: fixed;
        left: 0;
        bottom: 0;
        width: 100%;
        background: rgba(10, 15, 30, 0.85);
        border-top: 1px solid rgba(255, 255, 255, 0.08);
        color: #9ca3af;
        text-align: center;
        padding: 8px 0;
        font-size: 0.8rem;
        z-index: 9999;
        backdrop-filter: blur(10px);
        letter-spacing: 0.5px;
    }
    
    /* Button Custom styling */
    .stButton > button {
        background: rgba(31, 41, 55, 0.7);
        border: 1px solid rgba(255, 255, 255, 0.1);
        color: #f3f4f6;
        font-weight: 500;
        transition: all 0.2s ease;
    }
    .stButton > button:hover {
        background: #22c55e;
        color: #000;
        border-color: #22c55e;
        box-shadow: 0 0 10px rgba(34, 197, 94, 0.3);
    }
    
    /* Dynamic table tags */
    .tag {
        background: rgba(56, 189, 248, 0.15);
        color: #38bdf8;
        border-radius: 4px;
        padding: 2px 6px;
        font-size: 0.75rem;
        font-weight: 600;
    }
    .tag-sold {
        background: rgba(34, 197, 94, 0.15);
        color: #22c55e;
    }
    .tag-unsold {
        background: rgba(249, 115, 22, 0.15);
        color: #f97316;
    }
    .squad-rows {
        display: flex;
        flex-direction: column;
        gap: 12px;
        margin-top: 12px;
    }
    .squad-row {
        background: rgba(15, 23, 42, 0.7);
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 8px;
        padding: 12px;
    }
    .squad-row-head {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 10px;
        margin-bottom: 10px;
    }
    .squad-title {
        color: #f8fafc;
        font-size: 1rem;
        font-weight: 800;
        margin: 0;
    }
    .squad-meta {
        color: #9ca3af;
        font-size: 0.78rem;
        text-align: right;
    }
    .squad-slots {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(58px, 1fr));
        gap: 9px;
    }
    .squad-slot {
        min-width: 0;
        text-align: center;
    }
    .squad-avatar {
        width: 52px;
        height: 52px;
        border-radius: 999px;
        margin: 0 auto 5px;
        background: rgba(31, 41, 55, 0.78);
        border: 2px solid rgba(148, 163, 184, 0.2);
        display: flex;
        align-items: center;
        justify-content: center;
        overflow: hidden;
        color: #64748b;
        font-size: 1.3rem;
        font-weight: 800;
    }
    .squad-avatar img {
        width: 100%;
        height: 100%;
        object-fit: cover;
        display: block;
    }
    .squad-avatar.captain {
        border-color: #38bdf8;
        box-shadow: 0 0 14px rgba(56, 189, 248, 0.25);
    }
    .squad-avatar.marquee {
        border-color: #f59e0b;
        box-shadow: 0 0 14px rgba(245, 158, 11, 0.24);
    }
    .squad-label {
        color: #cbd5e1;
        font-size: 0.68rem;
        line-height: 1.15;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }
    .squad-price {
        color: #22c55e;
        font-size: 0.62rem;
        font-weight: 800;
    }
    @media (max-width: 720px) {
        .captain-grid {
            grid-template-columns: repeat(2, 1fr);
        }
        .squad-row-head {
            align-items: flex-start;
            flex-direction: column;
        }
        .squad-meta {
            text-align: left;
        }
        .squad-slots {
            grid-template-columns: repeat(5, minmax(48px, 1fr));
            gap: 8px;
        }
        .squad-avatar {
            width: 46px;
            height: 46px;
        }
    }
    @keyframes saleToastIn {
        0% { transform: translate(-50%, -18px) scale(0.94); opacity: 0; }
        14% { transform: translate(-50%, 0) scale(1); opacity: 1; }
        82% { transform: translate(-50%, 0) scale(1); opacity: 1; }
        100% { transform: translate(-50%, -10px) scale(0.98); opacity: 0; }
    }
    @keyframes confettiDrop {
        0% { transform: translateY(-20px) rotate(0deg); opacity: 0; }
        15% { opacity: 1; }
        100% { transform: translateY(150px) rotate(220deg); opacity: 0; }
    }
    </style>
    """
    st.html(css)

def render_header(title: str, active_captain_turn: str = None) -> None:
    """Renders the top panel and 4 Captain thumbnails displaying current stats."""
    inject_css()
    
    # 1. Main Header Title
    st.html(
        f"""
        <div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid rgba(255,255,255,0.08); padding-bottom: 10px; margin-bottom: 20px;">
            <div style="font-size: 1.6rem; font-weight: 700; color: #ffffff; letter-spacing: 0.5px;">🏆 LCL AUCTION 2026</div>
            <div style="font-size: 1.1rem; color: #9ca3af; font-weight: 500;">{title}</div>
        </div>
        """
    )
    
    # 2. Captain Cover Summaries
    teams = models.get_all_teams()
    
    # Map teams by captain
    team_map = {t["captain_name"]: t for t in teams}
    
    # Render 4 Captain summaries in columns
    cols = st.columns(4)
    for i, name in enumerate(["Sawon", "Dragleeoo", "Swapneel", "Harshit Agarwal"]):
        t = team_map.get(name)
        if not t:
            continue
            
        purse = format_inr(t["purse_remaining"])
        
        # Get count of players sold to this team
        sold_players = models.rows("SELECT id FROM players WHERE sold_team = ?", (t["name"],))
        squad_size = 1 + len(sold_players)  # 1 (Captain) + sold buys
        max_size = t["max_squad_size"]
        
        is_active = (active_captain_turn == name)
        active_class = "active-turn" if is_active else ""
        turn_indicator = "⚡ YOUR TURN" if is_active else ""
        
        initials = "".join([part[0] for part in name.split()]).upper()
        logo_src = find_team_logo(t)
        avatar_html = f'<img src="{escape(logo_src, quote=True)}" alt="{escape(t["name"], quote=True)} logo">' if logo_src else initials
        
        cols[i].html(
            f"""
            <div class="captain-card {active_class}">
                <div class="captain-avatar">{avatar_html}</div>
                <div class="captain-info">
                    <p class="captain-name">{escape(name)} <span style="font-size:0.7rem; color:#22c55e;">{turn_indicator}</span></p>
                    <p class="captain-team">{escape(t["name"])}</p>
                    <p class="captain-purse">{purse}</p>
                    <p class="captain-spots">Roster: <b>{squad_size} / {max_size}</b></p>
                </div>
            </div>
            """
        )

def render_footer() -> None:
    """Renders the fixed professional copyright footer at the bottom of the viewport."""
    st.html(
        """
        <div class="lcl-footer">
            © 2026 Sawon & Ujjawal · All rights reserved · Built with ❤️ for LCL 2026
        </div>
        """
    )

def render_spin_wheel(player_names: list[str], target_player: str, target_player_id: str = "", key: str = "wheel", auto_spin: bool = True) -> bool:
    """Renders an interactive and modern canvas-based Spin Wheel.
    The wheel cosmetically spins and lands on the pre-determined target_player.
    """
    if not player_names or not target_player:
        st.info("No players available to spin.")
        return False
        
    # Ensure target_player is in the list
    if target_player not in player_names:
        player_names = player_names + [target_player]
        
    names_json = json.dumps(player_names)
    target_index = player_names.index(target_player)
    auto_spin_js = "true" if auto_spin else "false"
    
    html_code = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{
                background: transparent;
                margin: 0;
                padding: 0;
                display: flex;
                flex-direction: column;
                align-items: center;
                justify-content: center;
                font-family: sans-serif;
                color: #fff;
                overflow: hidden;
            }}
            #wheel-container {{
                position: relative;
                width: 320px;
                height: 320px;
            }}
            #wheelCanvas {{
                border-radius: 50%;
                border: 4px solid rgba(255, 255, 255, 0.15);
                box-shadow: 0 10px 30px rgba(0, 0, 0, 0.5);
            }}
            #pointer {{
                position: absolute;
                top: -5px;
                left: 50%;
                transform: translateX(-50%);
                width: 0;
                height: 0;
                border-left: 15px solid transparent;
                border-right: 15px solid transparent;
                border-top: 25px solid #22c55e;
                z-index: 10;
                filter: drop-shadow(0px 3px 5px rgba(0,0,0,0.5));
            }}
            #result {{
                margin-top: 15px;
                font-weight: bold;
                font-size: 1.2rem;
                color: #38bdf8;
                min-height: 25px;
                text-shadow: 0 2px 4px rgba(0,0,0,0.3);
            }}
        </style>
    </head>
    <body>
        <div id="wheel-container">
            <div id="pointer"></div>
            <canvas id="wheelCanvas" width="320" height="320"></canvas>
        </div>
        <div id="result"></div>

        <script>
            const canvas = document.getElementById('wheelCanvas');
            const ctx = canvas.getContext('2d');
            const resultDiv = document.getElementById('result');
            
            const players = {names_json};
            const targetIdx = {target_index};
            const totalSegments = players.length;
            const colors = [
                '#1e293b', '#0f172a', '#312e81', '#1e1b4b',
                '#065f46', '#022c22', '#854d0e', '#422006'
            ];

            let startAngle = 0;
            const arc = Math.PI / (totalSegments / 2);
            let spinTimeout = null;
            let spinTime = 0;
            const spinTimeTotal = 3500; // 3.5 seconds
            
            const pointerAngle = 3 * Math.PI / 2;
            const targetArcCenter = targetIdx * arc + arc / 2;
            let finalAngle = pointerAngle - targetArcCenter;
            while (finalAngle < 0) finalAngle += 2 * Math.PI;
            
            const extraSpins = 5 * 2 * Math.PI;
            const totalRotation = finalAngle + extraSpins;
            
            function drawWheel() {{
                ctx.clearRect(0, 0, 320, 320);
                const rx = 160;
                const ry = 160;
                const r = 150;
                
                // Draw sections
                for (let i = 0; i < totalSegments; i++) {{
                    const angle = startAngle + i * arc;
                    ctx.fillStyle = colors[i % colors.length];
                    
                    ctx.beginPath();
                    ctx.arc(rx, ry, r, angle, angle + arc, false);
                    ctx.lineTo(rx, ry);
                    ctx.fill();
                    
                    // Add text
                    ctx.save();
                    ctx.fillStyle = "#e5e7eb";
                    ctx.translate(rx + Math.cos(angle + arc / 2) * (r * 0.65), 
                                  ry + Math.sin(angle + arc / 2) * (r * 0.65));
                    ctx.rotate(angle + arc / 2 + Math.PI / 2);
                    
                    const name = players[i];
                    ctx.font = 'bold 9px sans-serif';
                    ctx.textAlign = "center";
                    ctx.fillText(name.substring(0, 12), 0, 0);
                    ctx.restore();
                }}
                
                // Draw inner circle
                ctx.beginPath();
                ctx.arc(rx, ry, 30, 0, Math.PI * 2, false);
                ctx.fillStyle = "#0c1220";
                ctx.strokeStyle = "rgba(255,255,255,0.1)";
                ctx.lineWidth = 3;
                ctx.fill();
                ctx.stroke();
            }}

            function easeOut(t, b, c, d) {{
                const ts = (t /= d) * t;
                const tc = ts * t;
                return b + c * (tc + -3 * ts + 3 * t);
            }}

            function rotateWheel() {{
                spinTime += 30;
                if (spinTime >= spinTimeTotal) {{
                    stopRotateWheel();
                    return;
                }}
                startAngle = easeOut(spinTime, 0, totalRotation, spinTimeTotal);
                drawWheel();
                spinTimeout = setTimeout(rotateWheel, 30);
            }}

            function stopRotateWheel() {{
                clearTimeout(spinTimeout);
                startAngle = totalRotation;
                drawWheel();
                resultDiv.innerHTML = "🎯 Landed on: " + players[targetIdx];
            }}

            // Auto-run logic with localStorage sync
            const autoSpin = {auto_spin_js};
            const targetPlayerId = "{target_player_id}";
            
            if (autoSpin && targetPlayerId) {{
                const storageKey = 'lcl_spin_start_' + targetPlayerId;
                let spinStart = localStorage.getItem(storageKey);
                const now = Date.now();
                
                if (!spinStart) {{
                    spinStart = now.toString();
                    localStorage.setItem(storageKey, spinStart);
                }}
                
                const elapsed = now - parseInt(spinStart);
                if (elapsed >= spinTimeTotal) {{
                    stopRotateWheel();
                }} else {{
                    spinTime = elapsed;
                    resultDiv.innerHTML = "🌀 Spinning...";
                    rotateWheel();
                }}
            }} else {{
                drawWheel();
                resultDiv.innerHTML = "🎡 Ready to Spin";
            }}
        </script>
    </body>
    </html>
    """
    components.html(html_code, height=380)
    return True

def find_player_photo(player_name: str) -> Optional[str]:
    """Search for a player's photo under images/player_photo/ by trying different extensions
    and checking case-insensitively.
    """
    photo_dir = Path("images/player_photo")
    if not photo_dir.exists():
        return None
        
    target_name = player_name.strip().lower()
    
    # 1. Exact match with popular extensions
    for ext in [".jpg", ".jpeg", ".png", ".JPG", ".JPEG", ".PNG"]:
        path = photo_dir / f"{player_name}{ext}"
        if path.exists():
            return str(path)
            
    # 2. Case-insensitive directory scan, allowing captain short names to match full-name files.
    try:
        for f in photo_dir.iterdir():
            file_stem = f.stem.strip().lower()
            if f.is_file() and (file_stem == target_name or target_name in file_stem or file_stem in target_name):
                return str(f)
    except Exception:
        pass
        
    return None

def find_player_thumbnail(player_name: str) -> Optional[str]:
    """Search for the small roster thumbnail generated from the player photo."""
    thumb_dir = Path("images/player_thumb")
    if not thumb_dir.exists():
        return None

    target_name = player_name.strip().lower()
    for ext in [".jpg", ".jpeg", ".png", ".JPG", ".JPEG", ".PNG"]:
        path = thumb_dir / f"{player_name}{ext}"
        if path.exists():
            return str(path)

    try:
        for f in thumb_dir.iterdir():
            if not f.is_file() or f.suffix not in IMAGE_EXTENSIONS:
                continue
            file_stem = f.stem.strip().lower()
            if file_stem == target_name or target_name in file_stem or file_stem in target_name:
                return str(f)
    except Exception:
        pass

    return None

def render_player_card(player_data: dict) -> None:
    """Renders a visually appealing card to show the player currently on the block."""
    player_name = player_data.get("name", "Unknown")
    category = player_data.get("seeding", "Unknown")
    base_price = player_data.get("base_price", 0)
    base_price_fmt = format_inr(base_price)
    
    matches = player_data.get("matches") or "-"
    runs = player_data.get("runs") or "-"
    wickets = player_data.get("wickets") or "-"
    strike_rate = player_data.get("strike_rate") or "-"
    economy = player_data.get("economy") or "-"
    average = player_data.get("average") or "-"
    batting = player_data.get("batting") or "-"
    bowling = player_data.get("bowling") or "-"
    bowling_preference = player_data.get("bowling_preference") or "-"
    
    photo_path = find_player_photo(player_name)
    if photo_path:
        img_src = image_file_to_data_uri(photo_path)
    else:
        img_src = "https://ui-avatars.com/api/?name=" + player_name.replace(" ", "+") + "&background=1f2937&color=38bdf8&size=200"

    html = f"""
    <div class="glass-card" style="display: flex; gap: 20px; align-items: stretch; margin-bottom: 20px;">
        <div style="flex-shrink: 0; width: 140px; display: flex; flex-direction: column; justify-content: center; align-items: center; background: rgba(0,0,0,0.2); border-radius: 8px; padding: 10px;">
            <img src="{escape(img_src or '', quote=True)}" style="width: 110px; height: 110px; border-radius: 50%; object-fit: cover; border: 3px solid #38bdf8; box-shadow: 0 0 15px rgba(56, 189, 248, 0.3);">
            <div style="margin-top: 10px; text-align: center;">
                <span class="tag">{escape(str(category))}</span>
            </div>
        </div>
        <div style="flex-grow: 1; display: flex; flex-direction: column; justify-content: space-between;">
            <div>
                <h2 style="margin: 0; font-size: 1.8rem; color: #f3f4f6; letter-spacing: 0.5px;">{escape(str(player_name))}</h2>
                <div style="margin-top: 5px; font-size: 1.1rem; color: #22c55e; font-weight: bold;">Base Price: {base_price_fmt}</div>
            </div>
            <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin-top: 15px;">
                <div style="background: rgba(255,255,255,0.05); padding: 8px; border-radius: 6px; text-align: center;">
                    <div style="font-size: 0.7rem; color: #9ca3af; font-weight: bold;">MATCHES</div>
                    <div style="font-size: 1.2rem; font-weight: bold; color: #fff;">{matches}</div>
                </div>
                <div style="background: rgba(255,255,255,0.05); padding: 8px; border-radius: 6px; text-align: center;">
                    <div style="font-size: 0.7rem; color: #9ca3af; font-weight: bold;">RUNS (AVG/SR)</div>
                    <div style="font-size: 1.1rem; font-weight: bold; color: #fff;">{runs} <span style="font-size: 0.8rem; color: #38bdf8;">({average}/{strike_rate})</span></div>
                </div>
                <div style="background: rgba(255,255,255,0.05); padding: 8px; border-radius: 6px; text-align: center;">
                    <div style="font-size: 0.7rem; color: #9ca3af; font-weight: bold;">WICKETS (ECO)</div>
                    <div style="font-size: 1.1rem; font-weight: bold; color: #fff;">{wickets} <span style="font-size: 0.8rem; color: #38bdf8;">({economy})</span></div>
                </div>
            </div>
            <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin-top: 10px;">
                <div style="background: rgba(56,189,248,0.08); padding: 8px; border-radius: 6px;">
                    <div style="font-size: 0.7rem; color: #9ca3af; font-weight: bold;">BATTING</div>
                    <div style="font-size: 0.92rem; font-weight: 700; color: #f3f4f6;">{escape(str(batting))}</div>
                </div>
                <div style="background: rgba(56,189,248,0.08); padding: 8px; border-radius: 6px;">
                    <div style="font-size: 0.7rem; color: #9ca3af; font-weight: bold;">BOWLING</div>
                    <div style="font-size: 0.92rem; font-weight: 700; color: #f3f4f6;">{escape(str(bowling))}</div>
                </div>
                <div style="background: rgba(56,189,248,0.08); padding: 8px; border-radius: 6px;">
                    <div style="font-size: 0.7rem; color: #9ca3af; font-weight: bold;">BOWLING PREF</div>
                    <div style="font-size: 0.92rem; font-weight: 700; color: #f3f4f6;">{escape(str(bowling_preference))}</div>
                </div>
            </div>
        </div>
    </div>
    """
    st.html(textwrap.dedent(html))

def render_team_rosters_table(db) -> None:
    """Render each team's current members with name, seed, and purchase price."""
    render_team_squad_rows(db)

def image_file_to_small_data_uri(path: str | Path, max_bytes: int = 80_000) -> Optional[str]:
    """Inline only reasonably small images to keep roster HTML compact."""
    img_path = Path(path)
    if not img_path.exists() or not img_path.is_file():
        return None
    try:
        if img_path.stat().st_size > max_bytes:
            return None
    except OSError:
        return None
    return image_file_to_data_uri(img_path)

def _player_img_html(player_name: str) -> str:
    photo_path = find_player_thumbnail(player_name) or find_player_photo(player_name)
    img_src = image_file_to_small_data_uri(photo_path) if photo_path else None
    if not img_src:
        img_src = "https://ui-avatars.com/api/?name=" + player_name.replace(" ", "+") + "&background=1f2937&color=38bdf8&size=160"
    return f'<img src="{escape(img_src, quote=True)}" alt="{escape(player_name, quote=True)}">'

def render_team_squad_rows(db) -> None:
    """Render teams as horizontal squad rows with captain, sold players, and empty slots."""
    if hasattr(db, 'get_all_teams'):
        teams = db.get_all_teams()
    else:
        teams = models.get_all_teams()

    if not teams:
        return

    rows_html = []
    for team in teams:
        team_name = team["name"]
        captain_name = team["captain_name"]
        if hasattr(db, 'rows'):
            players = db.rows(
                """
                SELECT name, seeding, sold_price, is_marquee
                FROM players
                WHERE sold_team = ?
                ORDER BY CASE WHEN is_marquee THEN 0 ELSE 1 END, sold_at, name
                """,
                (team_name,),
            )
        else:
            players = models.rows(
                """
                SELECT name, seeding, sold_price, is_marquee
                FROM players
                WHERE sold_team = ?
                ORDER BY CASE WHEN is_marquee THEN 0 ELSE 1 END, sold_at, name
                """,
                (team_name,),
            )

        max_size = int(team["max_squad_size"])
        filled_count = min(max_size, 1 + len(players))
        slot_html = [
            f"""
            <div class="squad-slot" title="{escape(captain_name, quote=True)}">
                <div class="squad-avatar captain">{_player_img_html(captain_name)}</div>
                <div class="squad-label">{escape(captain_name)}</div>
            </div>
            """
        ]

        for player in players[: max_size - 1]:
            role_class = "marquee" if player["is_marquee"] else ""
            detail = f"{player['name']} ({player['seeding']}, {format_inr(player['sold_price'])})"
            slot_html.append(
                f"""
                <div class="squad-slot" title="{escape(detail, quote=True)}">
                    <div class="squad-avatar {role_class}">{_player_img_html(player['name'])}</div>
                    <div class="squad-label">{escape(player['name'])}</div>
                    <div class="squad-price">{format_inr(player['sold_price'])}</div>
                </div>
                """
            )

        for idx in range(max(0, max_size - len(slot_html))):
            next_no = len(slot_html) + 1
            slot_html.append(
                f"""
                <div class="squad-slot" title="Next member">
                    <div class="squad-avatar">+</div>
                    <div class="squad-label">Next member</div>
                </div>
                """
            )

        rows_html.append(
            f"""
            <div class="squad-row">
                <div class="squad-row-head">
                    <h3 class="squad-title">{escape(team_name)}</h3>
                    <div class="squad-meta">Captain: {escape(captain_name)} &nbsp; | &nbsp; {filled_count}/{max_size} roster &nbsp; | &nbsp; Purse {format_inr(team["purse_remaining"])}</div>
                </div>
                <div class="squad-slots">
                    {''.join(slot_html)}
                </div>
            </div>
            """
        )

    st.html(f'<div class="squad-rows">{"".join(rows_html)}</div>')

def render_sale_celebration() -> None:
    """Show a one-time attention message for the latest SOLD audit entry."""
    sold_log = models.one(
        """
        SELECT id, note
        FROM audit_log
        WHERE action = 'SOLD'
        ORDER BY id DESC
        LIMIT 1
        """
    )
    if not sold_log:
        return

    seen_key = "last_sale_celebration_id"
    if st.session_state.get(seen_key) == sold_log["id"]:
        return

    st.session_state[seen_key] = sold_log["id"]
    message = sold_log["note"].split(" for ")[0].replace(" sold to ", " got sold to ")
    st.toast(message)
    st.balloons()

def render_team_progress_grid(db, is_live=False) -> None:
    """A reusable grid showing all teams' logo, purse, max bid, and roster count."""
    from typing import Optional
    
    if hasattr(db, 'get_teams'):
        teams = db.get_teams()
    elif hasattr(db, 'get_all_teams'):
        teams = db.get_all_teams()
    else:
        teams = models.get_all_teams()

    if not teams:
        return

    cols = st.columns(len(teams))
    
    for i, team in enumerate(teams):
        captain = team["captain_name"]
        purse_val = team["purse_remaining"]
        purse = format_inr(purse_val)
        
        if hasattr(db, 'rows'):
            sold_players = db.rows("SELECT id FROM players WHERE sold_team = ?", (team["name"],))
        else:
            sold_players = models.rows("SELECT id FROM players WHERE sold_team = ?", (team["name"],))
            
        roster_count = 1 + len(sold_players)
        max_size = team["max_squad_size"]
        
        empty_slots = max_size - roster_count
        reserved_money = max(0, (empty_slots - 1) * 20_00_000)
        max_bid = max(0, purse_val - reserved_money)
        
        img_src = find_team_logo(team)
            
        html = f"""
        <div class="glass-card" style="text-align: center; padding: 12px; height: 100%;">
            <img src="{escape(img_src or '', quote=True)}" style="width: 55px; height: 55px; border-radius: 8px; margin-bottom: 8px; object-fit: cover; border: 1px solid rgba(255,255,255,0.1);">
            <h3 style="margin: 0 0 2px 0; font-size: 0.9rem; color: #f3f4f6; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">{escape(team['name'])}</h3>
            <p style="margin: 0 0 10px 0; font-size: 0.7rem; color: #9ca3af;">{escape(captain)}</p>
            <div style="background: rgba(0,0,0,0.2); border-radius: 6px; padding: 6px; margin-bottom: 10px; border: 1px solid rgba(34, 197, 94, 0.2);">
                <div style="font-size: 0.65rem; color: #9ca3af; font-weight: bold; letter-spacing: 0.5px;">PURSE REMAINING</div>
                <div style="font-size: 0.95rem; font-weight: bold; color: #22c55e;">{purse}</div>
            </div>
            <div style="display: flex; justify-content: space-between; font-size: 0.75rem; text-align: left; background: rgba(255,255,255,0.03); padding: 6px; border-radius: 4px;">
                <div>
                    <span style="color: #9ca3af; font-size: 0.65rem;">Max Bid</span><br>
                    <span style="color: #fff; font-weight: bold;">{format_inr(max_bid)}</span>
                </div>
                <div style="text-align: right;">
                    <span style="color: #9ca3af; font-size: 0.65rem;">Roster</span><br>
                    <span style="color: #38bdf8; font-weight: bold;">{roster_count}/{max_size}</span>
                </div>
            </div>
        </div>
        """
        cols[i].html(textwrap.dedent(html))

def render_league_poster():
    poster_path = Path("images/league_poster.jpeg")  # change filename

    if poster_path.exists():
        st.markdown(
            """
            <div style="margin-bottom:20px;">
            """,
            unsafe_allow_html=True,
        )

        st.image(
            str(poster_path),
            use_container_width=True
        )

        st.markdown(
            """
            </div>
            """,
            unsafe_allow_html=True,
        )