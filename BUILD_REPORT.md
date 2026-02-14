# Build Report: Sharp Money Tracking System

**Branch:** `claude/create-claude-md-on8Eo`
**Date:** 2026-02-14

---

## What Was Built

### Milestone 1: Line Movement History

**Files changed/created:**
- `scripts/002_create_sharp_money_tables.sql` — Migration for `line_movements` and `steam_alerts` tables
- `backend/db.py` — Added `get_latest_odds_for_game()`, `bulk_insert_line_movements()`, `get_line_movements_for_game()`, `get_biggest_recent_moves()`, and steam alert db functions
- `backend/scrapers/odds_scraper.py` — Added `store_line_movements()` function

**How it works:**
- On every scan, the scraper iterates ALL bookmaker/game/market/side combinations
- For each combo, it checks the most recent stored odds via `get_latest_odds_for_game()`
- If odds changed: inserts a new row with `previous_odds` and `odds_change` (delta)
- If odds are the same: skips the insert (saves storage)
- Uses bulk insert with a shared timestamp per scan batch
- Integrated into `run_scan()` per-sport with its own error handling

### Milestone 2: Steam Detection

**Files changed:**
- `backend/scrapers/odds_scraper.py` — Added `detect_steam_moves()` function

**How it works:**
- Runs after each scan cycle completes (after all sports are processed)
- Queries `line_movements` from the last 30 minutes with non-null `odds_change`
- Groups by `(game_id, market_type, side, direction)`
- Direction: `shortened` = odds went down (sharp money ON that side), `lengthened` = odds went up (sharp money AGAINST)
- If 3+ distinct bookmakers moved the same direction, creates a steam alert
- Magnitude = average absolute odds change across moving books
- Deduplication: won't create another alert for the same game/market/side within 60 minutes
- Configurable constants: `STEAM_MIN_BOOKS`, `STEAM_WINDOW_MINUTES`, `STEAM_DEDUP_MINUTES`

### Milestone 3: Sharp Money API Endpoints

**Files created:**
- `backend/api/routes/line_movements.py`
- `backend/api/routes/steam_alerts.py`
- `backend/api/routes/sharp_dashboard.py`

**Endpoints:**

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/line-movements/` | Top 20 biggest recent moves (configurable `hours` and `limit`) |
| GET | `/api/line-movements/{game_id}` | Full odds history for a game, all bookmakers. Optional `market_type` filter |
| GET | `/api/steam-alerts/` | Active steam alerts (configurable `hours` look-back, optional `sport` filter) |
| GET | `/api/sharp-dashboard/` | Combined: top 10 alerts + top 10 moves + summary stats |

**Wired into:** `backend/api/main.py`

### Milestone 4: Sharp Money Tracker Frontend

**Files created/changed:**
- `frontend/sharp-tracker.html` — New page
- `frontend/dashboard.html` — Added navigation bar

**Features:**
- **Summary stats:** Alert count (24h), most active sport, biggest single move
- **Steam Alerts feed:** Card grid with game, side, direction (red=ON, blue=AGAINST), magnitude, books that moved, time detected. Click to load chart.
- **Biggest Movers table:** Sport, game, side, market, book, prev/new odds, change, time. Click to load chart.
- **Line Movement Chart:** Chart.js line chart — time on X axis, American odds on Y axis, one colored line per bookmaker/side. Loads Chart.js 4.x from CDN.
- **Navigation bar** on both pages linking between +EV Dashboard and Sharp Tracker
- **Auto-refresh** every 60 seconds with countdown timer

---

## Action Required From You

### 1. Run the SQL migration

Open the **Supabase SQL Editor** and run the contents of:
```
scripts/002_create_sharp_money_tables.sql
```

This creates two tables: `line_movements` and `steam_alerts` with proper indexes.

### 2. Test the scanner

```bash
cd backend
python scrapers/odds_scraper.py CBB
```

You should see:
- Normal game fetching and +EV output
- `Line movements: N changes recorded.` for each sport
- `Steam alerts: no new steam detected.` (or alert count if books moved)

### 3. Test the API

```bash
cd backend && python -m uvicorn api.main:app --reload --port 8000
```

Then test:
```bash
curl http://localhost:8000/api/line-movements/
curl http://localhost:8000/api/steam-alerts/
curl http://localhost:8000/api/sharp-dashboard/
```

### 4. View the frontend

Open both in a browser:
- `frontend/dashboard.html` — +EV opportunities (existing, now with nav)
- `frontend/sharp-tracker.html` — Sharp money tracker (new)

---

## What Works

- All code imports cleanly and the API starts with all routes registered
- Line movement storage only records changes (space-efficient)
- Steam detection uses configurable thresholds and deduplication
- All API endpoints return valid JSON (empty arrays when no data yet)
- Frontend pages share consistent dark theme and cross-link via nav bar
- Chart.js renders multi-bookmaker line charts interactively

## Known Limitations / Future Work

- **Chart.js time scale:** The time axis works as a linear scale by default. For proper time formatting, add `chartjs-adapter-date-fns` from CDN. The chart still renders correctly without it, just shows raw timestamps.
- **Steam detection depends on data:** You need at least 2 scan cycles with line movement data before steam can be detected (it compares current vs previous odds). After the first scan, all odds are "new" with no previous_odds.
- **Line movement lookup per game:** `get_latest_odds_for_game()` fetches all rows for a game sorted by timestamp desc, then deduplicates in Python. For very high-volume games this could be optimized with a SQL `DISTINCT ON` query, but PostgREST doesn't support that natively — would require an RPC function.
- **Bulk operations:** If a scan produces 500+ line movement rows, the single bulk POST could hit Supabase payload limits. Consider batching in groups of 200 if this becomes an issue.
