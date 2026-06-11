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