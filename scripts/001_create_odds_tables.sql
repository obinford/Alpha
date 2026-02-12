-- RTM Picks Platform: Odds Pipeline Schema
-- Migration 001: Create core tables for odds tracking and EV analysis

-- 1. Games
CREATE TABLE IF NOT EXISTS games (
    game_id     TEXT PRIMARY KEY,
    sport       TEXT NOT NULL,
    home_team   TEXT NOT NULL,
    away_team   TEXT NOT NULL,
    start_time  TIMESTAMPTZ NOT NULL,
    status      TEXT NOT NULL DEFAULT 'upcoming',
    home_score  INTEGER,
    away_score  INTEGER,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_games_sport ON games (sport);
CREATE INDEX idx_games_start_time ON games (start_time);
CREATE INDEX idx_games_status ON games (status);

-- 2. Odds snapshots (time-series of odds from every sportsbook)
CREATE TABLE IF NOT EXISTS odds_snapshots (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    game_id         TEXT NOT NULL REFERENCES games (game_id),
    sportsbook      TEXT NOT NULL,
    market_type     TEXT NOT NULL,
    home_odds       NUMERIC NOT NULL,
    away_odds       NUMERIC NOT NULL,
    spread_value    NUMERIC,
    total_value     NUMERIC,
    timestamp       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_odds_snapshots_game_id ON odds_snapshots (game_id);
CREATE INDEX idx_odds_snapshots_timestamp ON odds_snapshots (timestamp);

-- 3. True lines (devigged sharp-book probabilities)
CREATE TABLE IF NOT EXISTS true_lines (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    game_id         TEXT NOT NULL REFERENCES games (game_id),
    market_type     TEXT NOT NULL,
    true_home_prob  NUMERIC NOT NULL,
    true_away_prob  NUMERIC NOT NULL,
    sharp_book      TEXT NOT NULL,
    no_vig_line     NUMERIC,
    timestamp       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_true_lines_game_id ON true_lines (game_id);

-- 4. EV opportunities (actionable +EV bets)
CREATE TABLE IF NOT EXISTS ev_opportunities (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    game_id             TEXT NOT NULL REFERENCES games (game_id),
    sportsbook          TEXT NOT NULL,
    market_type         TEXT NOT NULL,
    side                TEXT NOT NULL,
    book_odds           NUMERIC NOT NULL,
    book_implied_prob   NUMERIC NOT NULL,
    true_prob           NUMERIC NOT NULL,
    ev_percentage       NUMERIC NOT NULL,
    kelly_fraction      NUMERIC NOT NULL,
    recommended_units   NUMERIC NOT NULL,
    timestamp           TIMESTAMPTZ NOT NULL DEFAULT now(),
    status              TEXT NOT NULL DEFAULT 'open'
);

CREATE INDEX idx_ev_opportunities_status ON ev_opportunities (status);
CREATE INDEX idx_ev_opportunities_game_id ON ev_opportunities (game_id);
CREATE INDEX idx_ev_opportunities_timestamp ON ev_opportunities (timestamp);

-- 5. Bet results (graded outcomes for tracking performance)
CREATE TABLE IF NOT EXISTS bet_results (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ev_opportunity_id   BIGINT NOT NULL REFERENCES ev_opportunities (id),
    result              TEXT NOT NULL,
    closing_line        NUMERIC,
    closing_line_value  NUMERIC,
    profit_loss         NUMERIC,
    graded_at           TIMESTAMPTZ
);

CREATE INDEX idx_bet_results_ev_opportunity_id ON bet_results (ev_opportunity_id);
