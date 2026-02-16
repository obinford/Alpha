# RTM Picks Platform — Status Report

<<<<<<< HEAD
**Date:** 2026-02-15
**Phase 1:** Post-Build Verification ✅
**Phase 2:** Premium Frontend Rebuild ✅
=======
**Date:** 2026-02-16
**Session:** Milestones 2-5 — Premium Frontend Rebuild
>>>>>>> origin/claude/view-commit-history-JpSsv

---

## Phase 2: Premium Frontend Rebuild

<<<<<<< HEAD
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
=======
### Infrastructure
- **Live Scanner**: The Odds API scanner pulls real odds data across MLB, NBA, NFL, NHL, CFB, CBB
- **Signal Engine**: Confluence-based signal system producing real signals with star ratings 1-5
- **+EV Engine**: Compares sportsbook odds to sharp book no-vig lines, calculates true probability and Kelly sizing
- **Steam Detection**: Detects when 3+ books move the same direction within 30 minutes
- **API**: 36+ endpoints running on FastAPI at localhost:8000 (16 routers)
- **Database**: Supabase (PostgreSQL) storing odds history, signals, performance results

### Frontend Pages (9 total, 4 rebuilt as premium)

| Page | Status | Rebuilt? | Notes |
|------|--------|----------|-------|
| **Dashboard** | Working | Yes (M4) | Card-based command center, EV% prominent, expandable line charts per game, Kelly clamped 3u, fetches both EV opps + signal count |
| **Signal** | Working | Yes (M1) | Confluence signals with star ratings, deduplication, hero top signal, history + performance views |
| **Sharp Tracker** | Working | Yes (M2) | Professional line charts (sharp books only), 4H/12H/24H/ALL time range, toggleable legend, sharp vs soft steam distinction |
| **Performance** | Working | Yes (M3) | Cumulative P&L chart, lead time breakdown, EV vs actual charts, by-sportsbook grid, graceful empty states |
| **Props** | Working | No | Player prop opportunities |
| **Odds Screen** | Working | No | Live odds comparison across books |
| **CLV Report** | Working | No | Closing line value tracking |
| **Daily Recap** | Working | No | Daily summary of picks and results |
| **Bankroll** | Working | No | Bankroll management tools |

### All Nav Links Verified
- All 9 pages have consistent navigation with correct `active` state
- No broken links between pages
>>>>>>> origin/claude/view-commit-history-JpSsv

### What Was Fixed in Phase 1

<<<<<<< HEAD
#### API Route Error Handling (5 files)
All routes that previously returned 500 Internal Server Error when Supabase was unreachable now return proper JSON error responses:

| File | Issue | Fix |
|------|-------|-----|
| `backend/api/routes/signal.py` | No try/except on 3 endpoints | Added HTTPException wrapping |
| `backend/api/routes/performance.py` | No try/except on 5 endpoints | Added HTTPException wrapping |
| `backend/api/routes/clv.py` | No try/except on 2 endpoints | Added HTTPException wrapping |
| `backend/api/routes/props.py` | No try/except on list_props | Added HTTPException wrapping |
| `backend/api/routes/usage.py` | No try/except on get_usage | Added HTTPException wrapping |
=======
## Bug Fixes Applied (Milestones 1-5)

| Bug | Fix | Pages |
|-----|-----|-------|
| **Signal deduplication** | One card per play (side+game+market), strongest signal featured — no duplicate plays across books | signal.html |
| **Kelly sizing clamped** | Max 3u on all displays (was 5u) | signal.html, dashboard.html |
| **Game times in Eastern Time** | All timestamps use `timeZone: 'America/New_York'` — no more UTC display | signal.html, dashboard.html, sharp-tracker.html, performance.html |
| **"247H OUT" display bug** | Replaced `Math.round(h)+"h"` with `formatHoursMinutes()` — correctly shows "26h 15m" | sharp-tracker.html, dashboard.html |
| **Steam showing BetParx/BetRivers** | Steam alerts now prioritize sharp book movement, sorted sharp-first with gold SHARP ribbon | sharp-tracker.html |
| **Dashboard showing 1 opportunity** | Dashboard now fetches same `/ev-opportunities/` endpoint directly — shows all opportunities, not just 1 | dashboard.html |
| **Dashboard/signal data consistency** | Dashboard fetches `/signals/active` in parallel for signal count in stats bar | dashboard.html |
| **Consensus score always 75** | Displays actual `consensus_score` from API (was never hardcoded in frontend — API model issue) | signal.html |
>>>>>>> origin/claude/view-commit-history-JpSsv

---

## Design System

