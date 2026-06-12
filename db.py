import os
import re
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import streamlit as st
from config import PASSCODES

# Enable optional psycopg2 for PostgreSQL (Supabase)
try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    from psycopg2.pool import ThreadedConnectionPool
    _HAS_PG = True
except ImportError:
    _HAS_PG = False

ROOT = Path(__file__).parent
DB_PATH = ROOT / "auction.db"
_NAMED_PARAM_RE = re.compile(r":([A-Za-z_]\w*)")

def _get_db_url() -> str | None:
    try:
        url = st.secrets.get("database", {}).get("url")
        if url:
            return str(url)
    except Exception:
        pass
    return os.getenv("DATABASE_URL") or None

def _use_pg() -> bool:
    return _HAS_PG and bool(_get_db_url())

class _DBConn:
    """Thin wrapper shim for SQLite/PostgreSQL compatibility."""
    def __init__(self, raw_connection: Any, *, is_pg: bool, is_pooled: bool = False):
        self._raw = raw_connection
        self._pg = is_pg
        self._is_pooled = is_pooled
        self._cur = raw_connection.cursor() if is_pg else None

    @staticmethod
    def _convert(sql: str, is_pg: bool) -> str:
        if not is_pg:
            # SQLite uses :name or ? as is
            return sql
        # :named -> %(named)s (run before ? replacement)
        sql = _NAMED_PARAM_RE.sub(r"%(\1)s", sql)
        # ? -> %s
        sql = sql.replace("?", "%s")
        return sql

    def execute(self, sql: str, params: Any = None) -> Any:
        sql = self._convert(sql, self._pg)
        if self._pg:
            self._cur.execute(sql, params or ())
            return self._cur
        if params:
            # sqlite3 execute takes parameters as tuple or dict
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
            # PostgreSQL does not support AUTOINCREMENT, convert to SERIAL
            sql = re.sub(r"INTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT", "SERIAL PRIMARY KEY", sql, flags=re.IGNORECASE)
            with self._raw.cursor() as cur:
                cur.execute(sql)
        else:
            self._raw.executescript(sql)

    def commit(self) -> None:
        self._raw.commit()

    def close(self) -> None:
        if self._cur:
            try:
                self._cur.close()
            except Exception:
                pass
                
        if self._is_pooled and self._pg:
            pool = get_pg_pool()
            if pool:
                try:
                    self._raw.rollback() # Clear any pending tx state
                    pool.putconn(self._raw)
                except Exception:
                    pass
        else:
            try:
                self._raw.close()
            except Exception:
                pass

    def __enter__(self) -> "_DBConn":
        return self

    def __exit__(self, *exc: Any) -> bool:
        self.close()
        return False

@st.cache_resource(show_spinner=False)
def get_pg_pool():
    url = _get_db_url() or ""
    if "[YOUR-PASSWORD]" in url or "[YOUR_PASSWORD]" in url or "<password>" in url:
        st.error("❌ Database Connection URL placeholder not replaced.")
        st.stop()
    try:
        return ThreadedConnectionPool(1, 15, url, cursor_factory=RealDictCursor)
    except Exception as e:
        st.error(f"❌ Cloud database connection failed: {e}")
        st.stop()

def connect() -> _DBConn:
    """Return a _DBConn wrapping either psycopg2 or sqlite3."""
    if _use_pg():
        pool = get_pg_pool()
        try:
            raw = pool.getconn()
            raw.autocommit = True
            return _DBConn(raw, is_pg=True, is_pooled=True)
        except Exception as e:
            st.error(f"❌ Cloud database connection failed: {e}")
            st.stop()
    
    # SQLite fallback
    raw = sqlite3.connect(DB_PATH, check_same_thread=False)
    raw.row_factory = sqlite3.Row
    raw.execute("PRAGMA foreign_keys = ON")
    raw.execute("PRAGMA journal_mode = WAL")
    return _DBConn(raw, is_pg=False)

def init_db(force: bool = False) -> None:
    """Initializes the database schema if it hasn't been set up yet."""
    with closing(connect()) as con:
        # Check if players table exists
        exists = False
        try:
            if con._pg:
                exists = con.execute("SELECT 1 FROM players LIMIT 1").fetchone()
            else:
                exists = con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='players'").fetchone()
        except Exception:
            if getattr(con, '_pg', False):
                try: con._raw.rollback()
                except: pass

        if force:
            for table in ["audit_log", "auction_state", "live_bid_state", "silent_bids", "pre_auction_bets", "teams", "players"]:
                try:
                    if getattr(con, '_pg', False):
                        con.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
                    else:
                        con.execute(f"DROP TABLE IF EXISTS {table}")
                except Exception:
                    if getattr(con, '_pg', False):
                        try: con._raw.rollback()
                        except: pass
            con.commit()

        if not exists or force:
            # Run schema.sql
            schema_file = ROOT / "schema.sql"
            if schema_file.exists():
                sql = schema_file.read_text(encoding="utf-8")
                con.executescript(sql)
                con.commit()

        _ensure_player_detail_columns(con)
        con.commit()

