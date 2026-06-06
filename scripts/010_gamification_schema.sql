-- RTM Picks Platform: Gamification Schema
-- Migration 010: Multi-domain XP / quest / currency / achievement engine
--
-- Design notes:
--   * progress_events is the append-only event source. Every XP / currency
--     mutation must trace back to a progress_event via source_event_id.
--   * xp_ledger and currency_ledger are append-only; balances are never edited
--     in place. user_domain_progress and user_currency_balances are materialized
--     caches that can be fully rebuilt by folding the ledgers.
--   * idempotency_key on progress_events makes event ingestion safe to retry.

-- ─── Users ─────────────────────────────────────────────────────────────────

-- id is the same UUID as the Supabase auth user (auth.users.id); deleting the
-- auth user cascades to the gamification profile. No default — the id is always
-- supplied from auth (e.g. a handle_new_user trigger or the app on first login).
CREATE TABLE IF NOT EXISTS users (
    id          UUID PRIMARY KEY REFERENCES auth.users (id) ON DELETE CASCADE,
    email       TEXT UNIQUE NOT NULL,
    timezone    TEXT NOT NULL DEFAULT 'UTC',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);


-- ─── Domains ───────────────────────────────────────────────────────────────
-- The life areas the platform gamifies, e.g. 'money', 'fitness', 'education'.

CREATE TABLE IF NOT EXISTS domains (
    id    INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    key   TEXT UNIQUE NOT NULL,
    name  TEXT NOT NULL
);

INSERT INTO domains (key, name) VALUES
    ('money',     'Money'),
    ('fitness',   'Fitness'),
    ('education', 'Education')
ON CONFLICT (key) DO NOTHING;


-- ─── User Domain Weights ─────────────────────────────────────────────────────
-- Captured from the intake survey; per-user weights are expected to sum to 1.0.

CREATE TABLE IF NOT EXISTS user_domain_weights (
    user_id    UUID NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    domain_id  INTEGER NOT NULL REFERENCES domains (id) ON DELETE CASCADE,
    weight     NUMERIC NOT NULL DEFAULT 0 CHECK (weight >= 0 AND weight <= 1),
    PRIMARY KEY (user_id, domain_id)
);


-- ─── XP Rules ────────────────────────────────────────────────────────────────
-- Maps a domain action to its XP / currency payout and how repeated events
-- aggregate (e.g. 'sum', 'count', 'max'). multiplier_json holds conditional
-- multipliers (streak bonuses, time-of-day, etc).

CREATE TABLE IF NOT EXISTS xp_rules (
    id                   BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    domain_id            INTEGER NOT NULL REFERENCES domains (id) ON DELETE CASCADE,
    action_key           TEXT NOT NULL,
    base_xp              NUMERIC NOT NULL DEFAULT 0,
    currency_per_action  NUMERIC NOT NULL DEFAULT 0,
    aggregation          TEXT NOT NULL DEFAULT 'sum',
    multiplier_json      JSONB,
    active               BOOLEAN NOT NULL DEFAULT true,
    UNIQUE (domain_id, action_key)
);

CREATE INDEX IF NOT EXISTS idx_xp_rules_domain ON xp_rules (domain_id);
CREATE INDEX IF NOT EXISTS idx_xp_rules_active ON xp_rules (active);


-- ─── Quests ──────────────────────────────────────────────────────────────────
-- type: 'daily', 'weekly', 'milestone', 'chain', etc. criteria_json describes
-- the completion condition. prereq_quest_id enables quest chains. AI-generated
-- and user-sourced quests are tagged for provenance.

