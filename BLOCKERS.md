# Blockers

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
