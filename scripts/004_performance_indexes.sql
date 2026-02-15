-- RTM Picks Platform: Performance Tracking Indexes
-- Migration 004: Add indexes for performance queries on bet_results

-- Index on graded_at for date-range queries.
CREATE INDEX IF NOT EXISTS idx_bet_results_graded_at ON bet_results (graded_at);

-- Index on result for filtering wins/losses.
CREATE INDEX IF NOT EXISTS idx_bet_results_result ON bet_results (result);
