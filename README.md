# Life Tycoon

Life Tycoon is a real-life gamification app. It turns progress across the
domains that matter — **Money**, **Fitness**, and **Education** — into XP,
levels, quests, currency, streaks, and achievements, so building a better life
feels like leveling up a character.

> **Status:** Skeleton scaffold. This repository currently contains the
> monorepo structure, documentation, and database migrations only — no
> application code yet.

## Monorepo layout

```
apps/
  mobile/      # Player-facing mobile app (React Native / Expo)
  admin/       # Internal admin / content + quest management console
packages/
  engine/      # Domain-agnostic gamification engine (XP, quests, currency, streaks)
  ui/          # Shared design system / UI component library
  types/       # Shared TypeScript types (incl. generated Supabase types)
supabase/
  migrations/  # Versioned SQL schema + RLS migrations
  functions/   # Supabase Edge Functions
```

## Documentation

- [DESIGN.md](./DESIGN.md) — product & system design overview
- [SETUP.md](./SETUP.md) — local development setup
- [ROADMAP.md](./ROADMAP.md) — phased delivery plan

## Backend

The backend is built on [Supabase](https://supabase.com) (PostgreSQL + Auth +
Edge Functions). The gamification schema and its row-level-security policies
live in [`supabase/migrations`](./supabase/migrations).

> **Note:** The migrations in this repo are already applied to the live
> Supabase project (`csxbqejsuasvjbtfunpq`). The committed copies exist for
> version control and review only.
