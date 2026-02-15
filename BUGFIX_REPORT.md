# BUGFIX REPORT — Comprehensive Platform Testing & Fixes

**Date:** 2026-02-15
**Session:** Bug Testing Session — Systematic Audit

---

## Summary

Systematic audit of the live RTM Picks Platform: every API route, every frontend page, every fetch URL, every nav bar, and the full scanner pipeline. Found and fixed 5 bugs across 10 files.

---

## Bugs Found & Fixed

### Bug #1: Sport-Specific Prop Markets — 422 Error [CRITICAL]

**Problem:** The scanner sent ALL 13 prop market types (including football-specific ones like `player_pass_tds`, `player_pass_yds`, `player_rush_yds`, `player_receptions`, `player_reception_yds`, `player_anytime_td`) to every sport. The Odds API returns 422 for unsupported markets per sport — e.g., sending `player_pass_tds` to CBB/NHL.

**Fix:** Added sport-specific prop market mappings to `shared/config.py`:
- **Basketball (NBA/CBB/WNBA):** 7 markets — points, rebounds, assists, threes, blocks, steals, PRA
- **Football (NFL/CFB):** All 13 markets including passing, rushing, receiving
- **Hockey (NHL):** 4 markets — points, assists, blocks, steals
- **MLB/Tennis:** No prop markets (not yet configured)

Added `get_prop_markets_for_sport(sport_key)` helper function. Updated `odds_scraper.py` to use sport-specific lists in both `run_scan()` (API fetch) and `scan_game_props()` (EV scanning).

**Files:** `shared/config.py`, `backend/scrapers/odds_scraper.py`

---

### Bug #2: httpx Connection Pooling & Proxy Resilience

**Problem:** Every Supabase query and external API call created a new httpx connection. In containerized environments with egress proxies, direct `httpx.get()`/`httpx.post()` calls could fail. Additionally, `grader.py`, `signal_grader.py`, `clv_tracker.py`, and `score_fetcher.py` used raw `httpx.patch()`/`httpx.delete()` calls instead of the DB client, bypassing connection management.

**Fix:**
- `SupabaseClient` now creates a persistent `httpx.Client` (`self._http`) for all requests
- All `_httpx.patch()`, `_httpx.delete()` calls in grader, signal_grader, CLV tracker, and score_fetcher now route through `client._http`
- Odds API and Discord modules use shared `httpx.Client` instances for connection pooling
- Removed `import httpx as _httpx` anti-pattern from grader and signal_grader

**Files:** `backend/db.py`, `backend/scrapers/grader.py`, `backend/rtm_signal_engine/signal_grader.py`, `backend/scrapers/clv_tracker.py`, `backend/scrapers/scores/score_fetcher.py`, `backend/scrapers/odds/odds_api.py`, `backend/notifications/discord.py`

---

### Bug #3: Performance Results Endpoint Missing `range` Parameter

**Problem:** The frontend sends a `range` query parameter (e.g., "7d", "30d") to all three performance endpoints (summary, results, by-sport). The `summary` and `by-sport` endpoints accepted `range` and used `_range_to_dates()` to convert it. But the `results` endpoint only accepted raw `date_from`/`date_to` parameters — the `range` param was silently ignored, so results were never filtered by time period.

**Fix:** Added `range` parameter to `performance_results()` endpoint. When `range` is provided and `date_from` is not, it converts range to date_from/date_to using the existing `_range_to_dates()` helper.

**File:** `backend/api/routes/performance.py`

---

### Bug #4: Scanner Console Noise

**Problem:** Every 10-minute scan cycle printed "Discord: no new alerts to send.", "Steam alerts: no new steam detected.", and "RTM Signals: no signals met threshold." even when there was nothing to report. This cluttered the console log with noise, making it harder to spot real events.

**Fix:** Changed to only print when there IS something to report. Quiet scans now produce less output. "Sent X alerts", "X new steam alerts", "X signals fired" messages still print when there's activity.

**File:** `backend/scrapers/odds_scraper.py`

---

## Verification Results

### API Endpoint Audit