CREATE TABLE IF NOT EXISTS quests (
    id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    domain_id        INTEGER NOT NULL REFERENCES domains (id) ON DELETE CASCADE,
    title            TEXT NOT NULL,
    description      TEXT,
    type             TEXT NOT NULL DEFAULT 'standard',
    criteria_json    JSONB NOT NULL,
    xp_reward        NUMERIC NOT NULL DEFAULT 0,
    currency_reward  NUMERIC NOT NULL DEFAULT 0,
    prereq_quest_id  BIGINT REFERENCES quests (id) ON DELETE SET NULL,
    starts_at        TIMESTAMPTZ,
    ends_at          TIMESTAMPTZ,
    is_ai_generated  BOOLEAN NOT NULL DEFAULT false,
    source_user_id   UUID REFERENCES users (id) ON DELETE SET NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_quests_domain ON quests (domain_id);
CREATE INDEX IF NOT EXISTS idx_quests_type ON quests (type);
CREATE INDEX IF NOT EXISTS idx_quests_window ON quests (starts_at, ends_at);


-- ─── Quest Assignments ───────────────────────────────────────────────────────
-- status: 'assigned', 'in_progress', 'completed', 'expired', 'abandoned'.

CREATE TABLE IF NOT EXISTS quest_assignments (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id       UUID NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    quest_id      BIGINT NOT NULL REFERENCES quests (id) ON DELETE CASCADE,
    status        TEXT NOT NULL DEFAULT 'assigned',
    progress_json JSONB,
    assigned_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at  TIMESTAMPTZ,
    UNIQUE (user_id, quest_id)
);

CREATE INDEX IF NOT EXISTS idx_quest_assignments_user ON quest_assignments (user_id);
CREATE INDEX IF NOT EXISTS idx_quest_assignments_quest ON quest_assignments (quest_id);
CREATE INDEX IF NOT EXISTS idx_quest_assignments_status ON quest_assignments (status);


-- ─── Progress Events ─────────────────────────────────────────────────────────
-- Append-only event source. idempotency_key guarantees a given external event
-- is ingested at most once. verification_status: 'pending', 'verified',
-- 'rejected'; verifier records who/what confirmed it.

CREATE TABLE IF NOT EXISTS progress_events (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id             UUID NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    domain_id           INTEGER NOT NULL REFERENCES domains (id),
    action_key          TEXT NOT NULL,
    value               NUMERIC NOT NULL DEFAULT 1,
    raw_payload_json    JSONB,
    idempotency_key     TEXT NOT NULL UNIQUE,
    verification_status TEXT NOT NULL DEFAULT 'pending',
    verifier            TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_progress_events_user ON progress_events (user_id);
CREATE INDEX IF NOT EXISTS idx_progress_events_domain ON progress_events (domain_id);
CREATE INDEX IF NOT EXISTS idx_progress_events_action ON progress_events (action_key);
CREATE INDEX IF NOT EXISTS idx_progress_events_status ON progress_events (verification_status);
CREATE INDEX IF NOT EXISTS idx_progress_events_created ON progress_events (created_at);


-- ─── XP Ledger ───────────────────────────────────────────────────────────────
-- Append-only. Fold over (user_id, domain_id) to rebuild user_domain_progress.

CREATE TABLE IF NOT EXISTS xp_ledger (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id         UUID NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    domain_id       INTEGER NOT NULL REFERENCES domains (id),
    source_event_id BIGINT REFERENCES progress_events (id),
    xp_delta        NUMERIC NOT NULL,
    reason          TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_xp_ledger_user_domain ON xp_ledger (user_id, domain_id);
CREATE INDEX IF NOT EXISTS idx_xp_ledger_source_event ON xp_ledger (source_event_id);
CREATE INDEX IF NOT EXISTS idx_xp_ledger_created ON xp_ledger (created_at);


-- ─── Currency Ledger ─────────────────────────────────────────────────────────
-- Append-only. Fold over (user_id, currency_key) to rebuild balances.

CREATE TABLE IF NOT EXISTS currency_ledger (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id         UUID NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    currency_key    TEXT NOT NULL,
    delta           NUMERIC NOT NULL,
    reason          TEXT,
    source_event_id BIGINT REFERENCES progress_events (id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_currency_ledger_user_currency ON currency_ledger (user_id, currency_key);
CREATE INDEX IF NOT EXISTS idx_currency_ledger_source_event ON currency_ledger (source_event_id);
CREATE INDEX IF NOT EXISTS idx_currency_ledger_created ON currency_ledger (created_at);


-- ─── User Domain Progress (materialized cache) ───────────────────────────────
-- Rebuildable from xp_ledger + levels. Holds the current total XP and level
-- per (user, domain).

CREATE TABLE IF NOT EXISTS user_domain_progress (
    user_id    UUID NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    domain_id  INTEGER NOT NULL REFERENCES domains (id) ON DELETE CASCADE,
    total_xp   NUMERIC NOT NULL DEFAULT 0,
    level      INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, domain_id)
);


-- ─── User Currency Balances (materialized cache) ─────────────────────────────
-- Rebuildable from currency_ledger.

CREATE TABLE IF NOT EXISTS user_currency_balances (
    user_id      UUID NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    currency_key TEXT NOT NULL,
    balance      NUMERIC NOT NULL DEFAULT 0,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, currency_key)
);


-- ─── Levels ──────────────────────────────────────────────────────────────────
-- Precomputed XP curve: the cumulative XP required to reach each level within a
-- domain.

CREATE TABLE IF NOT EXISTS levels (
    domain_id     INTEGER NOT NULL REFERENCES domains (id) ON DELETE CASCADE,
    level         INTEGER NOT NULL,
    xp_threshold  NUMERIC NOT NULL,
    PRIMARY KEY (domain_id, level)
);


-- ─── Streaks ─────────────────────────────────────────────────────────────────
-- One running streak per (user, domain). freezes_remaining lets a user protect
-- a streak across a missed day.

CREATE TABLE IF NOT EXISTS streaks (
    id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id           UUID NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    domain_id         INTEGER NOT NULL REFERENCES domains (id) ON DELETE CASCADE,
    current_len       INTEGER NOT NULL DEFAULT 0,
    longest_len       INTEGER NOT NULL DEFAULT 0,
    last_event_date   DATE,
    freezes_remaining INTEGER NOT NULL DEFAULT 0,
    UNIQUE (user_id, domain_id)
);


-- ─── Achievements ────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS achievements (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    domain_id     INTEGER NOT NULL REFERENCES domains (id) ON DELETE CASCADE,
    key           TEXT NOT NULL,
    name          TEXT NOT NULL,
    criteria_json JSONB NOT NULL,
    xp_reward     NUMERIC NOT NULL DEFAULT 0,
    UNIQUE (domain_id, key)
);


-- ─── Achievement Levels ──────────────────────────────────────────────────────
-- Tiered achievements (bronze/silver/gold...) with escalating thresholds.

CREATE TABLE IF NOT EXISTS achievement_levels (
    id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    achievement_id BIGINT NOT NULL REFERENCES achievements (id) ON DELETE CASCADE,
    tier           INTEGER NOT NULL,
    threshold      NUMERIC NOT NULL,
    badge_url      TEXT,
    UNIQUE (achievement_id, tier)
);


-- ─── User Achievements ───────────────────────────────────────────────────────
-- A user holds at most one row per (achievement, tier).

CREATE TABLE IF NOT EXISTS user_achievements (
    user_id        UUID NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    achievement_id BIGINT NOT NULL REFERENCES achievements (id) ON DELETE CASCADE,
    tier           INTEGER NOT NULL DEFAULT 1,
    awarded_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, achievement_id, tier)
);

CREATE INDEX IF NOT EXISTS idx_user_achievements_user ON user_achievements (user_id);


-- ─── Prestige ────────────────────────────────────────────────────────────────
-- Tracks how many times a user has prestiged a domain and the resulting XP
-- multiplier. last_reset_at marks the most recent prestige reset.

CREATE TABLE IF NOT EXISTS prestige (
    user_id             UUID NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    domain_id           INTEGER NOT NULL REFERENCES domains (id) ON DELETE CASCADE,
    prestige_count      INTEGER NOT NULL DEFAULT 0,
    prestige_multiplier NUMERIC NOT NULL DEFAULT 1.0,
    last_reset_at       TIMESTAMPTZ,
    PRIMARY KEY (user_id, domain_id)
);
