# SYSTEM AUDIT — RTM Picks Platform

**Date:** 2026-02-15
**Session:** Build Session 6 — Milestone 1

---

## 1. Architecture Overview

```
rtm-picks-platform/
├── frontend/           # 9 static HTML pages (dark Bloomberg-terminal theme)
│   ├── dashboard.html       # +EV opportunity hub
│   ├── signal.html          # RTM Signal confluence model
│   ├── sharp-tracker.html   # Steam alerts + line movement tracking
│   ├── props.html           # Player prop screening
│   ├── odds-screen.html     # Multi-book odds comparison grid
│   ├── performance.html     # Historical P&L analytics
│   ├── clv-report.html      # Closing Line Value tracking
│   ├── daily-recap.html     # Daily betting recap
│   └── bankroll.html        # Kelly sizing + Monte Carlo simulator
│
├── backend/
│   ├── api/
│   │   └── routes/          # 17 route files (13 active, 4 stubs)
│   │       ├── ev.py             # GET / — EV opportunities
│   │       ├── signal.py         # GET /active, /history, /performance, /projection/{id}
│   │       ├── steam_alerts.py   # GET / — steam alerts
│   │       ├── sharp_dashboard.py# GET / — combined sharp money dashboard
│   │       ├── line_movements.py # GET /, GET /{game_id}
│   │       ├── props.py          # GET /, GET /types
│   │       ├── odds_screen.py    # GET /{sport}, GET /
│   │       ├── performance.py    # GET /summary, /results, /by-sport, /by-book, POST /recalculate
│   │       ├── clv.py            # GET /, GET /summary
│   │       ├── recap.py          # GET /today, /yesterday, /date/{date}, /recent, /morning-briefing
│   │       ├── bankroll.py       # POST+GET /size, POST /size-batch, POST+GET /simulate
│   │       ├── usage.py          # GET / — Odds API usage stats
│   │       ├── picks.py          # stub
│   │       ├── odds.py           # stub
│   │       ├── models.py         # stub
│   │       └── copilot.py        # stub
│   │
│   ├── scrapers/
│   │   ├── odds_scraper.py       # Main scan loop (10-min interval via APScheduler)
│   │   ├── grader.py             # Auto-grading: WIN/LOSS/PUSH with kelly sizing
│   │   ├── clv_tracker.py        # CLV record management
│   │   ├── odds/
│   │   │   └── odds_api.py       # The Odds API client
│   │   └── scores/
│   │       └── score_fetcher.py  # Game score fetching from The Odds API
│   │
│   ├── rtm_signal_engine/
│   │   ├── rtm_signal.py         # Confluence signal model (4 components)
│   │   └── signal_grader.py      # Signal auto-grading
│   │
│   ├── models/
│   │   ├── ev_calculator.py      # EV math: no-vig devig, probability, EV%
│   │   └── kelly.py              # Kelly Criterion bet sizing
│   │
│   ├── projections/
│   │   ├── projection_engine.py  # Weighted projection model (40/30/20/10)
│   │   ├── simulator.py          # Monte Carlo prop simulator (10k sims)
│   │   ├── stats_fetcher.py      # NBA.com stats with caching
│   │   ├── stats_cache.py        # File-based stats cache (6-24h TTL)
│   │   ├── league_averages.py    # League avg calculations
│   │   ├── math_utils.py         # Odds conversion utilities
│   │   └── mock_data.py          # 16 NBA players + 30 teams mock data
│   │
│   ├── analytics/
│   │   └── bankroll.py           # Kelly sizing + Monte Carlo simulation
│   │
│   ├── notifications/
│   │   ├── discord.py            # Discord webhook alerts (5 alert types)
│   │   └── alerts.py             # Alert dedup manager (in-memory)
│   │
│   └── db.py                     # Supabase PostgREST client (persistent httpx.Client)
│
├── shared/
│   └── config.py                 # Central configuration constants
│
├── CLAUDE.md                     # Project instructions
├── BUGFIX_REPORT.md              # Previous session bug fixes
└── .env                          # Environment variables
```

---

## 2. Database Schema (Supabase / PostgreSQL)

### Tables

