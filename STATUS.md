# RTM Picks Platform — Verification Status

**Date:** 2026-02-15
**Session:** Post-Build Verification

---

## What Works

### Scanner Pipeline
- **EV scanning**: Correctly finds +EV opportunities by devigging sharp book lines (Pinnacle > Circa > BetOnline)
- **Console output**: Games grouped by day (TODAY/TOMORROW/day name), opportunity counts, sport-grouped tables
- **Signal engine**: Generates calibrated 3-5 star signals from EV data using 4-component confluence model
- **Signal scoring**: Continuous curves for EV (15-100), tiered steam (40/70/100), market consensus (15-75 + steam bonus)
- **Kelly sizing**: Proper kelly-based unit recommendations on all signals
- **Prop scanning**: Correctly merges prop data, builds Over/Under pairs, deviggs, finds +EV

### API Server (FastAPI)
- **16 routers** mounted with correct prefixes
- **Health check**: `GET /health` → `{"status": "ok"}`
- **Static file serving**: Frontend HTML served from `/`
- **CORS**: Configured for all origins
- **All endpoints**: Return clean JSON error responses (no more 500 Internal Server Errors)
- **Usage endpoint**: Works without DB (`GET /api/usage/`)

### Frontend (9 Pages)
- **All fetch URLs** verified to match backend API endpoint paths
- **API base URL patterns** resolve correctly (localhost and production)
- **dashboard.html**: `GET /api/ev-opportunities/` ✅
- **signal.html**: `GET /api/signals/active`, `/history`, `/performance` ✅
- **sharp-tracker.html**: `GET /api/sharp-dashboard/`, `/api/line-movements/` ✅
- **props.html**: `GET /api/props/` ✅
- **odds-screen.html**: `GET /api/odds-screen/{sport}` ✅
- **performance.html**: `GET /api/performance/summary`, `/results`, `/by-sport`, `/api/signals/performance` ✅
- **clv-report.html**: `GET /api/clv/summary`, `/api/clv/` ✅
- **daily-recap.html**: `GET /api/recap/date/{date}` ✅
- **bankroll.html**: `POST /api/bankroll/size`, `/size-batch`, `/simulate` ✅

### Performance Page (Empty Data)
- Summary returns clean zeros: `{"total_bets":0, "record":"0-0", "win_rate":0, ...}`
- Results table shows "No results yet" message
- Charts skip rendering with empty data (no JS errors)
- Filters render without crashing
- Signal performance returns empty tier/sport breakdowns

---

## What Was Fixed

### API Route Error Handling (5 files)
All routes that previously returned 500 Internal Server Error when Supabase was unreachable now return proper JSON error responses:

| File | Issue | Fix |
|------|-------|-----|
| `backend/api/routes/signal.py` | No try/except on 3 endpoints | Added HTTPException wrapping |
| `backend/api/routes/performance.py` | No try/except on 5 endpoints | Added HTTPException wrapping |
| `backend/api/routes/clv.py` | No try/except on 2 endpoints | Added HTTPException wrapping |
| `backend/api/routes/props.py` | No try/except on list_props | Added HTTPException wrapping |
| `backend/api/routes/usage.py` | No try/except on get_usage | Added HTTPException wrapping |

---

## What Requires Real Credentials to Verify

These features work at the code level but cannot be end-to-end tested without real API keys:

| Feature | Blocked By | Code Status |
|---------|-----------|-------------|
| Live odds fetching | THE_ODDS_API_KEY | Scanner logic verified with synthetic data |
| DB persistence (games, odds, EV opps) | SUPABASE_URL/KEY | All DB write functions exist and are called |
| Signal storage in rtm_signals table | SUPABASE_URL/KEY | store_signals() tested in signal engine |
| CLV tracking | SUPABASE_URL/KEY | create_clv_from_ev_opportunities() called in scan loop |
| Steam detection | SUPABASE_URL/KEY | detect_steam_moves() called, queries line_movements |
| Auto-grading | SUPABASE_URL/KEY | grade_opportunities() called after score fetch |
| Discord alerts | DISCORD_WEBHOOK_URL | Alert thresholds configured (5% EV, 4+ stars) |

---

## Known Issues (Pre-existing)

1. **Egress proxy** — Container environment blocks outbound HTTPS to Supabase/Odds API (403)
2. **In-memory alert dedup** — Lost on restart, unbounded growth
3. **Projection engine NBA-only** — Mock data for non-NBA sports
4. **4 stub routers** — picks, odds, models, copilot (registered but non-functional)
5. **Hardcoded signal projection defaults** — opponent="BOS", home_away="home"

---

## Verification Summary

| Check | Status |
|-------|--------|
| API server starts | ✅ PASS |
| Signal engine generates signals | ✅ PASS (verified with synthetic data) |
| Frontend fetch URLs match API | ✅ PASS (all 9 pages) |
| Scanner console output format | ✅ PASS (grouped by day, counts, signal results) |
| Performance page with empty data | ✅ PASS (zeros, no errors) |
| API error handling | ✅ FIXED (was returning 500s) |