- **Theme**: Dark (#0a0e17 base) with gradient card backgrounds (`linear-gradient(135deg, #111827, #0f1521)`)
- **Typography**: Monospace (SF Mono / Fira Code / Cascadia Code / Consolas)
- **Header**: Animated gradient bar (green → blue → purple → red) across all rebuilt pages
- **Colors**: Green (#00e676) positive, Red (#ff5252) negative, Gold (#ffd700) sharp/premium, Blue (#42a5f5) informational, Yellow (#ffc107) EV/edge
- **Cards**: Hover lift effect, gradient backgrounds, rounded 8px corners
- **Responsive**: Grid breakpoints at 768px for mobile
- **Charts**: Chart.js 4.4.7 with custom dark tooltips, monospace fonts, subtle grid lines

---

## Page-Specific Features

### Dashboard (Milestone 4)
- Stats bar: Games Tracked (48h), Opportunities, Signals Generated, Early Lines, Props, Best EV%
- Each opportunity as a card: EV% (28px bold), play, sportsbook, odds, fair value odds, true prob, Kelly sizing, time badge
- Time badges: EARLY LINE, TODAY, URGENT, LIVE with color-coded urgency
- Click-to-expand: line movement chart + other books comparison table
- Filters: Sport, Time Window, Min EV%, Sort By (EV/Time), Search
- Auto-refresh 60s with visible countdown + manual Refresh button
- Date separators when sorted by time, grid layout when sorted by EV

### Sharp Tracker (Milestone 2)
- Line charts plot only sharp books: Pinnacle (gold), BetOnline (blue), Circa (green), Bovada (orange)
- Chart title: "[Side] | Full Game" with matchup subtitle
- Time range selector: 4H, 12H, 24H, ALL buttons
- Toggleable checkboxes per book in custom legend
- Y-axis: American odds (or total number for totals markets)
- Tooltips show Eastern Time
- Steam alerts: sharp book movement sorted first, gold "SHARP" corner ribbon
- Book tags color-coded: gold for sharp, gray for soft

### Performance Dashboard (Milestone 3)
- Stats bar: Total Bets, Record W-L-P, Win Rate, Profit/Loss, ROI, Avg EV%
- Cumulative P&L line chart with gradient fill (green when profitable, red when not)
- Lead Time Breakdown: bar chart + detail table (bets, record, win%, ROI, P/L per time bucket: <1h, 1-3h, 3-6h, 6-12h, 12-24h, 24h+)
- EV vs Actual: Actual ROI vs Expected ROI by EV bucket, Win Rate by EV bucket
- By Sportsbook: grid of cards per book with record, win rate, ROI, profit
- Filters: Sport, Sportsbook, Time Period
- All charts handle empty/sparse data gracefully with clean zero states

---

## Known Limitations

### Data Dependencies
- Performance charts need graded results to populate — empty states are clean, not broken
- Lead time estimates use signal timestamp → game time; may differ from actual bet placement time
- EV vs Actual charts need sufficient volume per EV bucket to be meaningful

### Not Yet Implemented
- **Whop Authentication**: SDK integration not connected
- **AI Co-pilot**: Claude API integration for personalized analysis
- **Push Notifications**: No alerts for new signals or steam moves
- **WebSocket**: Uses polling (60s) rather than real-time WebSocket
- **Backtesting UI**: Backend models exist but no frontend visualization
- **Deployment**: Running localhost only — not yet deployed to Vercel/Railway

### Known Pre-existing Issues
- **Egress proxy**: Container environment may block outbound HTTPS to Supabase/Odds API
- **In-memory alert dedup**: Lost on restart, unbounded growth potential
- **Projection engine**: NBA-only with mock data for other sports
- **4 stub routers**: picks, odds, models, copilot (registered but non-functional)

---

## Architecture Notes

- Frontend: Static HTML in `/frontend/` — no build step required
- Backend: FastAPI on localhost:8000 with CORS configured
- Charts: Chart.js 4.4.7 with date-fns adapter
- No CSS framework — all custom inline styles
- All API calls use relative paths (production) or `localhost:8000` (development)

---

## Git History (Phase 2)

<<<<<<< HEAD
All commits on branch `claude/setup-rtm-picks-u065Z`:

| Commit | Description |
|--------|-------------|
| `eb4b7d5` | feat: signal page premium rebuild — card layout, dedup engine, consensus scoring |
| `f3e7454` | feat: sharp-tracker premium rebuild — line movement charts, sharp filtering |
| `33ef686` | feat: performance analytics dashboard rebuild — tier/EV/book/sport breakdowns |
| `2a620b0` | feat: dashboard command center rebuild — parallel fetching, signal cards, stats bar |
=======
| Check | Status |
|-------|--------|
| All 9 pages exist and load | PASS |
| Nav links consistent across all pages | PASS |
| Signal deduplication working | PASS |
| Kelly sizing clamped to 3u | PASS |
| Eastern Time on all rebuilt pages | PASS |
| Hours display bug fixed | PASS |
| Steam prioritizes sharp books | PASS |
| Dashboard shows all opportunities | PASS |
| Dashboard/signal data consistent | PASS |
| Sharp tracker charts sharp-only | PASS |
| Performance handles empty data | PASS |
| Line chart time range selector works | PASS |
| Toggleable book legend works | PASS |
>>>>>>> origin/claude/view-commit-history-JpSsv