| Table | Purpose | Key Columns |
|---|---|---|
| `games` | All tracked games across sports | `game_id` (PK), `sport`, `home_team`, `away_team`, `start_time`, `status`, `home_score`, `away_score` |
| `ev_opportunities` | +EV betting opportunities per scan | `id`, `game_id` (FK), `sportsbook`, `market_type`, `side`, `book_odds`, `true_prob`, `ev_percentage`, `kelly_fraction`, `recommended_units`, `status`, `timestamp`, `commence_time`, `sport` |
| `line_movements` | Odds changes across all books | `id`, `game_id` (FK), `sport`, `bookmaker`, `market_type`, `side`, `odds`, `previous_odds`, `odds_change`, `timestamp` |
| `steam_alerts` | Steam move detections (3+ books) | `id`, `game_id` (FK), `sport`, `market_type`, `side`, `direction`, `books_moved`, `magnitude`, `first_move_time`, `detected_at`, `status` |
| `true_lines` | Devigged sharp book probabilities | `id`, `game_id` (FK), `market_type`, `true_home_prob`, `true_away_prob`, `sharp_book`, `no_vig_line`, `timestamp` |
| `odds_snapshots` | Raw odds from every sportsbook pull | `id`, `game_id` (FK), `sportsbook`, `market_type`, `home_odds`, `away_odds`, `spread_value`, `total_value` |
| `clv_records` | Closing Line Value tracking | `id`, `game_id` (FK), `sport`, `sportsbook`, `market_type`, `side`, `bet_odds`, `bet_true_prob`, `ev_at_bet`, `closing_odds`, `clv_percentage`, `status` |
| `bet_results` | Graded bet outcomes | `id`, `ev_opportunity_id` (FK), `result` (win/loss/push), `profit_loss`, `graded_at` |
| `rtm_signals` | Confluence model signals | `id`, `game_id` (FK), `sport`, `market_type`, `side`, `sportsbook`, `book_odds`, `signal_strength`, `star_rating`, `ev_score`, `steam_score`, `projection_score`, `consensus_score`, `edge_percentage`, `kelly_size`, `status` |

**Note:** Supabase queries blocked by egress proxy in this environment. Row counts could not be verified directly. The scanner running in Terminal 1 continuously populates these tables.

---

## 3. Scan Pipeline (odds_scraper.py)

The scanner runs every **10 minutes** via APScheduler. Each cycle:

1. **Fetch mainlines** (h2h, spreads, totals) for ALL upcoming games across 15 sports
2. **Fetch props** — only for games within 18h and sports with configured prop markets
3. **Persist to DB:** games, odds_snapshots, true_lines
4. **Store line movements** — compare to previous odds, only store changes
5. **Scan for +EV** — mainlines for all games, props for near-term only
6. **Bulk-insert EV opportunities** with shared timestamp
7. **CLV record creation** — seed CLV tracking for new EV opps
8. **CLV processing** — close records for started games, expire stale records
9. **Steam detection** — 3+ books moving same direction within 30min window
10. **Score fetching** — update completed games with final scores
11. **Auto-grading** — grade EV opps for final games (WIN/LOSS/PUSH)
12. **RTM Signal generation** — confluence model scoring
13. **Signal grading** — grade signals for completed games
14. **Discord alerts** — EV alerts (5%+ threshold) and signal alerts (4+ stars)

---

## 4. Signal Engine Analysis (CRITICAL)

### Current Implementation (`rtm_signal_engine/rtm_signal.py`)

**4 scoring components** (0-100 each):
- `ev_score`: Based on EV% tiers (1%→20, 3%→40, 5%→60, 8%→80, 12%→100)
- `steam_score`: Based on steam alert confirmation for matching game/side/market
- `projection_score`: Monte Carlo simulation vs line (props only)
- `consensus_score`: Count of books with confirming line movements

**Weights:**
- Game lines: ev=0.40, steam=0.30, projection=0.00, consensus=0.30
- Player props: ev=0.25, steam=0.20, projection=0.35, consensus=0.20

**Thresholds:**
- 75+ → 5 stars (STRONG SIGNAL)
- 60+ → 4 stars (SIGNAL)
- 45+ → 3 stars (LEAN)
- <45 → no signal

### BUG #1 — Wrong Table Name (CRITICAL)

