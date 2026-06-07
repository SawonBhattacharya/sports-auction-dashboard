-- ═══════════════════════════════════════════════════════════════
-- Auction Dashboard — Supabase PostgreSQL Schema
-- Run this in the Supabase SQL Editor to bootstrap the database.
-- The Streamlit app will also auto-create tables on first run,
-- but this file is provided for manual setup & reference.
-- ═══════════════════════════════════════════════════════════════

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

-- ── Seed default teams (edit these to match your tournament) ──
INSERT INTO teams (name, captain_name, logo_url, starting_purse, max_squad_size, min_roster_size, created_at)
VALUES
    ('Team Alpha',   'DRAGLEEOO',             '', 100000, 9, 9, NOW()::TEXT),
    ('Team Bravo',   'Ankit Jaiswal',         '', 100000, 9, 9, NOW()::TEXT),
    ('Team Charlie', 'Swapneel Chakraborty',  '', 100000, 9, 9, NOW()::TEXT),
    ('Team Delta',   'Sawon Bhattacharya',    '', 100000, 9, 9, NOW()::TEXT)
ON CONFLICT (name) DO NOTHING;

-- ── Set initial auction state ────────────────────────────────
INSERT INTO auction_state (key, value) VALUES ('auction_status', 'LIVE')
ON CONFLICT (key) DO NOTHING;
