# Build Report 2: Overnight Build — Props, Scheduler, CLV, Deployment

**Branch:** `claude/create-claude-md-on8Eo`
**Date:** 2026-02-15

---

## What Was Built

### Milestone 1: Player Props Scanning

**Files changed/created:**
- `backend/scrapers/odds/odds_api.py` — Added `description` field to `Outcome` dataclass
- `backend/scrapers/odds_scraper.py` — Added `scan_game_props()`, `_build_prop_sharp_map()`, `print_prop_results()`
- `shared/config.py` — Added `PROP_MARKETS` (13 markets) and `ALL_MARKETS`

**How it works:**
- Props use a different response structure: outcomes have a `description` field for the player name
- `_build_prop_sharp_map()` groups outcomes by `(description, point)` to find Over/Under pairs, then devigs them
- `scan_game_props()` iterates all 13 prop markets on the sharp book, builds true probabilities, then compares against soft books
- Selection format: `"Player Name Over/Under X.X"`
- Console output groups props by type (Points, Rebounds, etc.) with a dedicated table format
- `store_line_movements` includes player name in the `side` field for prop tracking

**Prop markets supported:**
`player_points`, `player_rebounds`, `player_assists`, `player_threes`, `player_blocks`, `player_steals`, `player_points_rebounds_assists`, `player_pass_tds`, `player_pass_yds`, `player_rush_yds`, `player_receptions`, `player_reception_yds`, `player_anytime_td`

### Milestone 2: Dashboard Filters and Props Display

**Files changed:**
- `frontend/dashboard.html` — Complete rewrite with filtering system

**Features:**
- **Filter dropdowns:** Sport, Sportsbook, Market (Game Lines / Player Props / h2h / spreads / totals), Min EV%
- **Search box:** Filter by team or player name
- **Client-side filtering:** All filters applied without page reload via `applyFilters()`
- **Dynamic filter population:** Sport and Sportsbook dropdowns populated from data with counts
- **Props display:** Colored `<span class="prop-tag">` in the Market column for prop bets
- **Preserved selections:** Auto-refresh (60s) preserves current filter state
- **Stats card:** Shows "Props" count instead of "Sports"

### Milestone 3: Smart API Scheduling

**Files created:**
- `backend/scrapers/scheduler.py` — Smart scheduling engine
- `backend/api/routes/usage.py` — API usage tracking endpoint

**How it works:**
- **Game proximity scheduling:** Scan interval ramps up as games approach:
  - 0–30 min before start: every 2 minutes
  - 30–60 min: every 5 minutes
  - 1–3 hours: every 10 minutes
  - 3–6 hours: every 20 minutes
  - 6–12 hours: every 30 minutes
  - 12–24 hours: every 60 minutes
- **Game schedule checking:** Queries Supabase `games` table for today's games per sport
- **Budget management:** Tracks API requests in `.api_usage.json`, auto-resets monthly
  - Default budget: 500 requests/month (The Odds API free tier)
  - If over budget: prioritizes sports by closest game start
- **CLI flags:**
  - `--dry-run`: Show schedule plan without executing scans
  - `--once`: Run a single smart scan and exit
  - No flags: Continuous loop with smart intervals

**Endpoint:**

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/usage/` | Current month's API usage, budget remaining, per-sport breakdown |

### Milestone 4: CLV Tracking

**Files created:**
- `scripts/003_clv_tracking.sql` — Migration for `clv_records` table
- `backend/scrapers/clv_tracker.py` — CLV tracking engine
- `backend/api/routes/clv.py` — CLV API endpoints
- `frontend/clv-report.html` — CLV Report dashboard

**How it works:**
- **Record creation:** When `run_scan()` finds +EV opportunities, CLV records are created with `status='open'`
- **Deduplication:** Won't create duplicate records for the same game/book/market/side
- **Closing line capture:** On subsequent scans after game start, fetches the most recent odds from `line_movements` as the "closing" line
- **CLV calculation:** `(closing_implied_prob - bet_implied_prob) / bet_implied_prob * 100`
  - Positive CLV = we got better odds than closing (edge confirmed)
  - Negative CLV = line moved against us
- **Expiration:** Records for games 48h+ past start without closing odds are expired
- **Summary stats:** Average CLV, positive CLV %, average EV at bet time, per-sport breakdown

**Endpoints:**

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/clv/` | CLV records with sport, hours, status filters |
| GET | `/api/clv/summary` | Aggregate CLV statistics (configurable days window) |

**Frontend (`clv-report.html`):**
- Summary stat cards: Total records, Average CLV, Positive CLV %, Avg EV at Bet
- Per-sport breakdown cards
- CLV Distribution histogram (Chart.js bar chart, green/red bins)
- CLV Over Time scatter plot with running average line
- Filterable records table with status badges
- 2-minute auto-refresh