def _ensure_player_detail_columns(con: _DBConn) -> None:
    """Add player detail columns to existing databases created before the latest workbook."""
    detail_columns = {
        "batting": "TEXT",
        "bowling": "TEXT",
        "bowling_preference": "TEXT",
        "fielding_dismissals": "TEXT",
    }
    if con._pg:
        for column, column_type in detail_columns.items():
            con.execute(f"ALTER TABLE players ADD COLUMN IF NOT EXISTS {column} {column_type}")
        return

    try:
        existing = {row["name"] for row in con.execute("PRAGMA table_info(players)").fetchall()}
    except Exception:
        return
    for column, column_type in detail_columns.items():
        if column not in existing:
            con.execute(f"ALTER TABLE players ADD COLUMN {column} {column_type}")

def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

def get_state(con: _DBConn, key: str, default: str | None = None) -> str | None:
    row = con.execute("SELECT value FROM auction_state WHERE key = ?", (key,)).fetchone()
    # sqlite Row is dict-like, psycopg2 row is RealDictCursor (dict)
    if row:
        return row[0] if isinstance(row, tuple) else row["value"]
    return default

def set_state(con: _DBConn, key: str, value: str | None) -> None:
    con.execute(
        "INSERT INTO auction_state(key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )

def rows(query: str, params: tuple[Any, ...] = ()) -> list[Any]:
    with closing(connect()) as con:
        res = con.execute(query, params).fetchall()
        # Convert sqlite Row objects to dicts for unified representation
        if not con._pg:
            return [dict(r) for r in res]
        return res

def one(query: str, params: tuple[Any, ...] = ()) -> Any | None:
    with closing(connect()) as con:
        res = con.execute(query, params).fetchone()
        if res and not con._pg:
            return dict(res)
        return res

def execute(query: str, params: tuple[Any, ...] = ()) -> None:
    with closing(connect()) as con:
        con.execute(query, params)
        con.commit()

def execute_transaction(queries_with_params: list[tuple[str, tuple[Any, ...]]]) -> None:
    """Executes multiple queries in a single connection transaction."""
    with closing(connect()) as con:
        if con._pg:
            con._raw.autocommit = False
            try:
                for sql, params in queries_with_params:
                    con.execute(sql, params)
                con._raw.commit()
            except Exception as e:
                con._raw.rollback()
                raise e
            finally:
                con._raw.autocommit = True
        else:
            try:
                for sql, params in queries_with_params:
                    con.execute(sql, params)
                con.commit()
            except Exception as e:
                con._raw.rollback()
                raise e

def clean_text(value: Any) -> str:
    if value is None or str(value).lower() == "nan":
        return ""
    return str(value).strip()

def number_or_none(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

def finalize_sale(
    player_id: str,
    sold_team: str,
    sold_price: int,
    purse_deduction: int,
    bonus_amount: int,
    tax_deductions: list[dict],  # list of {"team_name": str, "amount": int}
    log_note: str,
    clear_silent_bids: bool = False,
) -> bool:
    """
    WHY: Wraps the entire SOLD flow — player status update, purse deduction, bonus credit,
    tax penalties, audit log — in a single atomic DB transaction. This prevents the race
    condition where two simultaneous clicks (Admin "SOLD" + Captain "RTM Match") both read
    status='AVAILABLE' before either write completes, causing a double-sale.

    Returns True if the sale was committed, False if the player was already sold
    (another transaction won the race).

    JOKER CARD SAFETY: Bonus and tax calculations happen inside the same transaction,
    so a Joker card activation that happens between the bid and the sale cannot corrupt
    the purse calculation. The purse math is:
        new_purse = current_purse - sold_price + bonus - tax
    All three deltas are applied atomically.

    RTM CARD SAFETY: rtm_used is read BEFORE this function is called (in rules_engine).
    The mark_rtm_used UPDATE is NOT inside this transaction intentionally — it happens
    immediately when the RTM+ button is pressed (in captain.py), not at sale time.
    This means rtm_used can never be double-spent: the card is burned the moment it
    is triggered, not when the RTM decision resolves.
    """
    from datetime import datetime, timezone

    def utc() -> str:
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    with closing(connect()) as con:
        if con._pg:
            con._raw.autocommit = False
        try:
            # ── Step 1: Atomic guard — check-and-set player status ──
            # Using a conditional UPDATE: it only updates if status is NOT already SOLD.
            # We then verify exactly 1 row was affected. If 0, another transaction won.
            if con._pg:
                cur = con._raw.cursor()
                cur.execute(
                    "UPDATE players SET status='SOLD', sold_team=%s, sold_price=%s, sold_at=%s, updated_at=%s "
                    "WHERE id=%s AND status != 'SOLD'",
                    (sold_team, sold_price, utc(), utc(), player_id)
                )
                rows_affected = cur.rowcount
            else:
                cur = con._raw.execute(
                    "UPDATE players SET status='SOLD', sold_team=?, sold_price=?, sold_at=?, updated_at=? "
                    "WHERE id=? AND status != 'SOLD'",
                    (sold_team, sold_price, utc(), utc(), player_id)
                )
                rows_affected = cur.rowcount

            if rows_affected == 0:
                # Another transaction already sold this player — abort safely
                if con._pg:
                    con._raw.rollback()
                    con._raw.autocommit = True
                return False

            # ── Step 2: Purse deduction for buying team ──
            # We fetch the current purse INSIDE the transaction to avoid dirty reads.
            if con._pg:
                cur.execute("SELECT purse_remaining FROM teams WHERE name=%s FOR UPDATE", (sold_team,))
                team_row = cur.fetchone()
                new_purse = team_row["purse_remaining"] - purse_deduction + bonus_amount
                cur.execute(
                    "UPDATE teams SET purse_remaining=%s WHERE name=%s",
                    (max(0, new_purse), sold_team)
                )
            else:
                team_row = con._raw.execute(
                    "SELECT purse_remaining FROM teams WHERE name=?", (sold_team,)
                ).fetchone()
                new_purse = dict(team_row)["purse_remaining"] - purse_deduction + bonus_amount
                con._raw.execute(
                    "UPDATE teams SET purse_remaining=? WHERE name=?",
                    (max(0, new_purse), sold_team)
                )

            # ── Step 3: Apply prediction tax deductions ──
            # Each tax hits the BUYING team's purse (already computed above).
            # We loop here in case multiple predictors triggered taxes on the same player.
            # SAFETY: tax_deductions list is computed by rules_engine BEFORE this call,
            # so no DB reads happen inside this loop — no new connections opened.
            for tax in tax_deductions:
                tax_team = tax["team_name"]
                tax_amt = tax["amount"]
                if con._pg:
                    cur.execute("SELECT purse_remaining FROM teams WHERE name=%s FOR UPDATE", (tax_team,))
                    t_row = cur.fetchone()
                    cur.execute(
                        "UPDATE teams SET purse_remaining=%s WHERE name=%s",
                        (max(0, t_row["purse_remaining"] - tax_amt), tax_team)
                    )
                    cur.execute(
                        "INSERT INTO audit_log (action, player_id, team_name, amount, note, created_at) "
                        "VALUES (%s,%s,%s,%s,%s,%s)",
                        ("TAX", player_id, tax_team, tax_amt, tax["note"], utc())
                    )
                else:
                    t_row = con._raw.execute(
                        "SELECT purse_remaining FROM teams WHERE name=?", (tax_team,)
                    ).fetchone()
                    con._raw.execute(
                        "UPDATE teams SET purse_remaining=? WHERE name=?",
                        (max(0, dict(t_row)["purse_remaining"] - tax_amt), tax_team)
                    )
                    con._raw.execute(
                        "INSERT INTO audit_log (action, player_id, team_name, amount, note, created_at) "
                        "VALUES (?,?,?,?,?,?)",
                        ("TAX", player_id, tax_team, tax_amt, tax["note"], utc())
                    )

            # ── Step 4: Bonus audit log (if bonus was applied) ──
            if bonus_amount > 0:
                from config import format_inr
                bonus_note = f"Surprise Player Bonus: +{format_inr(bonus_amount)}"
                if con._pg:
                    cur.execute(
                        "INSERT INTO audit_log (action, player_id, team_name, amount, note, created_at) "
                        "VALUES (%s,%s,%s,%s,%s,%s)",
                        ("BONUS", player_id, sold_team, bonus_amount, bonus_note, utc())
                    )
                else:
                    con._raw.execute(
                        "INSERT INTO audit_log (action, player_id, team_name, amount, note, created_at) "
                        "VALUES (?,?,?,?,?,?)",
                        ("BONUS", player_id, sold_team, bonus_amount, bonus_note, utc())
                    )

            # ── Step 5: Main SOLD audit log ──
            if con._pg:
                cur.execute(
                    "INSERT INTO audit_log (action, player_id, team_name, amount, note, created_at) "
                    "VALUES (%s,%s,%s,%s,%s,%s)",
                    ("SOLD", player_id, sold_team, sold_price, log_note, utc())
                )
            else:
                con._raw.execute(
                    "INSERT INTO audit_log (action, player_id, team_name, amount, note, created_at) "
                    "VALUES (?,?,?,?,?,?)",
                    ("SOLD", player_id, sold_team, sold_price, log_note, utc())
                )

            # ── Step 6: Clear silent bids for this player (Last Bid Joker cleanup) ──
            if clear_silent_bids:
                if con._pg:
                    cur.execute("DELETE FROM silent_bids WHERE player_id=%s", (player_id,))
                else:
                    con._raw.execute("DELETE FROM silent_bids WHERE player_id=?", (player_id,))

            # ── Commit everything ──
            if con._pg:
                con._raw.commit()
                con._raw.autocommit = True
            else:
                con._raw.commit()

            return True

        except Exception as e:
            if con._pg:
                try:
                    con._raw.rollback()
                    con._raw.autocommit = True
                except Exception:
                    pass
            raise e