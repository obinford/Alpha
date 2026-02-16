-- Add bet_amount column to rtm_signals for flat-bet tracking.
-- All signals use $100 flat bets (no Kelly sizing for signals).

ALTER TABLE rtm_signals ADD COLUMN IF NOT EXISTS bet_amount NUMERIC NOT NULL DEFAULT 100;
