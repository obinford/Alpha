# Blockers

## Cannot test live API regions — EU, US_EX, UK (Build Session 8)

**Status:** Blocked — no `THE_ODDS_API_KEY` in this build environment.

**Action needed:** After deploy, run:
```bash
cd backend && python3 -c "from scrapers.test_regions import test_all; test_all()"
```
This tests each region (`eu`, `us_ex`, `uk`) with a single NBA h2h call and reports:
- Status code (200 = works, 401/403 = plan doesn't support)
- Books found per region
- Credit usage

If `eu` returns 200 → Pinnacle is available. Set `"eu"` in `ACTIVE_REGIONS`.
If `eu` returns 401/403 → Pinnacle requires higher-tier plan. Document and continue with sharp book consensus.

## Cannot verify Supabase schemas for new columns (Build Session 8)

**Status:** No `SUPABASE_URL` / `SUPABASE_KEY` in environment.

**Action needed:** After deploy, run migration:
```sql
ALTER TABLE ev_opportunities ADD COLUMN IF NOT EXISTS devig_source text DEFAULT 'sharp_consensus';
ALTER TABLE ev_opportunities ADD COLUMN IF NOT EXISTS devig_confidence float DEFAULT 0.8;
```

## NBA.com API blocked by proxy (Build Session 4)

**Status:** Worked around with mock data

NBA.com (`stats.nba.com`) returns 403 Forbidden in the build environment
due to a proxy. The `nba_api` library works correctly but the upstream
server blocks the request.

**Workaround:** Created comprehensive mock data in
`backend/projections/mock_data.py` with realistic 2024-25 stats for 15
top NBA players, all 30 team defense ratings, and league averages. The
`ProjectionEngine` class accepts `use_mock=True` to use this data.

**To fix in production:**
1. Set `use_mock=False` when deploying to Railway/production
2. The stats fetcher (`backend/projections/stats_fetcher.py`) will
   automatically use live NBA.com data when available
3. Rate limiting is built in (1.5s between requests)
4. File-based caching prevents redundant API calls (6h game logs,
   12h season averages, 24h team defense)
