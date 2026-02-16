# RTM Picks Platform — Status Report

**Date:** 2026-02-16
**Session:** Milestones 2-5 — Premium Frontend Rebuild

---

## What Works

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

---

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

## Verification Summary

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
