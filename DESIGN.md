# Life Tycoon — Design

> Skeleton document. Sections below outline the intended architecture; details
> will be filled in as the app is built.

## Concept

Life Tycoon gamifies real-world self-improvement. A user's real activity in a
set of life **domains** (initially Money, Fitness, Education) is converted into
game mechanics: XP, levels, in-app currency, quests, streaks, achievements, and
prestige.

## Domains

Each domain is independently leveled. Users weight the domains they care about
during onboarding (`user_domain_weights`), and the engine balances rewards
accordingly. New domains can be added as catalog rows without schema changes.

## Core mechanics

| Mechanic       | Backing tables                                            |
| -------------- | --------------------------------------------------------- |
| Progress intake| `progress_events` (idempotent, verifiable)                |
| XP             | `xp_rules`, `xp_ledger`, `user_domain_progress`, `levels` |
| Currency       | `currency_ledger`, `user_currency_balances`               |
| Quests         | `quests`, `quest_assignments`                             |
| Streaks        | `streaks`                                                 |
| Achievements   | `achievements`, `achievement_levels`, `user_achievements` |
| Prestige       | `prestige`                                                |

### Event-sourced ledgers

XP and currency are **append-only ledgers**. `user_domain_progress` and
`user_currency_balances` are materialized caches derived from the ledgers, so
balances are always auditable and reconstructable.

### Idempotent progress ingestion

Every `progress_event` carries an `idempotency_key` and a
`verification_status`, so the same real-world action can be reported more than
once without double-counting, and unverified events can be held for review.

## System components

- **`packages/engine`** — pure, domain-agnostic rules for translating
  `progress_events` into XP / currency / quest progress.
- **`packages/types`** — shared TypeScript types, including Supabase-generated
  database types.
- **`packages/ui`** — shared component library used by both apps.
- **`apps/mobile`** — the player experience.
- **`apps/admin`** — quest/content authoring and moderation.
- **`supabase/`** — schema, RLS, and Edge Functions.

## Security model

Row-level security is enabled on every user-scoped table. Users can read only
their own rows; ledgers and materialized caches are read-only to users and
written exclusively by the backend. Catalog tables (domains, levels, rules,
quests, achievements) are readable by any authenticated user. See
[`supabase/migrations/002_gamification_rls.sql`](./supabase/migrations/002_gamification_rls.sql).
