-- RTM Intelligence Layers — database tables
-- Run this migration after 005_rtm_signal.sql

-- ─── Book Reaction Times ───────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS book_reaction_times (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    game_id         TEXT NOT NULL,
    sport           TEXT NOT NULL,
    market_type     TEXT NOT NULL,
    side            TEXT NOT NULL,
    sharp_book      TEXT NOT NULL,
    sharp_move_time TIMESTAMPTZ NOT NULL,
    soft_book       TEXT NOT NULL,
    soft_move_time  TIMESTAMPTZ,
    reaction_seconds NUMERIC,
    was_stale       BOOLEAN DEFAULT false,
    edge_at_stale   NUMERIC,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_book_reactions_soft_book
    ON book_reaction_times (soft_book);
CREATE INDEX IF NOT EXISTS idx_book_reactions_sport
    ON book_reaction_times (sport);
CREATE INDEX IF NOT EXISTS idx_book_reactions_game
    ON book_reaction_times (game_id);


-- ─── Stale Line Alerts ─────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS stale_line_alerts (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    game_id         TEXT NOT NULL,
    sport           TEXT NOT NULL,
    market_type     TEXT NOT NULL,
    side            TEXT NOT NULL,
    stale_book      TEXT NOT NULL,
    stale_odds      NUMERIC NOT NULL,
    consensus_odds  NUMERIC NOT NULL,
    edge_percentage NUMERIC NOT NULL,
    stale_type      TEXT NOT NULL,
    detected_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at     TIMESTAMPTZ,
    status          TEXT NOT NULL DEFAULT 'active',
    bet_result      TEXT
);

CREATE INDEX IF NOT EXISTS idx_stale_lines_status
    ON stale_line_alerts (status);
CREATE INDEX IF NOT EXISTS idx_stale_lines_detected
    ON stale_line_alerts (detected_at);
CREATE INDEX IF NOT EXISTS idx_stale_lines_book
    ON stale_line_alerts (stale_book);


-- ─── Line Lifecycle ────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS line_lifecycle (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    game_id         TEXT NOT NULL,
    sport           TEXT NOT NULL,
    market_type     TEXT NOT NULL,
    side            TEXT NOT NULL,
    sportsbook      TEXT NOT NULL,
    first_seen_at   TIMESTAMPTZ NOT NULL,
    first_move_at   TIMESTAMPTZ,
    biggest_move_at TIMESTAMPTZ,
    stabilized_at   TIMESTAMPTZ,
    opening_odds    NUMERIC NOT NULL,
    closing_odds    NUMERIC,
    peak_edge       NUMERIC,
    peak_edge_time  TIMESTAMPTZ,
    game_start_time TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_line_lifecycle_sport
    ON line_lifecycle (sport);
CREATE INDEX IF NOT EXISTS idx_line_lifecycle_game_start
    ON line_lifecycle (game_start_time);
CREATE INDEX IF NOT EXISTS idx_line_lifecycle_game
    ON line_lifecycle (game_id);


-- ─── Add intelligence columns to rtm_signals ─────────────────────────────

ALTER TABLE rtm_signals
    ADD COLUMN IF NOT EXISTS intelligence_score NUMERIC DEFAULT 0;

ALTER TABLE rtm_signals
    ADD COLUMN IF NOT EXISTS intelligence_context JSONB;
