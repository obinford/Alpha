-- RTM Signal confluence model table.
-- Stores high-confidence signals generated when multiple independent
-- betting systems agree on the same play.

CREATE TABLE IF NOT EXISTS rtm_signals (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    game_id         TEXT NOT NULL,
    sport           TEXT NOT NULL,
    market_type     TEXT NOT NULL,
    side            TEXT NOT NULL,
    player_name     TEXT,
    prop_line       NUMERIC,
    sportsbook      TEXT NOT NULL,
    book_odds       NUMERIC NOT NULL,
    signal_strength NUMERIC NOT NULL,
    star_rating     INTEGER NOT NULL,
    ev_score        NUMERIC NOT NULL,
    steam_score     NUMERIC NOT NULL,
    projection_score NUMERIC,
    consensus_score NUMERIC NOT NULL,
    fair_odds       NUMERIC,
    edge_percentage NUMERIC NOT NULL,
    kelly_size      NUMERIC,
    status          TEXT NOT NULL DEFAULT 'active',
    result          TEXT,
    profit_loss     NUMERIC,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    graded_at       TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_rtm_signals_game_id ON rtm_signals (game_id);
CREATE INDEX IF NOT EXISTS idx_rtm_signals_created_at ON rtm_signals (created_at);
CREATE INDEX IF NOT EXISTS idx_rtm_signals_strength ON rtm_signals (signal_strength);
CREATE INDEX IF NOT EXISTS idx_rtm_signals_star_rating ON rtm_signals (star_rating);
CREATE INDEX IF NOT EXISTS idx_rtm_signals_status ON rtm_signals (status);
