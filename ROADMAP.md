# Life Tycoon — Roadmap

> Skeleton document. Phases and scope will evolve.

## Phase 0 — Scaffold (current)

- [x] Monorepo skeleton (`apps/`, `packages/`, `supabase/`)
- [x] Project docs (README, DESIGN, SETUP, ROADMAP)
- [x] Gamification schema migration (`001_gamification_schema.sql`)
- [x] Gamification RLS migration (`002_gamification_rls.sql`)

## Phase 1 — Engine foundation

- [ ] `packages/types` — shared + Supabase-generated types
- [ ] `packages/engine` — XP, currency, level, and streak calculation
- [ ] Edge Functions for idempotent progress-event ingestion
- [ ] Unit tests for the engine

## Phase 2 — Mobile MVP

- [ ] `apps/mobile` — auth + onboarding (domain weighting)
- [ ] Progress logging and the XP/level dashboard
- [ ] Quests and streaks UI
- [ ] `packages/ui` — shared component library

## Phase 3 — Quests & achievements

- [ ] Quest assignment + completion flow
- [ ] Achievements and tiered badges
- [ ] AI-generated quests

## Phase 4 — Admin & content

- [ ] `apps/admin` — quest/content authoring
- [ ] Event verification / moderation tooling

## Phase 5 — Prestige & retention

- [ ] Prestige loop
- [ ] Streak freezes and recovery
- [ ] Notifications and re-engagement
