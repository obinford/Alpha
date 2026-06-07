# Life Tycoon — Setup

> Skeleton document. Commands and tooling will be finalized as the app code
> lands.

## Prerequisites

- Node.js (LTS) and a package manager (pnpm recommended for the monorepo)
- [Supabase CLI](https://supabase.com/docs/guides/cli)
- For the mobile app: Expo / React Native toolchain

## Repository structure

See [README.md](./README.md) for the monorepo layout.

## Environment

Copy `.env.example` to `.env` (per app/package as it is added) and fill in:

- `SUPABASE_URL`
- `SUPABASE_ANON_KEY`
- `SUPABASE_SERVICE_ROLE_KEY` (server-side only — never ship to clients)

## Database

The gamification schema lives in [`supabase/migrations`](./supabase/migrations):

1. `001_gamification_schema.sql` — tables, indexes, seed domains
2. `002_gamification_rls.sql` — row-level-security policies

> **Important:** These migrations are **already applied** to the live Supabase
> project (`csxbqejsuasvjbtfunpq`). The repo copies are for version control and
> review only — do not re-apply them against the live database.

For a fresh/local stack:

```bash
supabase start
supabase db reset   # applies migrations in supabase/migrations
```

## Next steps

This repo is currently a skeleton. Application setup steps (installing
workspace dependencies, running the apps) will be documented here once the
apps and packages contain code.
