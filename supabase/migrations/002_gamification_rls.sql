-- Life Tycoon: Gamification Row-Level Security
-- Migration 002: RLS policies for the gamification schema (migration 001)

-- ── users ──
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS users_select_own ON users;
CREATE POLICY users_select_own ON users
    FOR SELECT TO authenticated USING (id = auth.uid());
DROP POLICY IF EXISTS users_update_own ON users;
CREATE POLICY users_update_own ON users
    FOR UPDATE TO authenticated USING (id = auth.uid()) WITH CHECK (id = auth.uid());

-- ── user_domain_weights (user self-manages from intake survey) ──
ALTER TABLE user_domain_weights ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS user_domain_weights_select_own ON user_domain_weights;
CREATE POLICY user_domain_weights_select_own ON user_domain_weights
    FOR SELECT TO authenticated USING (user_id = auth.uid());
DROP POLICY IF EXISTS user_domain_weights_insert_own ON user_domain_weights;
CREATE POLICY user_domain_weights_insert_own ON user_domain_weights
    FOR INSERT TO authenticated WITH CHECK (user_id = auth.uid());
DROP POLICY IF EXISTS user_domain_weights_update_own ON user_domain_weights;
CREATE POLICY user_domain_weights_update_own ON user_domain_weights
    FOR UPDATE TO authenticated USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid());
DROP POLICY IF EXISTS user_domain_weights_delete_own ON user_domain_weights;
CREATE POLICY user_domain_weights_delete_own ON user_domain_weights
    FOR DELETE TO authenticated USING (user_id = auth.uid());

-- ── progress_events (read-only to user; ingested by backend) ──
ALTER TABLE progress_events ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS progress_events_select_own ON progress_events;
CREATE POLICY progress_events_select_own ON progress_events
    FOR SELECT TO authenticated USING (user_id = auth.uid());

-- ── xp_ledger (read-only to user; written by backend) ──
ALTER TABLE xp_ledger ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS xp_ledger_select_own ON xp_ledger;
CREATE POLICY xp_ledger_select_own ON xp_ledger
    FOR SELECT TO authenticated USING (user_id = auth.uid());

-- ── currency_ledger (read-only to user; written by backend) ──
ALTER TABLE currency_ledger ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS currency_ledger_select_own ON currency_ledger;
CREATE POLICY currency_ledger_select_own ON currency_ledger
    FOR SELECT TO authenticated USING (user_id = auth.uid());

-- ── user_domain_progress (materialized cache; read-only to user) ──
ALTER TABLE user_domain_progress ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS user_domain_progress_select_own ON user_domain_progress;
CREATE POLICY user_domain_progress_select_own ON user_domain_progress
    FOR SELECT TO authenticated USING (user_id = auth.uid());

-- ── user_currency_balances (materialized cache; read-only to user) ──
ALTER TABLE user_currency_balances ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS user_currency_balances_select_own ON user_currency_balances;
CREATE POLICY user_currency_balances_select_own ON user_currency_balances
    FOR SELECT TO authenticated USING (user_id = auth.uid());

-- ── quest_assignments (read-only to user; assigned/progressed by backend) ──
ALTER TABLE quest_assignments ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS quest_assignments_select_own ON quest_assignments;
CREATE POLICY quest_assignments_select_own ON quest_assignments
    FOR SELECT TO authenticated USING (user_id = auth.uid());

-- ── streaks (read-only to user; maintained by backend) ──
ALTER TABLE streaks ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS streaks_select_own ON streaks;
CREATE POLICY streaks_select_own ON streaks
    FOR SELECT TO authenticated USING (user_id = auth.uid());

-- ── user_achievements (read-only to user; awarded by backend) ──
ALTER TABLE user_achievements ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS user_achievements_select_own ON user_achievements;
CREATE POLICY user_achievements_select_own ON user_achievements
    FOR SELECT TO authenticated USING (user_id = auth.uid());

-- ── prestige (read-only to user; maintained by backend) ──
ALTER TABLE prestige ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS prestige_select_own ON prestige;
CREATE POLICY prestige_select_own ON prestige
    FOR SELECT TO authenticated USING (user_id = auth.uid());

-- ── Reference / catalog tables: authenticated read, backend-managed writes ──
ALTER TABLE domains ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS domains_read_all ON domains;
CREATE POLICY domains_read_all ON domains FOR SELECT TO authenticated USING (true);

ALTER TABLE levels ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS levels_read_all ON levels;
CREATE POLICY levels_read_all ON levels FOR SELECT TO authenticated USING (true);

ALTER TABLE xp_rules ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS xp_rules_read_all ON xp_rules;
CREATE POLICY xp_rules_read_all ON xp_rules FOR SELECT TO authenticated USING (true);

ALTER TABLE quests ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS quests_read_all ON quests;
CREATE POLICY quests_read_all ON quests FOR SELECT TO authenticated USING (true);

ALTER TABLE achievements ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS achievements_read_all ON achievements;
CREATE POLICY achievements_read_all ON achievements FOR SELECT TO authenticated USING (true);

ALTER TABLE achievement_levels ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS achievement_levels_read_all ON achievement_levels;
CREATE POLICY achievement_levels_read_all ON achievement_levels FOR SELECT TO authenticated USING (true);