### Milestone 5: Deployment Preparation

**Files created:**
- `backend/Dockerfile` — Python 3.11-slim container
- `docker-compose.yml` — Three services: `api`, `scanner`, `clv-worker`
- `Procfile` — Railway/Heroku deployment (web, worker, clv)
- `.env.example` — All required environment variables

**Changes:**
- Frontend API URLs made configurable (auto-detect localhost vs production)

**Docker services:**
- `api` — FastAPI server on port 8000 with hot-reload
- `scanner` — Smart scheduler running continuously
- `clv-worker` — CLV processor running every 5 minutes

### Milestone 6: Polish and Integration Testing

**Tests performed:**
- Full import chain: all 10 API routers, scraper, scheduler, CLV tracker load cleanly
- API server starts and binds successfully
- Mock game scan: 4 game line + 2 prop opportunities correctly detected
- Scheduler display: budget tracking, proximity intervals, skip logic verified
- CLV calculation: 5 test scenarios all passed (positive/negative CLV for favorites and underdogs)
- All Python files pass `py_compile` check

---

## Action Required From You

### 1. Run the SQL migration for CLV

Open the **Supabase SQL Editor** and run:
```
scripts/003_clv_tracking.sql
```

This creates the `clv_records` table with proper indexes.

### 2. Test the scanner with props

```bash
cd backend
python scrapers/odds_scraper.py NBA
```

You should see game line AND player prop opportunities in the output.

### 3. Test the smart scheduler

```bash
cd backend
python scrapers/scheduler.py --dry-run
```

This shows which sports would be scanned and their intervals without using API credits.

### 4. Test CLV stats

```bash
cd backend
python scrapers/clv_tracker.py --stats
```

After a few scan cycles and game starts, this will show CLV summary.

### 5. Test all API endpoints

```bash
cd backend && python -m uvicorn api.main:app --reload --port 8000
```

Then test:
```bash
curl http://localhost:8000/api/ev-opportunities/
curl http://localhost:8000/api/line-movements/
curl http://localhost:8000/api/steam-alerts/
curl http://localhost:8000/api/sharp-dashboard/
curl http://localhost:8000/api/usage/
curl http://localhost:8000/api/clv/
curl http://localhost:8000/api/clv/summary
```

### 6. View all frontends

Open in a browser:
- `frontend/dashboard.html` — +EV Dashboard with filters
- `frontend/sharp-tracker.html` — Sharp Money Tracker
- `frontend/clv-report.html` — CLV Report

All three pages cross-link via the navigation bar.

---

## Complete API Endpoint Summary

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| GET | `/api/ev-opportunities/` | Latest +EV opportunities (filterable) |
| GET | `/api/line-movements/` | Top biggest recent line moves |
| GET | `/api/line-movements/{game_id}` | Full odds history for a game |
| GET | `/api/steam-alerts/` | Active steam alerts |
| GET | `/api/sharp-dashboard/` | Combined sharp money dashboard data |
| GET | `/api/usage/` | API usage stats and budget |
| GET | `/api/clv/` | CLV records (filterable) |
| GET | `/api/clv/summary` | CLV summary statistics |

---

## Architecture Overview

```
Scan Pipeline:
  scheduler.py → odds_scraper.py → odds_api.py → The Odds API
                      ↓
              ┌───────┴───────────┐
              ↓                   ↓
         Game Lines          Player Props
         scan_game()      scan_game_props()
              ↓                   ↓
              └───────┬───────────┘
                      ↓
              +EV Opportunities
                      ↓
         ┌────────────┼────────────┐
         ↓            ↓            ↓
   Supabase DB   CLV Tracker   Console Output
   (ev_opps,     (clv_records)  (formatted tables)
    line_movs,
    steam_alerts)
                      ↓
              CLV Processing
         (close records on game start)
```

## Known Limitations / Future Work

- **CLV side-matching:** For h2h/spreads CLV, the `side` field is a team name. The current CLV tracker uses `line_movements` to find closing odds by exact side match, which works. For a more precise CLV, we could use `true_lines` and map side to home/away probability.
- **Props CLV:** Player prop CLV works through `line_movements` since props store the full `"Player Name Over X.X"` as the side.
- **Docker `shared/` volume:** The Dockerfile `COPY ../shared` won't work in Docker build context. The `docker-compose.yml` mounts it as a volume instead, which is the intended usage.
- **Scheduler game check:** `check_sport_schedule()` queries Supabase for games. If no games have been scanned yet (fresh database), it falls back to scanning everything (safe default).
- **API budget:** The 500 request/month budget assumes The Odds API free tier. Update `MONTHLY_API_BUDGET` in scheduler.py if on a paid plan.
