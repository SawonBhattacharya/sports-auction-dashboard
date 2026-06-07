from __future__ import annotations

import base64
import mimetypes
import os
import re
import sqlite3
import sys
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

# ── Optional PostgreSQL driver ──────────────────────────────────────────────
try:
    import psycopg2
    from psycopg2.extras import RealDictCursor

    _HAS_PG = True
except ImportError:
    _HAS_PG = False


# ═══════════════════════════════════════════════════════════════════════════
# Paths & constants
# ═══════════════════════════════════════════════════════════════════════════

ROOT = Path(__file__).parent
DB_PATH = ROOT / "auction.db"
DEFAULT_WORKBOOK = ROOT / "Auction Tracker v3.xlsx"
IMAGE_DIR = ROOT / "images"
FAVICON_PATH = IMAGE_DIR / "favicon_logo.png"
HOME_LOGO_PATH = IMAGE_DIR / "home_page_logo.png"
ADMIN_PANEL_PATH = IMAGE_DIR / "admin_panel.png"
VIEWER_BACKDROP_PATH = IMAGE_DIR / "viewer_player_focus.png"


# ═══════════════════════════════════════════════════════════════════════════
# Secrets helpers — passcodes & database URL
# ═══════════════════════════════════════════════════════════════════════════

def _get_db_url() -> str | None:
    """Return the PostgreSQL connection URL from Streamlit secrets or env."""
    try:
        url = st.secrets.get("database", {}).get("url")
        if url:
            return str(url)
    except Exception:
        pass
    return os.getenv("DATABASE_URL") or None


def _get_passcode(role: str) -> str:
    """Return the passcode for the given role (admin / viewer).

    Priority: st.secrets → environment variable → empty string (deny by default).
    """
    key = "admin" if role.lower() == "admin" else "viewer"
    env_key = f"AUCTION_{key.upper()}_PASSCODE"
    try:
        code = st.secrets.get("passcodes", {}).get(key)
        if code:
            return str(code)
    except Exception:
        pass
    return os.getenv(env_key, "")


def _use_pg() -> bool:
    """True when a PostgreSQL URL is configured and the driver is available."""
    return _HAS_PG and bool(_get_db_url())


# ═══════════════════════════════════════════════════════════════════════════
# Database abstraction — unified wrapper over sqlite3 / psycopg2
# ═══════════════════════════════════════════════════════════════════════════

_NAMED_PARAM_RE = re.compile(r":([A-Za-z_]\w*)")


class _DBConn:
    """Thin shim so the rest of the app can use *one* coding style
    (``?`` positional params, ``:name`` named params, ``executescript``)
    regardless of whether the backend is SQLite or PostgreSQL.

    Usage is identical to ``sqlite3.Connection``:
    ``con.execute(sql, params).fetchone()``
    """

    def __init__(self, raw_connection: Any, *, is_pg: bool):
        self._raw = raw_connection
        self._pg = is_pg
        self._cur = raw_connection.cursor() if is_pg else None

    # ── param conversion ──────────────────────────────────────────────
    @staticmethod
    def _convert(sql: str, is_pg: bool) -> str:
        if not is_pg:
            return sql
        # :named  →  %(named)s   (must run before ? replacement)
        sql = _NAMED_PARAM_RE.sub(r"%(\1)s", sql)
        # ?  →  %s
        sql = sql.replace("?", "%s")
        return sql

    # ── execute / executemany / executescript ──────────────────────────
    def execute(self, sql: str, params: Any = None) -> Any:
        sql = self._convert(sql, self._pg)
        if self._pg:
            self._cur.execute(sql, params or ())
            return self._cur
        if params:
            return self._raw.execute(sql, params)
        return self._raw.execute(sql)

    def executemany(self, sql: str, params_list: Any) -> Any:
        sql = self._convert(sql, self._pg)
        if self._pg:
            for p in params_list:
                self._cur.execute(sql, p)
            return self._cur
        return self._raw.executemany(sql, params_list)

    def executescript(self, sql: str) -> None:
        if self._pg:
            self._cur.execute(sql)
        else:
            self._raw.executescript(sql)

    # ── transaction & lifecycle ───────────────────────────────────────
    def commit(self) -> None:
        self._raw.commit()

    def close(self) -> None:
        if self._cur:
            try:
                self._cur.close()
            except Exception:
                pass
        try:
            self._raw.close()
        except Exception:
            pass

    def __enter__(self) -> "_DBConn":
        return self

    def __exit__(self, *exc: Any) -> bool:
        self.close()
        return False


# ═══════════════════════════════════════════════════════════════════════════
# Connection factory
# ═══════════════════════════════════════════════════════════════════════════

def connect() -> _DBConn:
    """Return a ``_DBConn`` wrapping either psycopg2 or sqlite3."""
    if _use_pg():
        url = _get_db_url() or ""
        # Check for password placeholders
        if "[YOUR-PASSWORD]" in url or "[YOUR_PASSWORD]" in url or "<password>" in url:
            st.error(
                "❌ **Database Configuration Error**\n\n"
                "It looks like you copied the database URL placeholder without replacing `[YOUR-PASSWORD]` with your actual database password.\n\n"
                "Please update your password in Streamlit Secrets (App Settings → Secrets) and redeploy."
            )
            st.stop()
        try:
            raw = psycopg2.connect(url, cursor_factory=RealDictCursor)
            return _DBConn(raw, is_pg=True)
        except Exception as e:
            st.error(
                "❌ **Database Connection Failed**\n\n"
                "Unable to connect to the cloud PostgreSQL database. This is usually caused by:\n\n"
                "- **Incorrect Password**: Verify that the database password in your connection string is correct.\n"
                "- **Unencoded Special Characters**: If your password contains special characters (e.g. `@`, `:`, `/`, `#`, `?`), they **must** be URL-encoded. For example, `@` becomes `%40`, `#` becomes `%23`, etc.\n"
                "- **Database Paused**: Log into your Supabase dashboard to ensure your database is active and has not been paused due to inactivity.\n\n"
                f"**Error Details:** `{str(e).strip()}`"
            )
            st.stop()
    raw = sqlite3.connect(DB_PATH, check_same_thread=False)
    raw.row_factory = sqlite3.Row
    raw.execute("PRAGMA foreign_keys = ON")
    raw.execute("PRAGMA journal_mode = WAL")
    return _DBConn(raw, is_pg=False)



# ═══════════════════════════════════════════════════════════════════════════
# Streamlit page config (must be the first st.* call)
# ═══════════════════════════════════════════════════════════════════════════

st.set_page_config(
    page_title="Real-Time Sports Auction Portal",
    page_icon=str(FAVICON_PATH) if FAVICON_PATH.exists() else None,
    layout="wide",
    initial_sidebar_state="expanded",
)


