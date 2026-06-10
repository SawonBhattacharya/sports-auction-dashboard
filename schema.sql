-- ═══════════════════════════════════════════════════════════════
-- LCL Auction 2026 — Unified Database Schema
-- Compatible with both SQLite and Supabase PostgreSQL.
-- ═══════════════════════════════════════════════════════════════

-- 1. Players Table
CREATE TABLE IF NOT EXISTS players (
    id                  TEXT PRIMARY KEY,
    name                TEXT NOT NULL,
    seeding             TEXT NOT NULL,               -- Icon, Premium, Rising, Impact
    base_price          BIGINT NOT NULL,             -- Raw INR (e.g. 10000000)
    matches             DOUBLE PRECISION,
    innings             DOUBLE PRECISION,
    runs                DOUBLE PRECISION,
    average             DOUBLE PRECISION,
    strike_rate         DOUBLE PRECISION,
    best_score          TEXT,
    wickets             DOUBLE PRECISION,
    economy             DOUBLE PRECISION,
    fielding_dismissals DOUBLE PRECISION,
    batting             TEXT,
    bowling             TEXT,
    bowling_preference  TEXT,
    profile_url         TEXT,
    status              TEXT NOT NULL DEFAULT 'AVAILABLE', -- AVAILABLE, SOLD, UNSOLD
    sold_team           TEXT,
    sold_price          BIGINT,
    bid_count           INTEGER NOT NULL DEFAULT 0,
    picked_at           TEXT,
    sold_at             TEXT,
    is_marquee          BOOLEAN DEFAULT FALSE,       -- Set during pre-auction draft
    marquee_nominator   TEXT,                        -- Captain who selected this marquee
    updated_at          TEXT NOT NULL
);

-- 2. Teams Table
CREATE TABLE IF NOT EXISTS teams (
    name            TEXT PRIMARY KEY,
    captain_name    TEXT NOT NULL,
    logo_url        TEXT,
    starting_purse  BIGINT NOT NULL,
    purse_remaining BIGINT NOT NULL,
    max_squad_size  INTEGER NOT NULL DEFAULT 10,     -- Can be toggled to 11 by Admin
    rtm_used        BOOLEAN NOT NULL DEFAULT FALSE,
    joker_type      TEXT,                            -- FORCE_NOMINATION or LAST_BID (lottery)
    created_at      TEXT NOT NULL
);

-- 3. Pre-Auction Secret Selections
CREATE TABLE IF NOT EXISTS pre_auction_bets (
    id              SERIAL PRIMARY KEY, -- SQLite auto_increment. Postgres uses SERIAL (handled in app)
    captain_name    TEXT NOT NULL,
    bet_type        TEXT NOT NULL,                   -- 'SURPRISE' or 'PREDICTION'
    target_captain  TEXT,                            -- For predictions: who is buying
    target_player_id TEXT NOT NULL,                  -- Which player they are buying or surprise player
    created_at      TEXT NOT NULL,
    UNIQUE(captain_name, bet_type, target_captain)
);

-- 4. Silent Bids for Last Bid Joker
CREATE TABLE IF NOT EXISTS silent_bids (
    id              SERIAL PRIMARY KEY,
    player_id       TEXT NOT NULL,
    captain_name    TEXT NOT NULL,
    bid_amount      BIGINT NOT NULL,
    submitted_at    TEXT NOT NULL,
    UNIQUE(player_id, captain_name)
);

-- 5. Live Bid State (Tracks current bidder, phase, and Joker flows)
CREATE TABLE IF NOT EXISTS live_bid_state (
    player_id               TEXT PRIMARY KEY,
    current_bid             BIGINT NOT NULL DEFAULT 0,
    current_bidder          TEXT,                    -- Team Name
    bid_count               INTEGER NOT NULL DEFAULT 0,
    phase                   TEXT NOT NULL DEFAULT 'PRE_AUCTION', -- PRE_AUCTION, MARQUEE_AUCTION, MAIN_AUCTION
    rtm_captain             TEXT,
    revised_bid             BIGINT,
    last_bid_joker_captain  TEXT,
    updated_at              TEXT NOT NULL
);

-- 6. Auction State Table
CREATE TABLE IF NOT EXISTS auction_state (
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- 7. Audit Log Table
CREATE TABLE IF NOT EXISTS audit_log (
    id          SERIAL PRIMARY KEY,
    action      TEXT NOT NULL,                       -- BID, SOLD, UNSOLD, JOKER, SYNC, etc.
    player_id   TEXT,
    team_name   TEXT,
    amount      BIGINT,
    bid_count   INTEGER,
    note        TEXT,
    created_at  TEXT NOT NULL
);

-- Seed Initial Teams (starting purse ₹25 Crore = 250000000)
INSERT INTO teams (name, captain_name, logo_url, starting_purse, purse_remaining, max_squad_size, created_at)
VALUES
    ('AMD SENA',   'Dragleeoo',    '', 250000000, 250000000, 10, '2026-06-08T12:00:00Z'),
    ('PITCH PALS',   'Harshit Agarwal',  '', 250000000, 250000000, 10, '2026-06-08T12:00:00Z'),
    ('INVICTUS XI', 'Swapneel',     '', 250000000, 250000000, 10, '2026-06-08T12:00:00Z'),
    ('SHINING KNIGHTS',   'Sawon',        '', 250000000, 250000000, 10, '2026-06-08T12:00:00Z')
ON CONFLICT (name) DO UPDATE SET
    captain_name = EXCLUDED.captain_name,
    starting_purse = EXCLUDED.starting_purse,
    purse_remaining = EXCLUDED.purse_remaining;

-- Seed Initial Status
INSERT INTO auction_state (key, value)
VALUES ('auction_status', 'PRE_AUCTION')
ON CONFLICT (key) DO NOTHING;
