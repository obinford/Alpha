-- RTM Picks Platform: Sharp Money Tracking Schema
-- Migration 002: Line movements + steam alerts

-- 6. Line movements (full odds history per bookmaker/game/market/side)
CREATE TABLE IF NOT EXISTS line_movements (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    game_id         TEXT NOT NULL REFERENCES games (game_id),
    sport           TEXT NOT NULL,
    bookmaker       TEXT NOT NULL,
    market_type     TEXT NOT NULL,
    side            TEXT NOT NULL,
    odds            NUMERIC NOT NULL,
    previous_odds   NUMERIC,
    odds_change     NUMERIC,
    timestamp       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_line_movements_game_id ON line_movements (game_id);
CREATE INDEX idx_line_movements_timestamp ON line_movements (timestamp);
CREATE INDEX idx_line_movements_lookup ON line_movements (game_id, bookmaker, market_type, side);
CREATE INDEX idx_line_movements_change ON line_movements (odds_change);

-- 7. Steam alerts (3+ books moving same direction = sharp action)
CREATE TABLE IF NOT EXISTS steam_alerts (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    game_id         TEXT NOT NULL REFERENCES games (game_id),
    sport           TEXT NOT NULL,
    market_type     TEXT NOT NULL,
    side            TEXT NOT NULL,
    direction       TEXT NOT NULL,
    books_moved     JSONB NOT NULL DEFAULT '[]',
    magnitude       NUMERIC NOT NULL,
    first_move_time TIMESTAMPTZ NOT NULL,
    detected_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    status          TEXT NOT NULL DEFAULT 'active'
);

CREATE INDEX idx_steam_alerts_game_id ON steam_alerts (game_id);
CREATE INDEX idx_steam_alerts_detected_at ON steam_alerts (detected_at);
CREATE INDEX idx_steam_alerts_status ON steam_alerts (status);
