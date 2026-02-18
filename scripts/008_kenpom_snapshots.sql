-- KenPom snapshot storage: daily KenPom projections alongside Pinnacle odds.
-- Tracks projection accuracy over time for the KP Edge Finder page.

CREATE TABLE IF NOT EXISTS kenpom_snapshots (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    snapshot_date DATE NOT NULL,
    game_id TEXT NOT NULL,
    sport TEXT DEFAULT 'basketball_ncaab',
    home_team TEXT NOT NULL,
    away_team TEXT NOT NULL,
    commence_time TIMESTAMPTZ,
    kp_home_score REAL,
    kp_away_score REAL,
    kp_home_win_prob REAL,
    kp_projected_total REAL,
    kp_projected_spread REAL,
    pinnacle_spread_home REAL,
    pinnacle_total REAL,
    pinnacle_home_ml INTEGER,
    pinnacle_away_ml INTEGER,
    pinnacle_home_implied_prob REAL,
    spread_edge REAL,
    total_edge REAL,
    ml_edge REAL,
    result_home_score INTEGER,
    result_away_score INTEGER,
    result_spread_correct BOOLEAN,
    result_total_correct BOOLEAN,
    result_ml_correct BOOLEAN,
    graded BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(snapshot_date, game_id)
);

CREATE INDEX IF NOT EXISTS idx_kenpom_snapshots_date ON kenpom_snapshots(snapshot_date DESC);
CREATE INDEX IF NOT EXISTS idx_kenpom_snapshots_game ON kenpom_snapshots(game_id);
CREATE INDEX IF NOT EXISTS idx_kenpom_snapshots_graded ON kenpom_snapshots(graded)
