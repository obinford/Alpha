-- Pinnacle Odds History — stores opening, closing, and current Pinnacle lines
-- for every game.  Critical for CLV (Closing Line Value) analysis.
--
-- snapshot_type values:
--   "opening"  — First Pinnacle line we ever see for this game+market. Stored once, never overwritten.
--   "closing"  — Updated every scan cycle. Frozen when game tips off. Becomes the true closing line.
--   "current"  — Same as closing, overwritten each cycle for real-time display.

CREATE TABLE IF NOT EXISTS pinnacle_odds_history (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    game_id TEXT NOT NULL,
    sport TEXT NOT NULL,
    home_team TEXT NOT NULL,
    away_team TEXT NOT NULL,
    commence_time TIMESTAMPTZ,
    market_type TEXT NOT NULL,          -- h2h, spreads, totals
    line_value REAL,                    -- spread number or total number (NULL for h2h)
    home_odds INTEGER,                  -- home ML or home spread odds
    away_odds INTEGER,                  -- away ML or away spread odds
    over_odds INTEGER,                  -- totals only
    under_odds INTEGER,                 -- totals only
    home_prob REAL,                     -- devigged home/over probability
    away_prob REAL,                     -- devigged away/under probability
    snapshot_type TEXT NOT NULL DEFAULT 'current',  -- opening, closing, current
    captured_at TIMESTAMPTZ DEFAULT NOW(),
    snapshot_date DATE NOT NULL,
    UNIQUE(game_id, market_type, snapshot_type, snapshot_date)
);

CREATE INDEX IF NOT EXISTS idx_pin_hist_game ON pinnacle_odds_history(game_id);
CREATE INDEX IF NOT EXISTS idx_pin_hist_date ON pinnacle_odds_history(snapshot_date DESC);
CREATE INDEX IF NOT EXISTS idx_pin_hist_type ON pinnacle_odds_history(snapshot_type);
