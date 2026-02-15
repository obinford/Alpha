# RTM Picks Platform — Verification Status

**Date:** 2026-02-15
**Phase 1:** Post-Build Verification ✅
**Phase 2:** Premium Frontend Rebuild ✅

---

## Phase 2: Premium Frontend Rebuild

All 4 core pages rebuilt from scratch to match a $200/month premium product standard. Dark theme, gold accents, data-driven layouts, professional typography.

### Milestone 1 — Signal Page (`signal.html`)
**Commit:** `eb4b7d5`

Key changes:
- **Card-based layout** with EV column + content area for each signal
- **Play names** auto-generated from market data (e.g. "NYY ML", "Over 8.5 Runs")
- **Matchup lines** with ET-converted game times
- **Hero card** for the strongest signal with gold border accent
- **Component mini-bars** showing EV, Steam, Projection, Consensus breakdown
- **"Also +EV at"** section showing alternate sportsbooks from `other_books`
- **Performance tab** with star tier and sport breakdowns
- **Signal engine fixes**: granular consensus scoring (1→10 through 7+→75), quarter Kelly with 3u cap, fair odds calculation, `other_books` collection across sportsbooks

Backend changes:
- `rtm_signal_engine/rtm_signal.py` — consensus scoring returns `(score, num_books)`, Kelly sizing, fair odds, other_books collection
- `api/routes/signal.py` — added `_dedup_signals()` grouping by (game_id, market_type, side), merges other_books

### Milestone 2 — Sharp Tracker (`sharp-tracker.html`)
**Commit:** `f3e7454`

Key changes:
- **Fixed "247H OUT" bug** — `fmtLeadTime()` formats as "10d 7h" for >24h, "5.2h" for <24h
- **Sharp Only toggle** (default on) filters alerts/movers to sharp books only
- **Book badges** — gold for sharp (Pinnacle/Circa/BetOnline/Bovada), gray for soft
- **Line movement charts** with Chart.js — sharp books: thick gold lines (borderWidth: 3); soft: dashed muted (borderDash: [4, 2])
- **Chart controls** — sharp-only toggle, market type tabs (h2h/spreads/totals/all), custom legend
- **"Sharp Books Moving" stat** displayed in gold
- **Sport filter dropdown** for all sections
- **Magnitude bar** on steam alerts showing relative move size
- **Book display names** mapping API IDs to readable names
- **ET game times** throughout

### Milestone 3 — Performance Dashboard (`performance.html`)
**Commit:** `33ef686`

Key changes:
- **Star rating tier cards** (5★/4★/3★) from `/api/signals/performance` with win rate, record, units, ROI
- **EV bucket analysis** — client-side computation from results data (2-5%, 5-8%, 8-12%, 12-20%, 20%+ EV buckets)
- **By-sportsbook cards** from `/api/performance/by-book` with branded color accents per book
- **By-sport cards** with sport-colored fill bars, sorted by profitability
- **Cumulative profit chart** with dynamic green/red line based on final P/L
- **Pending signals count** displayed alongside graded totals
- **Lead time** with d/h formatting matching sharp tracker
- Fetches 5 endpoints in parallel: summary, results, by-sport, by-book, signals/performance

### Milestone 4 — Dashboard Command Center (`dashboard.html`)
**Commit:** `2a620b0`

Key changes:
- **Parallel API fetching** — 4 sources: EV opportunities, signals, performance, sharp dashboard
- **Active signals section** with card layout and hero card for strongest signal
- **Fixed count discrepancy** — shows both signal count AND EV opportunity count (was only showing EV count)
- **Stats bar** — Active Signals (gold), EV Opportunities (green), Best EV%, Record, Units P/L, Steam Alerts (red)
- **Signal cards** — play name, matchup with ET time, Kelly size, fair odds, strength bar, other books
- **Time badges** — LIVE (red), SOON (yellow), EARLY (blue) with d/h formatting
- **"View all signals →"** link in section header
- **EV opportunities table** preserved with all filters, default sort changed to EV%

---

## Phase 2 Verification Results

### API Server
- **FastAPI loads** with all 16 routers and **36+ routes**
- **Health check**: `GET /health` → `{"status": "ok"}`
- All endpoints return clean JSON (no 500 errors)

### Frontend-to-Backend URL Matching
All **15 unique fetch endpoints** across 4 rebuilt pages verified against backend routes:

| Page | Endpoints | Status |
|------|-----------|--------|
| dashboard.html | `/api/ev-opportunities/`, `/api/signals/active`, `/api/performance/summary`, `/api/sharp-dashboard/` | ✅ |
| signal.html | `/api/signals/active`, `/api/signals/history`, `/api/signals/performance` | ✅ |
| sharp-tracker.html | `/api/sharp-dashboard/`, `/api/line-movements/game/{id}`, `/api/steam-alerts/` | ✅ |
| performance.html | `/api/performance/summary`, `/api/performance/results`, `/api/performance/by-sport`, `/api/performance/by-book`, `/api/signals/performance` | ✅ |

### JavaScript Integrity
- **Bracket balance** checks pass on all 4 rebuilt pages (matched `{}`/`()`/`[]`)

### Signal Engine
Tested with synthetic 3-opportunity data:
- 3 EV opps → 1 consolidated signal ✅
- Kelly sizing: 3.00u (capped at quarter Kelly max) ✅
- Fair odds: +233 ✅
- Consensus: 3 books ✅
- Other books: fanduel, betmgm collected ✅

---

## Phase 1: Original Verification (Preserved)

### What Works

#### Scanner Pipeline
- **EV scanning**: Correctly finds +EV opportunities by devigging sharp book lines (Pinnacle > Circa > BetOnline)
- **Console output**: Games grouped by day (TODAY/TOMORROW/day name), opportunity counts, sport-grouped tables
- **Signal engine**: Generates calibrated 3-5 star signals from EV data using 4-component confluence model
- **Signal scoring**: Continuous curves for EV (15-100), tiered steam (40/70/100), market consensus (15-75 + steam bonus)
- **Kelly sizing**: Proper kelly-based unit recommendations on all signals
- **Prop scanning**: Correctly merges prop data, builds Over/Under pairs, deviggs, finds +EV

#### API Server (FastAPI)
- **16 routers** mounted with correct prefixes
- **Health check**: `GET /health` → `{"status": "ok"}`
- **Static file serving**: Frontend HTML served from `/`
- **CORS**: Configured for all origins
- **All endpoints**: Return clean JSON error responses (no more 500 Internal Server Errors)
- **Usage endpoint**: Works without DB (`GET /api/usage/`)

#### Frontend (9 Pages)
- **All fetch URLs** verified to match backend API endpoint paths
- **API base URL patterns** resolve correctly (localhost and production)

#### Performance Page (Empty Data)
- Summary returns clean zeros
- Results table shows "No results yet" message
- Charts skip rendering with empty data (no JS errors)
- Signal performance returns empty tier/sport breakdowns

### What Was Fixed in Phase 1

#### API Route Error Handling (5 files)
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

## Git History (Phase 2)

All commits on branch `claude/setup-rtm-picks-u065Z`:

| Commit | Description |
|--------|-------------|
| `eb4b7d5` | feat: signal page premium rebuild — card layout, dedup engine, consensus scoring |
| `f3e7454` | feat: sharp-tracker premium rebuild — line movement charts, sharp filtering |
| `33ef686` | feat: performance analytics dashboard rebuild — tier/EV/book/sport breakdowns |
| `2a620b0` | feat: dashboard command center rebuild — parallel fetching, signal cards, stats bar |
