-- RTM Picks Platform: CLV Tracking Schema
-- Migration 003: Closing Line Value records

-- 8. CLV records (compare opening bet odds vs closing odds)
CREATE TABLE IF NOT EXISTS clv_records (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    game_id             TEXT NOT NULL REFERENCES games (game_id),
    sport               TEXT NOT NULL,
    sportsbook          TEXT NOT NULL,
    market_type         TEXT NOT NULL,
    side                TEXT NOT NULL,
    bet_odds            NUMERIC NOT NULL,           -- odds when bet was placed
    bet_true_prob       NUMERIC NOT NULL,            -- devigged prob at bet time
    closing_odds        NUMERIC,                     -- odds at game start
    closing_true_prob   NUMERIC,                     -- devigged prob at close
    clv_percentage      NUMERIC,                     -- CLV = (closing_prob - bet_prob) / bet_prob * 100
    ev_at_bet           NUMERIC NOT NULL,            -- EV% when bet was placed
    bet_timestamp       TIMESTAMPTZ NOT NULL,        -- when the EV opportunity was found
    closing_timestamp   TIMESTAMPTZ,                 -- when closing odds were captured
    status              TEXT NOT NULL DEFAULT 'open', -- open, closed, expired
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_clv_records_game_id ON clv_records (game_id);
CREATE INDEX idx_clv_records_sport ON clv_records (sport);
CREATE INDEX idx_clv_records_status ON clv_records (status);
CREATE INDEX idx_clv_records_created_at ON clv_records (created_at);
CREATE INDEX idx_clv_records_clv ON clv_records (clv_percentage);