CSS = """
<style>
:root {
  --panel: #111827;
  --panel-soft: #172033;
  --ink: #e5e7eb;
  --muted: #9ca3af;
  --line: rgba(255,255,255,.1);
  --accent: #22c55e;
  --accent-2: #38bdf8;
  --danger: #f97316;
}
.stApp {
  background:
    radial-gradient(circle at top left, rgba(34,197,94,.16), transparent 34rem),
    linear-gradient(135deg, #08111f 0%, #121826 55%, #0b1320 100%);
  color: var(--ink);
}
[data-testid="stMetric"] {
  background: rgba(17,24,39,.76);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 12px 14px;
}
[data-testid="stMetricLabel"] p { color: var(--muted); }
.stage-header {
  align-items: center;
  border-bottom: 1px solid var(--line);
  display: flex;
  justify-content: space-between;
  margin-bottom: 18px;
  padding-bottom: 12px;
}
.header-brand {
  align-items: center;
  display: flex;
  gap: 14px;
}
.header-logo {
  background: rgba(255,255,255,.05);
  border: 1px solid var(--line);
  border-radius: 8px;
  height: 58px;
  object-fit: cover;
  width: 58px;
}
.brand-title {
  font-size: clamp(26px, 4vw, 54px);
  font-weight: 800;
  line-height: 1;
}
.live-pill {
  background: rgba(34,197,94,.16);
  border: 1px solid rgba(34,197,94,.45);
  border-radius: 999px;
  color: #bbf7d0;
  font-weight: 700;
  padding: 8px 14px;
}
.panel {
  background: rgba(17,24,39,.78);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 18px;
}
.player-card {
  min-height: 430px;
}
.viewer-stage-shell {
  background: linear-gradient(180deg, rgba(8,17,31,.32), rgba(8,17,31,.9)), var(--viewer-stage-bg);
  background-position: center top;
  background-size: cover;
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: clamp(12px, 2vw, 22px);
}
.stage-backdrop-banner {
  align-items: end;
  aspect-ratio: 16 / 5;
  background: linear-gradient(90deg, rgba(8,17,31,.08), rgba(8,17,31,.78)), var(--viewer-stage-bg);
  background-position: center;
  background-size: cover;
  border: 1px solid var(--line);
  border-radius: 8px;
  display: flex;
  margin-bottom: 18px;
  min-height: 220px;
  overflow: hidden;
  padding: 22px;
}
.stage-backdrop-banner strong {
  color: #ecfccb;
  display: block;
  font-size: clamp(28px, 4vw, 58px);
  line-height: 1;
}
.stage-backdrop-banner span {
  color: #bae6fd;
  display: block;
  font-size: 15px;
  font-weight: 700;
  margin-top: 6px;
}
.avatar {
  align-items: center;
  aspect-ratio: 16 / 9;
  background: linear-gradient(135deg, rgba(56,189,248,.18), rgba(34,197,94,.18));
  border: 1px solid var(--line);
  border-radius: 8px;
  display: flex;
  font-size: clamp(42px, 8vw, 100px);
  font-weight: 900;
  justify-content: center;
  margin-bottom: 18px;
  overflow: hidden;
}
.player-photo-frame {
  border: 2px solid var(--line);
  border-radius: 12px;
  display: block;
  height: 320px;
  margin: 0 auto 20px auto;
  object-fit: cover;
  object-position: top center;
  width: 100%;
  box-shadow: 0 8px 24px rgba(0,0,0,.5);
}
.brand-logo img, .admin-banner img {
  border-radius: 8px;
  display: block;
  margin-bottom: 18px;
  width: 100%;
}
.sidebar-logo {
  border: 2px solid var(--line);
  border-radius: 50%;
  display: block;
  margin: 0 auto 12px auto;
  width: 120px;
  height: 120px;
  object-fit: cover;
}
.player-name {
  font-size: clamp(32px, 5vw, 72px);
  font-weight: 900;
  line-height: 1;
  margin-bottom: 8px;
}
.tag-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin: 12px 0 18px;
}
.tag {
  background: rgba(56,189,248,.12);
  border: 1px solid rgba(56,189,248,.28);
  border-radius: 999px;
  color: #bae6fd;
  padding: 6px 10px;
}
.stat-grid {
  display: grid;
  gap: 8px;
  grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
}
.stat {
  background: rgba(255,255,255,.04);
  border-radius: 8px;
  padding: 10px;
}
.stat small {
  color: var(--muted);
  display: block;
  font-size: 12px;
}
.stat strong {
  display: block;
  font-size: 18px;
  margin-top: 2px;
}
.ticker {
  background: rgba(249,115,22,.12);
  border: 1px solid rgba(249,115,22,.35);
  border-radius: 8px;
  color: #fed7aa;
  font-size: clamp(18px, 2vw, 30px);
  font-weight: 800;
  margin-top: 18px;
  padding: 14px 18px;
  text-align: center;
}
.log-line {
  border-bottom: 1px solid var(--line);
  padding: 8px 0;
}
.small-muted { color: var(--muted); font-size: 13px; }
button[kind="primary"] { font-weight: 800; }

.team-card {
  background: rgba(17, 24, 39, 0.78);
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 20px;
  margin-bottom: 16px;
  display: flex;
  align-items: center;
  gap: 20px;
  transition: transform 0.2s, box-shadow 0.2s;
}
.team-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 8px 20px rgba(0, 0, 0, 0.4);
  border-color: var(--accent);
}
.team-logo-circular {
  width: 80px;
  height: 80px;
  border-radius: 50%;
  border: 2px solid var(--line);
  object-fit: cover;
  background: rgba(255, 255, 255, 0.05);
}
.team-details {
  flex-grow: 1;
}
.team-title {
  font-size: 20px;
  font-weight: 700;
  color: var(--ink);
  margin-bottom: 2px;
}
.team-captain {
  font-size: 14px;
  color: var(--accent-2);
  margin-bottom: 10px;
  font-weight: 600;
}
.team-stats-row {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
  margin-top: 10px;
}
.team-stat-box {
  background: rgba(255, 255, 255, 0.03);
  border-radius: 6px;
  padding: 8px;
  text-align: center;
}
.team-stat-label {
  font-size: 11px;
  color: var(--muted);
  display: block;
}
.team-stat-value {
  font-size: 15px;
  font-weight: 700;
  color: var(--ink);
}
</style>
"""


def image_data_src(path: Path) -> str:
    if not path.exists():
        return "none"
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def image_data_uri(path: Path) -> str:
    src = image_data_src(path)
    return f"url({src})" if src != "none" else "none"


def asset_css() -> str:
    return f"""
    <style>
    :root {{
      --viewer-stage-bg: {image_data_uri(VIEWER_BACKDROP_PATH)};
    }}
    </style>
    """


# ═══════════════════════════════════════════════════════════════════════════
# Database initialisation
# ═══════════════════════════════════════════════════════════════════════════

_PG_DDL = """
CREATE TABLE IF NOT EXISTS players (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    category        TEXT NOT NULL DEFAULT 'Player',
    batting         TEXT,
    bowling         TEXT,
    base_price      INTEGER NOT NULL DEFAULT 10000,
    matches         DOUBLE PRECISION,
    innings         DOUBLE PRECISION,
    runs            DOUBLE PRECISION,
    average         DOUBLE PRECISION,
    strike_rate     DOUBLE PRECISION,
    best_score      TEXT,
    wickets         DOUBLE PRECISION,
    economy         DOUBLE PRECISION,
    fielding_dismissals DOUBLE PRECISION,
    profile_url     TEXT,
    status          TEXT NOT NULL DEFAULT 'AVAILABLE',
    sold_team       TEXT,
    sold_price      INTEGER,
    bid_count       INTEGER NOT NULL DEFAULT 0,
    picked_at       TEXT,
    sold_at         TEXT,
    updated_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS teams (
    name            TEXT PRIMARY KEY,
    captain_name    TEXT,
    logo_url        TEXT,
    starting_purse  INTEGER NOT NULL,
    max_squad_size  INTEGER NOT NULL,
    min_roster_size INTEGER NOT NULL,
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS auction_state (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS audit_log (
    id          SERIAL PRIMARY KEY,
    action      TEXT NOT NULL,
    player_id   TEXT,
    team_name   TEXT,
    amount      INTEGER,
    bid_count   INTEGER,
    note        TEXT,
    created_at  TEXT NOT NULL
);
"""

_SQLITE_DDL = """
CREATE TABLE IF NOT EXISTS players (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'Player',
    batting TEXT,
    bowling TEXT,
    base_price INTEGER NOT NULL DEFAULT 10000,
    matches REAL,
    innings REAL,
    runs REAL,
    average REAL,
    strike_rate REAL,
    best_score TEXT,
    wickets REAL,
    economy REAL,
    fielding_dismissals REAL,
    profile_url TEXT,
    status TEXT NOT NULL DEFAULT 'AVAILABLE',
    sold_team TEXT,
    sold_price INTEGER,
    bid_count INTEGER NOT NULL DEFAULT 0,
    picked_at TEXT,
    sold_at TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS teams (
    name TEXT PRIMARY KEY,
    captain_name TEXT,
    logo_url TEXT,
    starting_purse INTEGER NOT NULL,
    max_squad_size INTEGER NOT NULL,
    min_roster_size INTEGER NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS auction_state (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action TEXT NOT NULL,
    player_id TEXT,
    team_name TEXT,
    amount INTEGER,
    bid_count INTEGER,
    note TEXT,
    created_at TEXT NOT NULL
);
"""