All 20+ endpoints verified for correct routing and parameter handling:

| Endpoint Group | Route Prefix | Status |
|---|---|---|
| EV Opportunities | `/api/ev-opportunities` | OK |
| Performance | `/api/performance` | Fixed (Bug #3) |
| Signals | `/api/signals` | OK |
| Props | `/api/props` | OK |
| Sharp Dashboard | `/api/sharp-dashboard` | OK |
| Line Movements | `/api/line-movements` | OK |
| Steam Alerts | `/api/steam-alerts` | OK |
| CLV | `/api/clv` | OK |
| Recap | `/api/recap` | OK |
| Bankroll | `/api/bankroll` | OK |
| Odds Screen | `/api/odds-screen` | OK |
| Usage | `/api/usage` | OK |

### Frontend/Backend Route Matching

All 9 frontend pages verified — every `fetch()` URL matches its corresponding backend route:

| Frontend Page | API Calls | Match |
|---|---|---|
| dashboard.html | `/api/ev-opportunities/` | OK |
| signal.html | `/api/signals/active`, `/history`, `/performance` | OK |
| sharp-tracker.html | `/api/sharp-dashboard/`, `/api/line-movements/` | OK |
| props.html | `/api/props/` | OK |
| odds-screen.html | `/api/odds-screen/{sport}` | OK |
| performance.html | `/api/performance/summary`, `/results`, `/by-sport` | Fixed |
| clv-report.html | `/api/clv/summary`, `/api/clv/` | OK |
| daily-recap.html | `/api/recap/date/{date}` | OK |
| bankroll.html | `/api/bankroll/size`, `/size-batch`, `/simulate` | OK |

### Nav Bar Consistency

All 9 pages have identical nav bars with all 9 links:
Dashboard | Signal | Sharp Tracker | Props | Odds Screen | Performance | CLV Report | Daily Recap | Bankroll

### Signal Engine Integration

Verified the full signal pipeline in `odds_scraper.py`:
1. Signal generation from EV opportunities (RTMSignal engine)
2. Signal storage to Supabase
3. Discord alerts for 4+ star signals
4. Signal grading for completed games

### Scanner Pipeline

Full scan cycle verified:
1. Fetch mainlines (h2h, spreads, totals) for ALL upcoming games
2. Fetch sport-specific props for near-term games only (Fixed — Bug #1)
3. Persist games, odds snapshots, true lines
4. Store line movements for ALL games
5. Scan for +EV opportunities
6. Persist EV opportunities (bulk insert with row-by-row fallback)
7. CLV record creation and processing
8. Steam move detection
9. Score fetching and auto-grading
10. RTM Signal generation and grading
11. Discord alerts
12. Console output (cleaned — Bug #4)

---

## Files Modified

| File | Change |
|---|---|
| `shared/config.py` | Sport-specific prop market mappings |
| `backend/scrapers/odds_scraper.py` | Use sport-specific props, clean console output |
| `backend/db.py` | Persistent httpx.Client for connection pooling |
| `backend/scrapers/grader.py` | Route httpx calls through client._http |
| `backend/rtm_signal_engine/signal_grader.py` | Route httpx calls through db_client._http |
| `backend/scrapers/clv_tracker.py` | Route httpx calls through db._http |
| `backend/scrapers/scores/score_fetcher.py` | Shared httpx.Client, route Supabase calls through client._http |
| `backend/scrapers/odds/odds_api.py` | Shared httpx.Client for connection pooling |
| `backend/notifications/discord.py` | Shared httpx.Client for connection pooling |
| `backend/api/routes/performance.py` | Add `range` param to results endpoint |

---

## What Was NOT Broken

- All 9 nav bars: consistent across every page
- All frontend fetch URLs: correctly match backend routes
- Signal engine: properly wired into scan cycle
- CLV tracking: create records → close at game start → expire stale
- Auto-grading: kelly-based unit sizing (fixed in previous session)
- Discord notifications: signal alerts, EV alerts, rate limiting
- Props page: new line detection, time badges
- Sharp tracker: 48h window, steam alerts