`_get_steam_alerts()` (line 413) and `load_cache()` (line 451) query table `"steam_moves"` — but the actual table is `"steam_alerts"`. This causes a silent 404/exception → steam_score is **always 0**.

### BUG #2 — Scoring Too Aggressive for Game Lines

With steam always 0 (BUG #1) and projection always 0 (game lines don't use projections):
- Max possible signal_strength = ev_score * 0.40 + consensus * 0.30
- Even best case: 100 * 0.40 + 80 * 0.30 = 40 + 24 = **64** (barely 4 stars)
- Typical case: 40 * 0.40 + 30 * 0.30 = 16 + 9 = **25** (well below 45 threshold)

**Result: 0 signals generated.** The combination of wrong table name + high thresholds + stepwise scoring gaps means almost nothing passes.

### BUG #3 — Consensus Checks Wrong Direction

`market_consensus_score()` counts books where `odds_change < 0` (odds shortened). But "shortened" can mean different things depending on which side you're on. The logic doesn't properly map "confirming" vs "contrary" movements relative to the bet side.

---

## 5. API Endpoint Map

### Active Endpoints (16 routers, 30+ endpoints)

| Router | Prefix | Endpoints |
|---|---|---|
| ev | `/api/ev-opportunities` | `GET /` — latest +EV opportunities |
| signal | `/api/signals` | `GET /active`, `GET /history`, `GET /performance`, `GET /projection/{id}` |
| steam_alerts | `/api/steam-alerts` | `GET /` — recent steam alerts |
| sharp_dashboard | `/api/sharp-dashboard` | `GET /` — combined dashboard |
| line_movements | `/api/line-movements` | `GET /`, `GET /{game_id}` |
| props | `/api/props` | `GET /`, `GET /types` |
| odds_screen | `/api/odds-screen` | `GET /`, `GET /{sport}` |
| performance | `/api/performance` | `GET /summary`, `GET /results`, `GET /by-sport`, `GET /by-book`, `POST /recalculate` |
| clv | `/api/clv` | `GET /`, `GET /summary` |
| recap | `/api/recap` | `GET /today`, `GET /yesterday`, `GET /date/{date}`, `GET /recent`, `GET /morning-briefing` |
| bankroll | `/api/bankroll` | `POST+GET /size`, `POST /size-batch`, `POST+GET /simulate` |
| usage | `/api/usage` | `GET /` |
| picks | `/api/picks` | `GET /` (stub) |
| odds | `/api/odds` | `GET /` (stub) |
| models | `/api/models` | `GET /` (stub) |
| copilot | `/api/copilot` | `POST /chat` (stub) |

### Health + Root

- `GET /health` → `{"status": "ok", "service": "rtm-picks-api"}`
- `GET /` → Redirect to `/dashboard.html`

---

## 6. Frontend Page Map

| Page | API Calls | Auto-Refresh |
|---|---|---|
| `dashboard.html` | `GET /api/ev-opportunities/` | 60s |
| `signal.html` | `GET /api/signals/active`, `/history`, `/performance` | 60s |
| `sharp-tracker.html` | `GET /api/sharp-dashboard/`, `/api/line-movements/`, `/api/line-movements/{id}` | 60s |
| `props.html` | `GET /api/props/` | 60s |
| `odds-screen.html` | `GET /api/odds-screen/{sport}` | 120s |
| `performance.html` | `GET /api/performance/summary`, `/results`, `/by-sport`, `/api/signals/performance` | 60s |
| `clv-report.html` | `GET /api/clv/summary`, `/api/clv/` | 120s |
| `daily-recap.html` | `GET /api/recap/date/{date}` | none |
| `bankroll.html` | `POST /api/bankroll/size`, `/size-batch`, `/simulate` | none |

All 9 pages have identical nav bars. All frontend fetch URLs match backend routes.

---

## 7. Configuration (`shared/config.py`)

| Constant | Value | Notes |
|---|---|---|
| `ODDS_API_SPORT_KEYS` | 15 sports | MLB, NBA, NFL, NHL, CFB, CBB, WNBA, 8 tennis Grand Slams |
| `SHARP_BOOKS` | pinnacle, circa, betonlineag | In preference order |
| `MARKETS` | h2h, spreads, totals | Mainline markets |
| `PROP_MARKETS` | 13 types | All player prop types |
| `SPORT_PROP_MARKETS` | Basketball: 7, Football: 13, Hockey: 4 | Sport-specific subsets |
| `DEFAULT_KELLY_FRACTION` | 0.25 | Quarter Kelly |
| `MIN_EV_THRESHOLD` | 1.0% | Minimum to surface a pick |
| `MIN_GRADE_EV_THRESHOLD` | 3.0% | Minimum to grade/track a bet |
| `MIN_ALERT_EV_THRESHOLD` | 5.0% | Minimum for Discord alert |

### Missing from config (hardcoded in various files):
- Signal thresholds (hardcoded in rtm_signal.py: 75/60/45)
- Signal weights (hardcoded in rtm_signal.py)
- Scan interval (hardcoded in odds_scraper.py: 10 min)
- Prop window hours (hardcoded: 18h)
- Steam detection parameters (min books: 3, window: 30min, dedup: 60min)
- Bankroll units (hardcoded: 100)
- Unit clamp range (hardcoded: 0.1 to 5.0)

---

## 8. Known Issues & Bugs

### Critical

1. **Signal Engine produces 0 signals** — Wrong table name (`steam_moves` vs `steam_alerts`), scoring thresholds too high, consensus scoring direction ambiguous
2. **Egress proxy blocks Supabase** — Container environment proxy returns 403 for all outbound HTTPS to Supabase. Scanner works in Terminal 1 (different network path).

### Moderate

3. **In-memory alert dedup** — Alert dedup sets (`alerts.py`) lost on restart. No persistence. Unbounded growth.
4. **Projection engine NBA-only** — Only uses mock data or NBA.com stats. CBB/NHL/NFL/CFB have no real projections.
5. **CLV `get_closing_sharp_line` returns None** — Line 262 explicitly `return None` with comment "Needs game context to map side -> prob". Function never used but exists.
6. **No input validation** — EV calculator, Kelly, and odds functions don't validate inputs.

### Minor

7. **4 stub routers** — picks, odds, models, copilot — registered but non-functional
8. **Client-side date_to filtering** — Performance results filter `date_to` in Python, not in PostgREST query
9. **Hardcoded signal projection defaults** — opponent="BOS", home_away="home"
10. **Discord embed size** — No validation against Discord's 6000-char embed limit

---

## 9. Data Flow Diagram

```
The Odds API
     │
     ▼
odds_scraper.py (every 10 min)
     │
     ├─► games table
     ├─► odds_snapshots table
     ├─► true_lines table
     ├─► line_movements table
     ├─► ev_opportunities table
     │        │
     │        ├─► clv_records table
     │        ├─► bet_results table (after game final)
     │        └─► rtm_signals table (BROKEN — 0 signals)
     │
     ├─► steam_alerts table
     ├─► score_fetcher → games table (scores)
     └─► Discord webhooks
              │
              ├─► EV alerts (5%+ threshold)
              ├─► Steam alerts
              ├─► Signal alerts (4+ stars)
              ├─► Daily recaps
              └─► Morning briefings

FastAPI (api/main.py)
     │
     ├─► 16 routers → Supabase queries
     └─► Static file serving → frontend/*.html
```

---

## 10. Environment

- **Python:** 3.11+
- **Key dependencies:** FastAPI, httpx, APScheduler, python-dotenv, nba_api
- **Database:** Supabase (PostgreSQL + PostgREST)
- **External APIs:** The Odds API, Discord Webhooks
- **Hosting target:** Railway (backend workers), Vercel (frontend)

---

## 11. Priority Action Items

1. **FIX SIGNAL ENGINE** — Fix table name, recalibrate scoring, lower thresholds (Milestone 2)
2. **Frontend testing** — Verify all 9 pages with live data (Milestone 3)
3. **Data integrity verification** — Manual EV math check, line movement quality (Milestone 4)
4. **Centralize configuration** — Move all hardcoded values to shared/config.py (Milestone 5)
5. **Signal page premium redesign** — Make it worth $200/month (Milestone 6)
6. **Odds screen research tool** — Game comparison grid with vig calculator (Milestone 7)
7. **Documentation** — BUILD_REPORT_6.md, README update (Milestone 8)