def init_db() -> None:
    with closing(connect()) as con:
        # ── Create tables ─────────────────────────────────────────────
        if _use_pg():
            con.execute(_PG_DDL)
            # Column migration (PG supports IF NOT EXISTS on ALTER)
            con.execute("ALTER TABLE teams ADD COLUMN IF NOT EXISTS captain_name TEXT")
            con.execute("ALTER TABLE teams ADD COLUMN IF NOT EXISTS logo_url TEXT")
        else:
            con.executescript(_SQLITE_DDL)
            # Column migration for older SQLite databases
            cursor = con.execute("PRAGMA table_info(teams)")
            columns = [row["name"] for row in cursor.fetchall()]
            if columns:
                if "captain_name" not in columns:
                    con.execute("ALTER TABLE teams ADD COLUMN captain_name TEXT")
                if "logo_url" not in columns:
                    con.execute("ALTER TABLE teams ADD COLUMN logo_url TEXT")

        # ── Seed default teams if empty ───────────────────────────────
        if not con.execute("SELECT 1 FROM teams LIMIT 1").fetchone():
            now = utc_now()
            con.executemany(
                "INSERT INTO teams (name, captain_name, logo_url, starting_purse, max_squad_size, min_roster_size, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    ("Team Alpha", "DRAGLEEOO", "", 100000, 9, 9, now),
                    ("Team Bravo", "Ankit Jaiswal", "", 100000, 9, 9, now),
                    ("Team Charlie", "Swapneel Chakraborty", "", 100000, 9, 9, now),
                    ("Team Delta", "Sawon Bhattacharya", "", 100000, 9, 9, now),
                ],
            )
        if not get_state(con, "auction_status"):
            set_state(con, "auction_status", "LIVE")
        con.commit()


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def get_state(con: _DBConn, key: str, default: str | None = None) -> str | None:
    row = con.execute("SELECT value FROM auction_state WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_state(con: _DBConn, key: str, value: str | None) -> None:
    con.execute(
        "INSERT INTO auction_state(key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def rows(query: str, params: tuple[Any, ...] = ()) -> list[Any]:
    with closing(connect()) as con:
        return con.execute(query, params).fetchall()


def one(query: str, params: tuple[Any, ...] = ()) -> Any | None:
    with closing(connect()) as con:
        return con.execute(query, params).fetchone()


def rupees(value: Any) -> str:
    try:
        amount = int(float(value or 0))
    except (TypeError, ValueError):
        amount = 0
    return "Rs. " + f"{amount:,}"


def number_or_none(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def clean_text(value: Any) -> str:
    if value is None or str(value).lower() == "nan":
        return ""
    return str(value).strip()


def player_category(row: pd.Series) -> str:
    batting = clean_text(row.get("Batting"))
    bowling = clean_text(row.get("Bowling"))
    wickets = number_or_none(row.get("Wickets")) or 0
    runs = number_or_none(row.get("Runs")) or 0
    if wickets >= 15 and runs >= 250:
        return "All-Rounder"
    if wickets >= 15:
        return "Bowler"
    if runs >= 250:
        return "Batsman"
    if bowling and bowling.lower() not in {"throw", "none", "na"} and batting:
        return "All-Rounder"
    if bowling:
        return "Bowler"
    return "Batsman" if batting else "Player"


def extract_profile_url(value: Any) -> str:
    text = clean_text(value)
    return text if text.startswith("http") else ""


def load_excel_players(path: Path, base_price: int) -> pd.DataFrame:
    stats = pd.read_excel(path, sheet_name="Player_DB")
    stats.columns = [clean_text(c) for c in stats.columns]
    stats = stats.dropna(how="all")
    stats = stats[stats.get("Name").notna()]
    stats["Name"] = stats["Name"].map(clean_text)

    try:
        responses = pd.read_excel(path, sheet_name="Form responses 1")
        responses.columns = [clean_text(c) for c in responses.columns]
        responses["Name_clean"] = responses["Name"].map(lambda x: clean_text(x).lower())
    except Exception:
        responses = pd.DataFrame()

    records: list[dict[str, Any]] = []
    for idx, row in stats.iterrows():
        name = clean_text(row.get("Name"))
        if not name:
            continue
        response = None
        if not responses.empty:
            match = responses[responses["Name_clean"] == name.lower()]
            if not match.empty:
                response = match.iloc[0]
        player_id = clean_text(row.get("Player ID")) or f"P{idx + 1:03d}"
        batting = clean_text(response.get("Batting")) if response is not None else ""
        bowling = clean_text(response.get("Bowling")) if response is not None else ""
        records.append(
            {
                "id": player_id,
                "name": name,
                "category": player_category(row if response is None else row.combine_first(response)),
                "batting": batting,
                "bowling": bowling,
                "base_price": base_price,
                "matches": number_or_none(row.get("Matches")),
                "innings": number_or_none(row.get("Innings")),
                "runs": number_or_none(row.get("Runs")),
                "average": number_or_none(row.get("Avg")),
                "strike_rate": number_or_none(row.get("SR")),
                "best_score": clean_text(row.get("Best Score")),
                "wickets": number_or_none(row.get("Wickets")),
                "economy": number_or_none(row.get("Economy")),
                "fielding_dismissals": number_or_none(row.get("Fielding Dismissals")),
                "profile_url": extract_profile_url(row.get("Profile")),
            }
        )
    return pd.DataFrame(records)


def import_players(path: Path, base_price: int, replace_existing: bool) -> int:
    df = load_excel_players(path, base_price)
    now = utc_now()
    with closing(connect()) as con:
        if replace_existing:
            con.execute("DELETE FROM players")
            set_state(con, "active_player_id", None)
        count = 0
        for record in df.to_dict("records"):
            con.execute(
                """
                INSERT INTO players (
                    id, name, category, batting, bowling, base_price, matches, innings,
                    runs, average, strike_rate, best_score, wickets, economy,
                    fielding_dismissals, profile_url, updated_at
                ) VALUES (
                    :id, :name, :category, :batting, :bowling, :base_price, :matches,
                    :innings, :runs, :average, :strike_rate, :best_score, :wickets,
                    :economy, :fielding_dismissals, :profile_url, :updated_at
                )
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    category = excluded.category,
                    batting = excluded.batting,
                    bowling = excluded.bowling,
                    base_price = excluded.base_price,
                    matches = excluded.matches,
                    innings = excluded.innings,
                    runs = excluded.runs,
                    average = excluded.average,
                    strike_rate = excluded.strike_rate,
                    best_score = excluded.best_score,
                    wickets = excluded.wickets,
                    economy = excluded.economy,
                    fielding_dismissals = excluded.fielding_dismissals,
                    profile_url = excluded.profile_url,
                    updated_at = excluded.updated_at
                """,
                {**record, "updated_at": now},
            )
            count += 1
        con.execute(
            "INSERT INTO audit_log(action, note, created_at) VALUES (?, ?, ?)",
            ("SYNC", f"Imported {count} players from {path.name}", now),
        )
        con.commit()
        mark_captains()
    return count


def standings() -> list[dict[str, Any]]:
    team_rows = rows("SELECT * FROM teams ORDER BY name")
    sold_rows = rows(
        """
        SELECT sold_team, COUNT(*) AS squad_size, COALESCE(SUM(sold_price), 0) AS spent
        FROM players
        WHERE status = 'SOLD'
        GROUP BY sold_team
        """
    )
    last_rows = rows(
        """
        SELECT p.sold_team, p.name, p.sold_at
        FROM players p
        WHERE p.status = 'SOLD' AND p.sold_at IS NOT NULL
        ORDER BY p.sold_at DESC
        """
    )
    sold_by_team = {r["sold_team"]: r for r in sold_rows}
    last_by_team: dict[str, str] = {}
    for row in last_rows:
        last_by_team.setdefault(row["sold_team"], row["name"])

    result = []
    for team in team_rows:
        sold = sold_by_team.get(team["name"])
        spent = int(sold["spent"]) if sold else 0
        squad_size = int(sold["squad_size"]) if sold else 0
        remaining = int(team["starting_purse"]) - spent
        max_bid = calculate_max_bid(
            remaining,
            squad_size,
            int(team["min_roster_size"]),
            int(team["max_squad_size"]),
        )
        result.append(
            {
                "Team Name": team["name"],
                "Captain": team["captain_name"] or "None",
                "Logo URL": team["logo_url"] or "",
                "Remaining Purse": remaining,
                "Max Bid Power": max_bid,
                "Roster Count": f"{squad_size} / {team['max_squad_size']}",
                "Squad Size": squad_size,
                "Max Squad Size": team["max_squad_size"],
                "Min Roster Size": team["min_roster_size"],
                "Last Purchase": last_by_team.get(team["name"], "-"),
            }
        )
    return result


def calculate_max_bid(
    remaining_purse: int,
    current_squad_size: int,
    min_roster_size: int,
    max_squad_size: int,
) -> int:
    if current_squad_size >= max_squad_size:
        return 0
    minimum_base = get_min_base_price()
    protected_slots = max(min_roster_size - current_squad_size - 1, 0)
    return max(remaining_purse - protected_slots * minimum_base, 0)


def get_min_base_price() -> int:
    row = one("SELECT COALESCE(MIN(base_price), 50000) AS min_base FROM players")
    return int(row["min_base"] or 50000) if row else 50000


def active_player() -> Any | None:
    with closing(connect()) as con:
        active_id = get_state(con, "active_player_id")
        if not active_id:
            return None
        return con.execute("SELECT * FROM players WHERE id = ?", (active_id,)).fetchone()


def draw_player() -> Any | None:
    with closing(connect()) as con:
        available = con.execute(
            "SELECT * FROM players WHERE status = 'AVAILABLE' ORDER BY RANDOM() LIMIT 1"
        ).fetchone()
        if not available:
            return None
        now = utc_now()
        con.execute(
            "UPDATE players SET status = 'ACTIVE', picked_at = ?, updated_at = ? WHERE id = ?",
            (now, now, available["id"]),
        )
        set_state(con, "active_player_id", available["id"])
        con.execute(
            "INSERT INTO audit_log(action, player_id, note, created_at) VALUES (?, ?, ?, ?)",
            ("DRAW", available["id"], f"Drawn: {available['name']}", now),
        )
        con.commit()
        return available


def mark_sold(player_id: str, team_name: str, sale_price: int, bid_count: int) -> tuple[bool, str]:
    table = standings()
    team = next((r for r in table if r["Team Name"] == team_name), None)
    player = one("SELECT * FROM players WHERE id = ?", (player_id,))
    if not team or not player:
        return False, "Missing team or player."
    if player["status"] != "ACTIVE":
        return False, "Player is not currently active."

    if team["Squad Size"] >= team["Max Squad Size"]:
        return False, f"{team_name} already has a full squad."
    if sale_price < int(player["base_price"]):
        return False, "Sale price cannot be below the player base price."
    if sale_price > int(team["Max Bid Power"]):
        return False, f"{team_name} can bid up to {rupees(team['Max Bid Power'])}."

    with closing(connect()) as con:
        now = utc_now()
        con.execute(
            """
            UPDATE players
            SET status = 'SOLD', sold_team = ?, sold_price = ?, bid_count = ?,
                sold_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (team_name, sale_price, bid_count, now, now, player_id),
        )
        set_state(con, "active_player_id", None)
        con.execute(
            """
            INSERT INTO audit_log(action, player_id, team_name, amount, bid_count, note, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("SOLD", player_id, team_name, sale_price, bid_count, f"Sold to {team_name}", now),
        )
        con.commit()
    return True, "Player marked sold."


def mark_unsold(player_id: str, note: str = "") -> None:
    with closing(connect()) as con:
        now = utc_now()
        con.execute(
            "UPDATE players SET status = 'UNSOLD', updated_at = ? WHERE id = ?",
            (now, player_id),
        )
        set_state(con, "active_player_id", None)
        con.execute(
            "INSERT INTO audit_log(action, player_id, note, created_at) VALUES (?, ?, ?, ?)",
            ("UNSOLD", player_id, note, now),
        )
        con.commit()


def reset_player(player_id: str) -> None:
    """Return a player to AVAILABLE (or CAPTAIN if they are a team captain)."""
    player = one("SELECT name FROM players WHERE id=?", (player_id,))
    captain_names = {
        r["captain_name"].strip().lower()
        for r in rows("SELECT captain_name FROM teams")
        if r["captain_name"]
    }
    new_status = (
        "CAPTAIN"
        if player and player["name"].strip().lower() in captain_names
        else "AVAILABLE"
    )
    with closing(connect()) as con:
        now = utc_now()
        con.execute(
            "UPDATE players SET status=?, sold_team=NULL, sold_price=NULL, bid_count=0, picked_at=NULL, sold_at=NULL, updated_at=? WHERE id=?",
            (new_status, now, player_id),
        )
        active_id = get_state(con, "active_player_id")
        if active_id == player_id:
            set_state(con, "active_player_id", None)
        con.execute(
            "INSERT INTO audit_log(action, player_id, note, created_at) VALUES (?, ?, ?, ?)",
            ("RESTORED", player_id, f"Reset to {new_status}", now),
        )
        con.commit()


def summary_metrics() -> dict[str, Any]:
    with closing(connect()) as con:
        sold = con.execute("SELECT COUNT(*) c, COALESCE(SUM(sold_price), 0) total FROM players WHERE status='SOLD'").fetchone()
        unsold = con.execute("SELECT COUNT(*) c FROM players WHERE status='UNSOLD'").fetchone()
        remaining = con.execute("SELECT COUNT(*) c FROM players WHERE status='AVAILABLE'").fetchone()
        highest = con.execute(
            "SELECT name, sold_team, sold_price FROM players WHERE status='SOLD' ORDER BY sold_price DESC LIMIT 1"
        ).fetchone()
    return {
        "sold": int(sold["c"] or 0),
        "total_spent": int(sold["total"] or 0),
        "unsold": int(unsold["c"] or 0),
        "remaining": int(remaining["c"] or 0),
        "highest": highest,
    }


def render_header(status: str) -> None:
    logo = ""
    if FAVICON_PATH.exists():
        logo = f'<img class="header-logo" src="{image_data_src(FAVICON_PATH)}" alt="Auction logo">'
    st.markdown(
        f"""
        <div class="stage-header">
          <div class="header-brand">
            {logo}
            <div>
              <div class="small-muted">LOCAL TOURNAMENT</div>
              <div class="brand-title">Live Auction 2026</div>
            </div>
          </div>
          <div class="live-pill">STATUS: {status}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_player_card(player: Any | None) -> None:
    if player is None:
        st.markdown(
            """
            <div class="panel player-card">
              <div class="player-name">Waiting for draw</div>
              <div class="small-muted">The active player will appear here as soon as the admin draws from the pool.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        return
    local_photo = find_player_image(player)
    photo_html = (
        f'<img class="player-photo-frame" src="{image_data_src(local_photo)}" alt="{player["name"]}">'
        if local_photo
        else ""
    )
    st.markdown(
        f"""
        <div class="panel player-card">
          {photo_html}
          <div class="player-name">{player['name']}</div>
          <div class="tag-row">
            <span class="tag">{player['category']}</span>
            <span class="tag">Base: {rupees(player['base_price'])}</span>
            <span class="tag">ID: {player['id']}</span>
          </div>
          <div class="stat-grid">
            <div class="stat"><small>Matches</small><strong>{fmt_num(player['matches'])}</strong></div>
            <div class="stat"><small>Runs</small><strong>{fmt_num(player['runs'])}</strong></div>
            <div class="stat"><small>Strike Rate</small><strong>{fmt_num(player['strike_rate'])}</strong></div>
            <div class="stat"><small>Wickets</small><strong>{fmt_num(player['wickets'])}</strong></div>
            <div class="stat"><small>Economy</small><strong>{fmt_num(player['economy'])}</strong></div>
            <div class="stat"><small>Best Score</small><strong>{player['best_score'] or '-'}</strong></div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def slug(value: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "_" for ch in value.strip())
    return "_".join(part for part in cleaned.split("_") if part)


def save_team_logo(team_name: str, uploaded_file) -> str:
    if not IMAGE_DIR.exists():
        IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = slug(team_name)
    file_ext = Path(uploaded_file.name).suffix or ".png"
    logo_path = IMAGE_DIR / f"team_{safe_name}_logo{file_ext}"
    with open(logo_path, "wb") as f:
        f.write(uploaded_file.getbuffer())
    return str(logo_path)


def _normalise(text: str) -> str:
    """Lowercase, keep only alphanumeric chars, collapse whitespace."""
    return " ".join("".join(ch for ch in text.lower() if ch.isalnum() or ch == " ").split())


def find_player_image(player: Any) -> Path | None:
    """Resolve the best photo for a player.

    Priority order:
      1. Direct name match in ``images/Player_Photo/``:  filename stem is
         compared (normalised) against the player name.  Files are now simply
         named ``Player Name.jpg`` with no hash prefix.
      2. Same scan in the root ``images/`` folder as a last resort.
    """
    # ── 1. Auto name-matching ────────────────────────────────────────────
    player_photo_dir = IMAGE_DIR / "Player_Photo"
    search_dirs = [d for d in [player_photo_dir, IMAGE_DIR] if d.exists()]

    target_name = _normalise(player["name"])
    target_id   = _normalise(str(player["id"]))

    for search_dir in search_dirs:
        for file in search_dir.iterdir():
            if file.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
                continue
            # Filenames are now just "Player Name.ext" — compare stem directly
            name_part = _normalise(file.stem)
            if name_part == target_name or name_part == target_id:
                return file
    return None


def get_all_player_photos() -> list[Path]:
    """Return every image file in images/Player_Photo/ then root images/."""
    found: list[Path] = []
    for search_dir in [IMAGE_DIR / "Player_Photo", IMAGE_DIR]:
        if not search_dir.exists():
            continue
        for f in sorted(search_dir.iterdir()):
            if f.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
                found.append(f)
    return found


def fmt_num(value: Any) -> str:
    if value is None or value == "":
        return "-"
    try:
        n = float(value)
    except (TypeError, ValueError):
        return str(value)
    return str(int(n)) if n.is_integer() else f"{n:.2f}"


def render_room_status() -> None:
    metrics = summary_metrics()
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    c1.metric("Total Purse Spent", rupees(metrics["total_spent"]))
    c2.metric("Players Sold", metrics["sold"])
    c3, c4 = st.columns(2)
    c3.metric("Unsold Count", metrics["unsold"])
    c4.metric("Remaining Players", metrics["remaining"])
    st.markdown("#### Max Bid Power")
    for row in standings():
        st.progress(
            min(row["Max Bid Power"] / max(row["Remaining Purse"], 1), 1.0)
            if row["Remaining Purse"] > 0
            else 0,
            text=f"{row['Team Name']}: {rupees(row['Max Bid Power'])}",
        )
    st.markdown("</div>", unsafe_allow_html=True)

    highest = metrics["highest"]
    if highest:
        text = (
            f"Current highest bid: {rupees(highest['sold_price'])} "
            f"({highest['name']} to {highest['sold_team']})"
        )
    else:
        text = "Current highest bid: auction has not recorded a sale yet"
    st.markdown(f'<div class="ticker">{text}</div>', unsafe_allow_html=True)


def viewer_stage() -> None:
    render_header(get_auction_status())
    current = active_player()
    # Backdrop always uses the venue image — player photo appears inside the card only
    st.markdown(
        """
        <div class="stage-backdrop-banner">
          <div>
            <strong>CrickBid Live</strong>
            <span>Player focus, purse pressure, and bid power in one room view</span>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown('<div class="viewer-stage-shell">', unsafe_allow_html=True)
    left, right = st.columns([1.55, 1], gap="large")
    with left:
        render_player_card(current)
    with right:
        render_room_status()
    st.markdown("</div>", unsafe_allow_html=True)



def get_auction_status() -> str:
    with closing(connect()) as con:
        return get_state(con, "auction_status", "LIVE") or "LIVE"


def admin_console() -> None:
    if ADMIN_PANEL_PATH.exists():
        st.markdown('<div class="admin-banner">', unsafe_allow_html=True)
        st.image(str(ADMIN_PANEL_PATH), use_container_width=True)
        st.markdown("</div>", unsafe_allow_html=True)
    st.title("Admin Auction Console")
    current = active_player()
    c1, c2 = st.columns([1, 1], gap="large")

    with c1:
        st.subheader("Step 1: Draw Player")
        render_player_card(current)
        col_a, col_b = st.columns(2)
        if col_a.button("Spin / Next Random Player", type="primary", use_container_width=True):
            if current:
                st.warning("Resolve the active player before drawing another.")
            else:
                drawn = draw_player()
                if drawn:
                    st.success(f"Drawn: {drawn['name']}")
                    st.rerun()
                else:
                    st.info("No available players remain.")
        if col_b.button("Clear Active", use_container_width=True, disabled=current is None):
            if current:
                reset_player(current["id"])
                st.rerun()

    with c2:
        st.subheader("Step 2: Live Bidding Input")
        teams = [r["Team Name"] for r in standings()]
        if not current:
            st.info("Draw a player to enable bidding controls.")
        else:
            with st.form("sale_form"):
                team = st.selectbox("Winning team", teams)
                price = st.number_input(
                    "Final sale price",
                    min_value=int(current["base_price"]),
                    value=int(current["base_price"]),
                    step=get_min_base_price(),
                )
                bids = st.number_input("Number of bids", min_value=0, value=1, step=1)
                submitted = st.form_submit_button("Mark Sold", type="primary", use_container_width=True)
            if submitted:
                ok, msg = mark_sold(current["id"], team, int(price), int(bids))
                if ok:
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)
            if st.button("Mark Unsold", use_container_width=True):
                mark_unsold(current["id"])
                st.success("Player marked unsold.")
                st.rerun()

    st.divider()
    st.subheader("Step 3: Database Quick Actions")
    q1, q2, q3 = st.columns(3)
    with q1:
        with st.popover("Sync Excel Data", use_container_width=True):
            sync_base_price = st.number_input("Player Base Price", min_value=0, value=10000, step=1000)
            sync_replace = st.checkbox("Replace existing players", value=False)
            if st.button("Run Sync Now", type="primary", use_container_width=True):
                try:
                    count = import_players(DEFAULT_WORKBOOK, base_price=int(sync_base_price), replace_existing=sync_replace)
                    st.success(f"Synced {count} players.")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Sync failed: {exc}")
    with q2:
        status = get_auction_status()
        new_status = "PAUSED" if status == "LIVE" else "LIVE"
        if st.button(f"{'Pause' if status == 'LIVE' else 'Resume'} Auction", use_container_width=True):
            with closing(connect()) as con:
                set_state(con, "auction_status", new_status)
                con.commit()
            st.rerun()
    with q3:
        correction_panel()


def correction_panel() -> None:
    with st.popover("Correction / Edit", use_container_width=True):
        sold_or_unsold = rows(
            "SELECT id, name, status, sold_team, sold_price FROM players "
            "WHERE status IN ('SOLD','UNSOLD','ACTIVE') ORDER BY updated_at DESC LIMIT 100"
        )
        if not sold_or_unsold:
            st.caption("No auctioned players yet.")
            return
        labels = [f"{r['name']} - {r['status']}" for r in sold_or_unsold]
        selected = st.selectbox("Player", labels)
        player = sold_or_unsold[labels.index(selected)]
        if st.button("Return selected player to pool", use_container_width=True):
            reset_player(player["id"])
            st.success("Returned to pool.")
            st.rerun()


def team_leaderboards() -> None:
    st.title("Team Leaderboards")
    table = standings()
    
    # Render cards in a grid of 2 columns
    cols = st.columns(2)
    for idx, row in enumerate(table):
        col = cols[idx % 2]
        with col:
            logo_path_str = row.get("Logo URL", "")
            if logo_path_str and os.path.exists(logo_path_str):
                logo_src = image_data_src(Path(logo_path_str))
            else:
                initials = "".join(part[:1] for part in row["Team Name"].split()[:2]).upper()
                logo_src = f"https://placehold.co/120x120/172033/e5e7eb?text={initials}"
            
            html_card = f"""
            <div class="team-card">
              <img class="team-logo-circular" src="{logo_src}" alt="{row['Team Name']}">
              <div class="team-details">
                <div class="team-title">{row['Team Name']}</div>
                <div class="team-captain">Captain: {row['Captain']}</div>
                <div class="team-stats-row">
                  <div class="team-stat-box">
                    <span class="team-stat-label">Purse Remaining</span>
                    <span class="team-stat-value" style="color: var(--accent);">{rupees(row['Remaining Purse'])}</span>
                  </div>
                  <div class="team-stat-box">
                    <span class="team-stat-label">Max Bid Power</span>
                    <span class="team-stat-value" style="color: var(--accent-2);">{rupees(row['Max Bid Power'])}</span>
                  </div>
                  <div class="team-stat-box">
                    <span class="team-stat-label">Roster Count</span>
                    <span class="team-stat-value">{row['Roster Count']}</span>
                  </div>
                </div>
                <div style="margin-top: 12px; font-size: 13px;">
                  <span class="small-muted">Last Purchase: </span>
                  <strong style="color: var(--ink);">{row['Last Purchase']}</strong>
                </div>
              </div>
            </div>
            """
            st.markdown(html_card, unsafe_allow_html=True)
            
    st.divider()
    teams = [r["Team Name"] for r in table]
    st.subheader("Squad Roster Details")
    selected = st.selectbox("Select Team to view players", teams)
    squad = rows(
        "SELECT name, category, sold_price, bid_count FROM players WHERE sold_team = ? ORDER BY sold_at",
        (selected,),
    )
    if squad:
        display_squad = []
        for player in squad:
            display_squad.append({
                "Player Name": player["name"],
                "Category": player["category"],
                "Sold Price": rupees(player["sold_price"]),
                "Bids Count": player["bid_count"]
            })
        st.dataframe(display_squad, hide_index=True, use_container_width=True)
    else:
        st.info("No players purchased by this team yet.")




def manage_teams_panel() -> None:
    st.subheader("Manage Teams Configuration")
    team_list = rows("SELECT * FROM teams ORDER BY name")
    
    for idx, team in enumerate(team_list):
        expander_title = f"Edit {team['name']} (Captain: {team['captain_name'] or 'None'})"
        with st.expander(expander_title, expanded=(idx == 0)):
            with st.form(f"edit_team_form_{team['name']}", clear_on_submit=False):
                new_name = st.text_input("Team Name", value=team["name"])
                new_captain = st.text_input("Captain Name", value=team["captain_name"] or "")
                
                logo_file = st.file_uploader(f"Upload New Team Logo for {team['name']}", type=["png", "jpg", "jpeg", "webp"], key=f"logo_upload_{team['name']}")
                
                # Show current logo if exists
                if team["logo_url"] and os.path.exists(team["logo_url"]):
                    logo_src = image_data_src(Path(team["logo_url"]))
                    st.markdown(
                        f'<div>Current Logo: <img class="team-logo-circular" src="{logo_src}" style="width: 50px; height: 50px;"></div>',
                        unsafe_allow_html=True
                    )
                
                c1, c2, c3 = st.columns(3)
                new_purse = c1.number_input("Starting Purse ($ / points)", min_value=0, value=int(team["starting_purse"]), step=10000)
                new_max_squad = c2.number_input("Max Squad Size (hardcore 9)", min_value=1, value=int(team["max_squad_size"]), step=1)
                new_min_roster = c3.number_input("Min Roster Size (hardcore 9)", min_value=1, value=int(team["min_roster_size"]), step=1)
                
                submitted = st.form_submit_button("Save Changes", type="primary")
                if submitted:
                    logo_path = team["logo_url"]
                    if logo_file:
                        logo_path = save_team_logo(new_name, logo_file)
                    
                    # Update database with transaction safety
                    with closing(connect()) as con:
                        # If name changed, rename cascade in players and audit logs
                        if new_name != team["name"]:
                            con.execute("UPDATE players SET sold_team = ? WHERE sold_team = ?", (new_name, team["name"]))
                            con.execute("UPDATE audit_log SET team_name = ? WHERE team_name = ?", (new_name, team["name"]))
                        
                        con.execute(
                            """
                            UPDATE teams
                            SET name = ?, captain_name = ?, logo_url = ?, starting_purse = ?,
                                max_squad_size = ?, min_roster_size = ?
                            WHERE name = ?
                            """,
                            (new_name, new_captain, logo_path, int(new_purse), int(new_max_squad), int(new_min_roster), team["name"])
                        )
                        con.commit()
                    
                    mark_captains()
                    st.success(f"Successfully updated team {new_name} details!")
                    st.rerun()


def auction_control_panel() -> None:
    st.subheader("Auction State & Admin Controls")
    
    # 1. State status
    status = get_auction_status()
    st.info(f"Current Auction Status: **{status}**")
    
    # Explain database persistence
    st.markdown(
        """
        <div class="panel" style="border-left: 4px solid var(--accent-2); padding: 15px; margin-bottom: 20px;">
          <strong style="color: var(--accent-2);">Real-Time Database Persistence:</strong><br>
          All auction events, draws, bids, and team data are automatically and immediately saved to the database. 
          If the application server goes down or restarts, <strong>you will not lose any data</strong>. The next load will automatically resume exactly where you left off.
        </div>
        """,
        unsafe_allow_html=True
    )
    
    st.divider()
    
    st.subheader("Action Controls")
    c1, c2 = st.columns(2)
    with c1:
        if status == "LIVE":
            if st.button("Pause Auction", type="primary", use_container_width=True):
                with closing(connect()) as con:
                    set_state(con, "auction_status", "PAUSED")
                    con.commit()
                st.success("Auction has been PAUSED.")
                st.rerun()
        else:
            if st.button("Start / Resume Auction", type="primary", use_container_width=True):
                with closing(connect()) as con:
                    set_state(con, "auction_status", "LIVE")
                    con.commit()
                st.success("Auction is now LIVE.")
                st.rerun()
                
    st.divider()
    st.subheader("Danger Zone")
    
    with st.expander("Reset Database / Clear Roster (⚠️ IRREVERSIBLE)"):
        st.warning("These operations will erase bid data and cannot be undone. Be careful!")
        
        # Soft reset
        if st.button("Clear Auction Roster (Soft Reset)", use_container_width=True):
            with closing(connect()) as con:
                now = utc_now()
                # Reset all players
                con.execute(
                    """
                    UPDATE players
                    SET status = 'AVAILABLE', sold_team = NULL, sold_price = NULL,
                        bid_count = 0, picked_at = NULL, sold_at = NULL, updated_at = ?
                    """,
                    (now,),
                )
                # Reset active player ID
                set_state(con, "active_player_id", None)
                # Clear logs
                con.execute("DELETE FROM audit_log")
                con.execute(
                    "INSERT INTO audit_log(action, note, created_at) VALUES (?, ?, ?)",
                    ("RESET_AUCTION", "Auction roster cleared and logs reset.", now),
                )
                # Ensure existing teams have budget 100000 and 9 player squad limits
                con.execute(
                    """
                    UPDATE teams
                    SET starting_purse = 100000, max_squad_size = 9, min_roster_size = 9
                    """
                )
                # Set status to LIVE
                set_state(con, "auction_status", "LIVE")
                con.commit()
            st.success("Rosters cleared, purse budgets reset to 100k, and squad sizes reset to 9 players!")
            st.rerun()
            
        # Hard reset
        if st.button("Full Reset to Defaults (Overwrite Teams)", use_container_width=True):
            with closing(connect()) as con:
                now = utc_now()
                # Clear players & reset
                con.execute(
                    """
                    UPDATE players
                    SET status = 'AVAILABLE', sold_team = NULL, sold_price = NULL,
                        bid_count = 0, picked_at = NULL, sold_at = NULL, updated_at = ?
                    """,
                    (now,),
                )
                # Reset active player ID
                set_state(con, "active_player_id", None)
                # Clear logs
                con.execute("DELETE FROM audit_log")
                con.execute(
                    "INSERT INTO audit_log(action, note, created_at) VALUES (?, ?, ?)",
                    ("HARD_RESET", "Auction hard reset to default database state.", now),
                )
                # Reset and override all teams to the four captains
                con.execute("DELETE FROM teams")
                con.executemany(
                    """
                    INSERT INTO teams (name, captain_name, logo_url, starting_purse, max_squad_size, min_roster_size, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        ("Team Alpha", "DRAGLEEOO", "", 100000, 9, 9, now),
                        ("Team Bravo", "Ankit Jaiswal", "", 100000, 9, 9, now),
                        ("Team Charlie", "Swapneel Chakraborty", "", 100000, 9, 9, now),
                        ("Team Delta", "Sawon Bhattacharya", "", 100000, 9, 9, now),
                    ],
                )
                # Set status to LIVE
                set_state(con, "auction_status", "LIVE")
                con.commit()
            st.success("Successfully completed full reset! Default captains loaded with 100k budget and 9 player limits.")
            st.rerun()


def exclude_player(player_id: str, reason: str = "") -> None:
    """Mark a player as EXCLUDED so they are skipped by the draw and auction."""
    with closing(connect()) as con:
        now = utc_now()
        con.execute(
            "UPDATE players SET status = 'EXCLUDED', updated_at = ? WHERE id = ?",
            (now, player_id),
        )
        active_id = get_state(con, "active_player_id")
        if active_id == player_id:
            set_state(con, "active_player_id", None)
        con.execute(
            "INSERT INTO audit_log(action, player_id, note, created_at) VALUES (?, ?, ?, ?)",
            ("EXCLUDED", player_id, reason or "Excluded before auction", now),
        )
        con.commit()


def restore_player(player_id: str) -> None:
    """Restore an EXCLUDED player back to AVAILABLE."""
    with closing(connect()) as con:
        now = utc_now()
        con.execute(
            "UPDATE players SET status = 'AVAILABLE', updated_at = ? WHERE id = ?",
            (now, player_id),
        )
        con.execute(
            "INSERT INTO audit_log(action, player_id, note, created_at) VALUES (?, ?, ?, ?)",
            ("RESTORED", player_id, "Restored to auction pool", now),
        )
        con.commit()

def mark_captains() -> None:
    teams = rows(
        """
        SELECT captain_name
        FROM teams
        WHERE captain_name IS NOT NULL
        """
    )

    captain_names = [
        t["captain_name"].strip().lower()
        for t in teams
        if t["captain_name"]
    ]

    if not captain_names:
        return

    with closing(connect()) as con:

        # First remove old captain tags
        con.execute(
            """
            UPDATE players
            SET status='AVAILABLE'
            WHERE status='CAPTAIN'
            """
        )

        placeholders = ",".join("?" * len(captain_names))

        con.execute(
            f"""
            UPDATE players
            SET status='CAPTAIN'
            WHERE LOWER(name) IN ({placeholders})
            """,
            tuple(captain_names),
        )

        con.commit()

def update_player_base_price(player_id: str, new_price: int) -> None:
    with closing(connect()) as con:
        con.execute(
            "UPDATE players SET base_price = ?, updated_at = ? WHERE id = ?",
            (new_price, utc_now(), player_id),
        )
        con.commit()


def player_roster_panel() -> None:
    """Admin panel: exclude players from the auction before it starts,
    and individually adjust base prices."""
    st.title("Player Roster Management")

    st.markdown(
        """
        <div class="panel" style="border-left:4px solid var(--danger); margin-bottom:18px;">
          <strong style="color:var(--danger);">Pre-Auction Exclusion</strong><br>
          Use this panel to remove players who haven't paid, withdrew, or are otherwise
          ineligible before the auction begins. Excluded players are skipped by the draw
          and are invisible to viewers. You can restore them at any time.
        </div>
        """,
        unsafe_allow_html=True,
    )

    # ── Tabs: Available pool | Excluded players ───────────────────────────
    tab_avail, tab_excl, tab_capt, tab_price = st.tabs(
    [
        "Available Pool",
        "Excluded Players",
        "Captains",
        "Edit Base Prices"
    ]
)

    with tab_avail:
        pool = rows(
            "SELECT id, name, category, base_price, status FROM players "
            "WHERE status IN ('AVAILABLE','ACTIVE') ORDER BY name"
        )
        if not pool:
            st.info("No available players in the pool.")
        else:
            st.caption(f"{len(pool)} player(s) currently in the auction pool.")
            search = st.text_input("Search by name", placeholder="Type to filter…", key="roster_search")
            filtered = [p for p in pool if not search or search.lower() in p["name"].lower()]

            for p in filtered:
                photo = find_player_image(p)
                col_photo, col_info, col_action = st.columns([1, 4, 2])
                with col_photo:
                    if photo:
                        st.image(str(photo), width=70)
                    else:
                        initials = "".join(w[:1] for w in p["name"].split()[:2]).upper()
                        st.markdown(
                            f'<div style="width:70px;height:70px;border-radius:8px;background:rgba(56,189,248,.15);'
                            f'display:flex;align-items:center;justify-content:center;'
                            f'font-size:22px;font-weight:900;border:1px solid var(--line);">{initials}</div>',
                            unsafe_allow_html=True,
                        )
                with col_info:
                    st.markdown(f"**{p['name']}**  `{p['category']}`  ·  Base: {rupees(p['base_price'])}")
                    st.caption(f"ID: {p['id']}  ·  Status: {p['status']}")
                with col_action:
                    reason = st.text_input(
                        "Reason", placeholder="e.g. not paid",
                        key=f"reason_{p['id']}", label_visibility="collapsed"
                    )
                    if st.button("Exclude", key=f"excl_{p['id']}", use_container_width=True):
                        exclude_player(p["id"], reason)
                        st.rerun()
                st.divider()

    with tab_excl:
        excl = rows(
            "SELECT id, name, category, base_price FROM players "
            "WHERE status = 'EXCLUDED' ORDER BY name"
        )
        if not excl:
            st.success("No players are currently excluded.")
        else:
            st.caption(f"{len(excl)} player(s) excluded from the auction.")
            for p in excl:
                photo = find_player_image(p)
                col_photo, col_info, col_action = st.columns([1, 4, 2])
                with col_photo:
                    if photo:
                        st.image(str(photo), width=70)
                    else:
                        initials = "".join(w[:1] for w in p["name"].split()[:2]).upper()
                        st.markdown(
                            f'<div style="width:70px;height:70px;border-radius:8px;background:rgba(249,115,22,.15);'
                            f'display:flex;align-items:center;justify-content:center;'
                            f'font-size:22px;font-weight:900;border:1px solid rgba(249,115,22,.3);">{initials}</div>',
                            unsafe_allow_html=True,
                        )
                with col_info:
                    st.markdown(f"**{p['name']}**  `{p['category']}`  ·  Base: {rupees(p['base_price'])}")
                    st.caption(f"ID: {p['id']}  ·  Status: ⛔ EXCLUDED")
                with col_action:
                    if st.button("Restore", key=f"restore_{p['id']}", use_container_width=True, type="primary"):
                        restore_player(p["id"])
                        st.rerun()
                st.divider()

    with tab_capt:

        captains = rows(
            """
            SELECT id,name,category
            FROM players
            WHERE status='CAPTAIN'
            ORDER BY name
            """
        )

        if not captains:
            st.info("No captains detected.")
        else:

            st.success(
                f"{len(captains)} captain(s) automatically excluded from auction."
            )

            st.dataframe(
                [
                    {
                        "ID": p["id"],
                        "Name": p["name"],
                        "Category": p["category"],
                    }
                    for p in captains
                ],
                hide_index=True,
                use_container_width=True,
            )
        
    with tab_price:
        st.markdown("Adjust the base price for individual players. Changes take effect immediately.")
        all_players = rows(
            "SELECT id, name, category, base_price, status FROM players ORDER BY name"
        )
        search2 = st.text_input("Search by name", placeholder="Type to filter…", key="price_search")
        filtered2 = [p for p in all_players if not search2 or search2.lower() in p["name"].lower()]

        # Bulk price update
        with st.expander("Set same base price for ALL players"):
            new_bulk = st.number_input(
                "New base price (all players)", min_value=0, value=5000, step=1000, key="bulk_price"
            )
            if st.button("Apply to All", type="primary", key="bulk_apply"):
                with closing(connect()) as con:
                    con.execute(
                        "UPDATE players SET base_price = ?, updated_at = ?",
                        (int(new_bulk), utc_now()),
                    )
                    con.commit()
                st.success(f"Base price updated to {rupees(new_bulk)} for all players.")
                st.rerun()

        st.divider()
        for p in filtered2:
            col_name, col_price, col_btn = st.columns([3, 2, 1])
            with col_name:
                status_badge = "⛔" if p["status"] == "EXCLUDED" else "✅" if p["status"] == "AVAILABLE" else "🔵"
                st.markdown(f"{status_badge} **{p['name']}** `{p['category']}`")
            with col_price:
                new_price = st.number_input(
                    "Price", min_value=0, value=int(p["base_price"]),
                    step=1000, key=f"price_{p['id']}", label_visibility="collapsed"
                )
            with col_btn:
                if st.button("Save", key=f"save_price_{p['id']}", use_container_width=True):
                    update_player_base_price(p["id"], int(new_price))
                    st.success(f"Updated {p['name']}")
                    st.rerun()


def summary_and_logs() -> None:
    st.title("Summary & Logs")
    metrics = summary_metrics()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Highest Bid", rupees(metrics["highest"]["sold_price"]) if metrics["highest"] else "Rs. 0")
    c2.metric("Sold", metrics["sold"])
    c3.metric("Unsold", metrics["unsold"])
    c4.metric("Remaining", metrics["remaining"])

    st.subheader("Player Pool")
    status_filter = st.multiselect(
        "Status filter",
        ["AVAILABLE", "ACTIVE", "SOLD", "UNSOLD", "EXCLUDED","CAPTAIN"],
        default=["AVAILABLE", "ACTIVE", "SOLD", "UNSOLD","CAPTAIN"],
    )
    placeholders = ",".join("?" for _ in status_filter) or "''"
    player_rows = rows(
        f"SELECT id, name, category, status, sold_team, sold_price, bid_count FROM players WHERE status IN ({placeholders}) ORDER BY name",
        tuple(status_filter),
    )
    st.dataframe(
        [
            {
                "ID": r["id"],
                "Name": r["name"],
                "Category": r["category"],
                "Status": r["status"],
                "Team": r["sold_team"] or "-",
                "Price": rupees(r["sold_price"]),
                "Bids": r["bid_count"],
            }
            for r in player_rows
        ],
        hide_index=True,
        use_container_width=True,
    )

    st.subheader("Audit Log")
    logs = rows("SELECT * FROM audit_log ORDER BY id DESC LIMIT 80")
    for log in logs:
        amount = f" - {rupees(log['amount'])}" if log["amount"] else ""
        st.markdown(
            f"<div class='log-line'><strong>{log['action']}</strong>{amount} "
            f"<span class='small-muted'>{log['created_at']}</span><br>{log['note'] or ''}</div>",
            unsafe_allow_html=True,
        )


def setup_sidebar(role: str) -> None:
    if HOME_LOGO_PATH.exists():
        logo_src = image_data_src(HOME_LOGO_PATH)
        st.sidebar.markdown(
            f'<div style="text-align: center;"><img class="sidebar-logo" src="{logo_src}"></div>',
            unsafe_allow_html=True
        )
    st.sidebar.title("Auction Portal")
    st.sidebar.caption(f"Role: {role}")
    if st.sidebar.button("Log out", use_container_width=True):
        st.session_state.clear()
        st.rerun()
    st.sidebar.divider()

    with closing(connect()) as con:
        player_count  = con.execute("SELECT COUNT(*) c FROM players WHERE status NOT IN ('EXCLUDED','CAPTAIN')").fetchone()["c"]
        excluded_count = con.execute("SELECT COUNT(*) c FROM players WHERE status = 'EXCLUDED'").fetchone()["c"]
        captain_count = con.execute(
    """
    SELECT COUNT(*) c
    FROM players
    WHERE status='CAPTAIN'
    """
).fetchone()["c"]

        available_count = con.execute("SELECT COUNT(*) c FROM players WHERE status = 'AVAILABLE'").fetchone()["c"]

    st.sidebar.metric("Players in Pool", player_count)
    st.sidebar.metric("Available", available_count)
    if excluded_count:
        st.sidebar.metric("Excluded (pre-auction)", excluded_count)
    if captain_count:
        st.sidebar.metric("Captains", captain_count)
    st.sidebar.metric("Base Price", rupees(get_min_base_price()))

    if role == "Admin":
        # Live read-only snapshot of each team's current configuration
        st.sidebar.divider()
        st.sidebar.subheader("Teams Snapshot")
        for t in standings():
            st.sidebar.markdown(
                f"**{t['Team Name']}**  \n"
                f"Purse: {rupees(t['Remaining Purse'])}  ·  "
                f"Squad: {t['Roster Count']}"
            )
        st.sidebar.caption("Edit teams in the Manage Teams tab.")


def login() -> None:
    st.markdown(CSS, unsafe_allow_html=True)
    st.markdown(asset_css(), unsafe_allow_html=True)
    render_header("LOGIN")

    # Check that passcodes are configured
    admin_code = _get_passcode("admin")
    viewer_code = _get_passcode("viewer")
    if not admin_code and not viewer_code:
        st.error(
            "⚠️ **Passcodes not configured.**  "
            "Set them in `.streamlit/secrets.toml` or via environment variables "
            "`AUCTION_ADMIN_PASSCODE` / `AUCTION_VIEWER_PASSCODE`."
        )

    left, right = st.columns([1, 1], gap="large")
    with left:
        if HOME_LOGO_PATH.exists():
            st.markdown('<div class="brand-logo">', unsafe_allow_html=True)
            st.image(str(HOME_LOGO_PATH), use_container_width=True)
            st.markdown("</div>", unsafe_allow_html=True)
        st.markdown(
            """
            <div class="panel">
              <h2>Real-Time Sports Auction Portal</h2>
              <p class="small-muted">
                Admins can run the draw, submit bids, and correct data. Viewers get a read-only
                live stage and standings that refresh automatically.
              </p>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with right:
        with st.form("login"):
            role = st.radio("Access level", ["Viewer", "Admin"], horizontal=True)
            passcode = st.text_input("Passcode", type="password")
            submitted = st.form_submit_button("Enter Auction", type="primary", use_container_width=True)
        if submitted:
            expected = _get_passcode(role)
            if expected and passcode == expected:
                st.session_state.role = role
                st.rerun()
            else:
                st.error("Invalid passcode.")


@st.fragment(run_every=2)
def render_viewer_stage_fragment() -> None:
    viewer_stage()


@st.fragment(run_every=2)
def render_team_leaderboards_fragment() -> None:
    team_leaderboards()


@st.fragment(run_every=2)
def render_summary_and_logs_fragment() -> None:
    summary_and_logs()


def bootstrap_data_if_needed() -> None:
    count = one("SELECT COUNT(*) c FROM players")
    if count and int(count["c"]) > 0:
        return
    if DEFAULT_WORKBOOK.exists():
        try:
            import_players(DEFAULT_WORKBOOK, base_price=10000, replace_existing=False)
        except Exception as exc:
            st.warning(f"Player import is pending. Install requirements and use Sync Excel Data. Error: {exc}")


def main() -> None:
    st.markdown(CSS, unsafe_allow_html=True)
    st.markdown(asset_css(), unsafe_allow_html=True)
    init_db()
    bootstrap_data_if_needed()
    mark_captains()

    role = st.session_state.get("role")
    if not role:
        login()
        return

    setup_sidebar(role)

    if role == "Admin":
        tabs = st.tabs(["Live Bid", "Team Leaderboards", "Manage Teams", "Auction Control", "Player Roster", "Summary & Logs"])
        with tabs[0]:
            admin_console()
        with tabs[1]:
            team_leaderboards()
        with tabs[2]:
            manage_teams_panel()
        with tabs[3]:
            auction_control_panel()
        with tabs[4]:
            player_roster_panel()
        with tabs[5]:
            summary_and_logs()
    else:
        tabs = st.tabs(["Live Stage", "Team Leaderboards", "Summary & Logs"])
        with tabs[0]:
            render_viewer_stage_fragment()
        with tabs[1]:
            render_team_leaderboards_fragment()
        with tabs[2]:
            render_summary_and_logs_fragment()


def launched_by_streamlit() -> bool:
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
    except Exception:
        return False
    return get_script_run_ctx() is not None


def run_with_streamlit_cli() -> None:
    from streamlit.web import cli as streamlit_cli

    sys.argv = [
        "streamlit",
        "run",
        str(Path(__file__).resolve()),
        "--server.port",
        "8501",
        "--server.headless",
        "true",
    ]
    raise SystemExit(streamlit_cli.main())


if __name__ == "__main__":
    if launched_by_streamlit():
        main()
    else:
        run_with_streamlit_cli()
