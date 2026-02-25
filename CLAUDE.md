# RTM Picks Platform

## Project Overview
AI-powered sports betting intelligence platform hosted on Whop.
Covers MLB, NBA, NFL, NHL, CFB, CBB.
Features: +EV engine, proprietary prediction models, AI co-pilot, personalized bankroll management.

## Tech Stack
- Frontend: Next.js 14+ with TypeScript, Tailwind CSS, hosted on Vercel
- Backend: Python 3.11+ with FastAPI
- Database: Supabase (PostgreSQL with TimescaleDB extension)
- Cache: Upstash Redis
- Odds Data: The Odds API
- Stats Data: pybaseball (MLB), nba_api (NBA), nfl_data_py (NFL), NHL API
- AI: Claude API (Sonnet 4.5) for co-pilot features
- Auth/Payments: Whop SDK
- Hosting: Vercel (frontend), Supabase Edge Functions + Railway (backend workers)

## Project Structure
```
/frontend                    - Next.js 14 Whop app (TypeScript)
/frontend/app/               - App Router pages
/frontend/app/dashboard/     - Main dashboard (active signals, bankroll, odds tables)
/frontend/app/picks/         - Signal card grid with KenPom projections
/frontend/app/ev-scanner/    - Real-time +EV scanner across all books
/frontend/app/kenpom/        - KenPom edge finder for CBB
/frontend/app/performance/   - Historical results & ROI tracking
/frontend/app/settings/      - Settings (stub)
/frontend/components/        - Shared components (sidebar, bankroll provider)
/frontend/lib/               - API client, bankroll context

/backend                     - Python FastAPI service
/backend/api/                - FastAPI app setup & CORS
/backend/api/routes/         - API route handlers (18 route files)
/backend/scrapers/           - Odds pipeline, grading, CLV tracking
/backend/scrapers/odds/      - The Odds API wrapper (Game/Market/Outcome dataclasses)
/backend/scrapers/scores/    - Game score fetching
/backend/models/             - Devig engine, EV calculator, Kelly criterion
/backend/rtm_signal_engine/  - RTM confluence model & signal grading
/backend/intelligence/       - Stale detector, book profiler, market timing, KenPom
/backend/projections/        - NBA player projection engine & Monte Carlo simulator
/backend/notifications/      - Discord webhooks, daily recaps
/backend/analytics/          - Bankroll management analytics
/backend/tests/              - pytest test suite (7 test files, ~2700 lines)

/shared                      - Shared types and configuration
/shared/config.py            - All thresholds, sport keys, book lists, API settings
/shared/config.ts            - TypeScript mirror for frontend
/shared/books.py             - Bookmaker registry (40+ books with tiers/weights)
/scripts                     - SQL migration files (001-009)
```

## Coding Standards
- Python: Type hints on all functions, docstrings, pytest for testing
- TypeScript: Strict mode, ESLint, Prettier
- All database queries use parameterized statements
- Every prediction model must have a backtest before deployment
- Use environment variables for all API keys and secrets (never hardcode)
- Write clear commit messages describing what changed and why

## Key Business Rules
- The +EV engine compares sportsbook odds to sharp book (Pinnacle/Circa) no-vig lines
- Positive EV = when a book's implied probability is lower than the true probability
- All picks must be timestamped and recorded for transparent performance tracking
- Closing Line Value (CLV) is the gold standard metric for proving edge
- Unit sizing follows Kelly Criterion (fractional Kelly for safety)
- RTM Signals use 1-unit flat bets (not kelly-sized)
- EV Opportunities use kelly-sized recommended_units for grading

## Current Phase
Phase 2: Multi-sport +EV engine, RTM signal confluence model, performance tracking

---

## Database Schema (Supabase PostgreSQL)

### 14 Tables, 50 Indexes

#### games (Migration 001) - Core game schedule
| Column | Type | Notes |
|--------|------|-------|
| game_id | TEXT PK | The Odds API game identifier |
| sport | TEXT NOT NULL | e.g. "basketball_nba" |
| home_team | TEXT NOT NULL | |
| away_team | TEXT NOT NULL | |
| start_time | TIMESTAMPTZ NOT NULL | Game start (NOT "commence_time") |
| status | TEXT DEFAULT 'upcoming' | upcoming, live, final |
| home_score | INTEGER | NULL until final |
| away_score | INTEGER | NULL until final |
| created_at | TIMESTAMPTZ DEFAULT now() | |

Indexes: sport, start_time, status

#### odds_snapshots (Migration 001) - Raw odds time-series
| Column | Type | Notes |
|--------|------|-------|
| id | BIGINT IDENTITY PK | |
| game_id | TEXT FK→games | |
| sportsbook | TEXT NOT NULL | |
| market_type | TEXT NOT NULL | h2h, spreads, totals |
| home_odds | NUMERIC NOT NULL | Home team or Over odds |
| away_odds | NUMERIC NOT NULL | Away team or Under odds |
| spread_value | NUMERIC | |
| total_value | NUMERIC | |
| timestamp | TIMESTAMPTZ DEFAULT now() | |

Indexes: game_id, timestamp

#### true_lines (Migration 001) - Devigged sharp probabilities
| Column | Type | Notes |
|--------|------|-------|
| id | BIGINT IDENTITY PK | |
| game_id | TEXT FK→games | |
| market_type | TEXT NOT NULL | |
| true_home_prob | NUMERIC NOT NULL | Home/Over true probability |
| true_away_prob | NUMERIC NOT NULL | Away/Under true probability |
| sharp_book | TEXT NOT NULL | Devig source book |
| no_vig_line | NUMERIC | |
| timestamp | TIMESTAMPTZ DEFAULT now() | |

Indexes: game_id

#### ev_opportunities (Migration 001) - +EV betting opportunities
| Column | Type | Notes |
|--------|------|-------|
| id | BIGINT IDENTITY PK | |
| game_id | TEXT FK→games | |
| sportsbook | TEXT NOT NULL | |
| market_type | TEXT NOT NULL | |
| side | TEXT NOT NULL | e.g. "Team A -3.5", "Over 210.5" |
| book_odds | NUMERIC NOT NULL | American odds |
| book_implied_prob | NUMERIC NOT NULL | |
| true_prob | NUMERIC NOT NULL | From devig |
| ev_percentage | NUMERIC NOT NULL | |
| kelly_fraction | NUMERIC NOT NULL | |
| recommended_units | NUMERIC NOT NULL | Kelly-based units |
| timestamp | TIMESTAMPTZ DEFAULT now() | |
| status | TEXT DEFAULT 'open' | open, expired, graded |

Indexes: status, game_id, timestamp

#### bet_results (Migration 001, 004) - Graded EV opportunity outcomes
| Column | Type | Notes |
|--------|------|-------|
| id | BIGINT IDENTITY PK | |
| ev_opportunity_id | BIGINT FK→ev_opportunities | |
| result | TEXT NOT NULL | win, loss, push |
| closing_line | NUMERIC | |
| closing_line_value | NUMERIC | |
| profit_loss | NUMERIC | Kelly-based units |
| graded_at | TIMESTAMPTZ | |

Indexes: ev_opportunity_id, graded_at, result

#### line_movements (Migration 002) - Odds change tracking
| Column | Type | Notes |
|--------|------|-------|
| id | BIGINT IDENTITY PK | |
| game_id | TEXT FK→games | |
| sport | TEXT NOT NULL | |
| bookmaker | TEXT NOT NULL | |
| market_type | TEXT NOT NULL | |
| side | TEXT NOT NULL | |
| odds | NUMERIC NOT NULL | |
| previous_odds | NUMERIC | |
| odds_change | NUMERIC | |
| timestamp | TIMESTAMPTZ DEFAULT now() | |

Indexes: game_id, timestamp, (game_id,bookmaker,market_type,side), odds_change

#### steam_alerts (Migration 002) - Sharp money detection
| Column | Type | Notes |
|--------|------|-------|
| id | BIGINT IDENTITY PK | |
| game_id | TEXT FK→games | |
| sport, market_type, side, direction | TEXT | |
| books_moved | JSONB DEFAULT '[]' | |
| magnitude | NUMERIC NOT NULL | |
| first_move_time | TIMESTAMPTZ NOT NULL | |
| detected_at | TIMESTAMPTZ DEFAULT now() | |
| status | TEXT DEFAULT 'active' | |

Indexes: game_id, detected_at, status

#### clv_records (Migration 003) - Closing Line Value tracking
| Column | Type | Notes |
|--------|------|-------|
| id | BIGINT IDENTITY PK | |
| game_id | TEXT FK→games | |
| sport, sportsbook, market_type, side | TEXT | |
| bet_odds | NUMERIC NOT NULL | Odds at bet time |
| bet_true_prob | NUMERIC NOT NULL | Devigged prob at bet time |
| closing_odds | NUMERIC | Odds at game start |
| closing_true_prob | NUMERIC | Devigged prob at close |
| clv_percentage | NUMERIC | (closing-bet)/bet * 100 |
| ev_at_bet | NUMERIC NOT NULL | |
| bet_timestamp | TIMESTAMPTZ NOT NULL | |
| closing_timestamp | TIMESTAMPTZ | |
| status | TEXT DEFAULT 'open' | open, closed, expired |
| created_at | TIMESTAMPTZ DEFAULT now() | |

Indexes: game_id, sport, status, created_at, clv_percentage

#### rtm_signals (Migrations 005, 006, 007) - RTM confluence signals
| Column | Type | Notes |
|--------|------|-------|
| id | BIGINT IDENTITY PK | |
| game_id | TEXT NOT NULL | No FK to games |
| sport, market_type, side | TEXT NOT NULL | |
| player_name | TEXT | |
| prop_line | NUMERIC | |
| sportsbook | TEXT NOT NULL | |
| book_odds | NUMERIC NOT NULL | American odds |
| signal_strength | NUMERIC NOT NULL | 0-100 composite score |
| star_rating | INTEGER NOT NULL | 3-5 stars |
| ev_score | NUMERIC NOT NULL | |
| steam_score | NUMERIC NOT NULL | |
| projection_score | NUMERIC | |
| consensus_score | NUMERIC NOT NULL | |
| fair_odds | NUMERIC | |
| edge_percentage | NUMERIC NOT NULL | |
| kelly_size | NUMERIC | |
| intelligence_score | NUMERIC DEFAULT 0 | |
| intelligence_context | JSONB | |
| status | TEXT DEFAULT 'active' | active, graded, expired |
| result | TEXT | win, loss, push |
| profit_loss | NUMERIC | 1-unit flat bet P/L |
| bet_amount | NUMERIC DEFAULT 100 | Legacy column, unused for P/L |
| created_at | TIMESTAMPTZ DEFAULT now() | |
| graded_at | TIMESTAMPTZ | |

Indexes: game_id, created_at, signal_strength, star_rating, status

#### book_reaction_times (Migration 006) - Book speed tracking
| Column | Type | Notes |
|--------|------|-------|
| id | BIGINT IDENTITY PK | |
| game_id, sport, market_type, side | TEXT | |
| sharp_book | TEXT NOT NULL | |
| sharp_move_time | TIMESTAMPTZ NOT NULL | |
| soft_book | TEXT NOT NULL | |
| soft_move_time | TIMESTAMPTZ | |
| reaction_seconds | NUMERIC | |
| was_stale | BOOLEAN DEFAULT false | |
| edge_at_stale | NUMERIC | |
| created_at | TIMESTAMPTZ DEFAULT now() | |

Indexes: soft_book, sport, game_id

#### stale_line_alerts (Migration 006) - Stale line detection
| Column | Type | Notes |
|--------|------|-------|
| id | BIGINT IDENTITY PK | |
| game_id, sport, market_type, side | TEXT | |
| stale_book | TEXT NOT NULL | |
| stale_odds, consensus_odds | NUMERIC NOT NULL | |
| edge_percentage | NUMERIC NOT NULL | |
| stale_type | TEXT NOT NULL | |
| detected_at | TIMESTAMPTZ DEFAULT now() | |
| resolved_at | TIMESTAMPTZ | |
| status | TEXT DEFAULT 'active' | |
| bet_result | TEXT | |

Indexes: status, detected_at, stale_book

#### line_lifecycle (Migration 006) - Line opening→closing lifecycle
| Column | Type | Notes |
|--------|------|-------|
| id | BIGINT IDENTITY PK | |
| game_id, sport, market_type, side, sportsbook | TEXT | |
| first_seen_at, first_move_at, biggest_move_at, stabilized_at | TIMESTAMPTZ | |
| opening_odds, closing_odds | NUMERIC | |
| peak_edge | NUMERIC | |
| peak_edge_time | TIMESTAMPTZ | |
| game_start_time | TIMESTAMPTZ NOT NULL | |

Indexes: sport, game_start_time, game_id

#### kenpom_snapshots (Migration 008) - KenPom CBB projections
| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| snapshot_date | DATE NOT NULL | |
| game_id | TEXT NOT NULL | |
| sport | TEXT DEFAULT 'basketball_ncaab' | |
| home_team, away_team | TEXT NOT NULL | |
| commence_time | TIMESTAMPTZ | Note: this table uses commence_time |
| kp_home_score, kp_away_score | REAL | KenPom projected scores |
| kp_home_win_prob, kp_projected_total, kp_projected_spread | REAL | |
| pinnacle_spread_home, pinnacle_total | REAL | |
| pinnacle_home_ml, pinnacle_away_ml | INTEGER | |
| pinnacle_home_implied_prob | REAL | |
| spread_edge, total_edge, ml_edge | REAL | |
| result_home_score, result_away_score | INTEGER | |
| result_spread_correct, result_total_correct, result_ml_correct | BOOLEAN | |
| spread_unit_result, total_unit_result, ml_unit_result | REAL | |
| graded | BOOLEAN DEFAULT FALSE | |

UNIQUE: (snapshot_date, game_id)
Indexes: snapshot_date DESC, game_id, graded

#### pinnacle_odds_history (Migration 009) - Pinnacle opening/closing lines
| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| game_id, sport | TEXT NOT NULL | |
| home_team, away_team | TEXT NOT NULL | |
| commence_time | TIMESTAMPTZ | |
| market_type | TEXT NOT NULL | h2h, spreads, totals |
| line_value | REAL | Spread/total number, NULL for h2h |
| home_odds, away_odds | INTEGER | |
| over_odds, under_odds | INTEGER | Totals only |
| home_prob, away_prob | REAL | Devigged |
| snapshot_type | TEXT DEFAULT 'current' | opening, closing, current |
| captured_at | TIMESTAMPTZ DEFAULT NOW() | |
| snapshot_date | DATE NOT NULL | |

UNIQUE: (game_id, market_type, snapshot_type, snapshot_date)
Indexes: game_id, snapshot_date DESC, snapshot_type

### Foreign Key Map
```
games (parent)
 +-- odds_snapshots.game_id
 +-- true_lines.game_id
 +-- ev_opportunities.game_id
 +-- line_movements.game_id
 +-- steam_alerts.game_id
 +-- clv_records.game_id

ev_opportunities
 +-- bet_results.ev_opportunity_id  (FK prevents DELETE, must soft-delete)
```

---

## Scanner Pipeline (odds_scraper.py)

The main pipeline runs every 10 minutes and follows this flow:

```
1. FETCH ODDS        - The Odds API → mainline + prop markets per sport
2. MERGE PROPS       - Merge prop data into game objects
3. STORE RAW DATA    - games (upsert), odds_snapshots (insert), line_movements (batched)
4. DEVIG             - Hierarchical: Pinnacle → DK/FD → Exchanges → Market Avg
5. STORE TRUE LINES  - true_lines table with devig source + confidence
6. SCAN FOR +EV      - Compare soft book odds to true probs, filter by MIN_EV_THRESHOLD
7. STORE EV OPPS     - Bulk insert with shared timestamp
8. STEAM DETECTION   - 3+ books moving same direction within 30min
9. RTM SIGNALS       - Confluence model: EV + Steam + Projection + Consensus + Intel
10. CLEANUP          - Expire stale opps (>20min), expire signals for started games
11. SCORES & GRADING - Fetch final scores, grade EV opps + RTM signals
12. CLV TRACKING     - Compare bet odds to closing odds at game start
```

### Devig Hierarchy
| Tier | Books | Confidence |
|------|-------|------------|
| 1 (Sharp) | Pinnacle, Circa, Bookmaker | HIGH |
| 2 (Fallback) | DraftKings, FanDuel, BetOnline | MEDIUM |
| 3 (Exchange) | Novig, Betfair, Smarkets | LOW (requires 3+) |
| 4 (Market Avg) | All remaining books | LOW |

### RTM Signal Confluence Model (0-100 score)
Sport-adaptive weights:
- **NBA**: EV 25%, Steam 15%, Projection 25%, Consensus 15%, Intelligence 20%
- **CBB**: EV 30%, Steam 15%, Projection 20% (KenPom), Consensus 15%, Intelligence 20%
- **Other**: EV 40%, Steam 20%, Consensus 20%, Intelligence 20%

Signal tiers: 70+ = 5-star STRONG, 55+ = 4-star SIGNAL, 40+ = 3-star LEAN

### Profit/Loss Math
```
WIN at +150: units * (150/100) = +1.50u
WIN at -150: units * (100/150) = +0.667u
LOSS:        -units (always)
PUSH:        0.0u

RTM Signals: Always 1.0 unit flat bets
EV Opportunities: Kelly-sized recommended_units
```

---

## Terminal Commands

### Run Scanner
```bash
cd /home/user/Alpha/backend
python -m scrapers.odds_scraper                    # Scan in-season sports
python -m scrapers.odds_scraper --sports NBA CBB   # Specific sports
SCAN_ALL_SPORTS=1 python -m scrapers.odds_scraper  # All sports
```

### Run Tests
```bash
cd /home/user/Alpha/backend
python -m pytest tests/                            # All tests (~236 tests)
python -m pytest tests/ -v                         # Verbose output
python -m pytest tests/test_kelly.py               # Specific file
python -m pytest tests/test_devig.py::TestBalancedMarket  # Specific class
python -m pytest tests/ -k "kelly"                 # Pattern matching
```

### Run Backend API
```bash
cd /home/user/Alpha/backend
uvicorn api.main:app --reload --port 8000
```

### Run Frontend
```bash
cd /home/user/Alpha/frontend
npm run dev      # Dev server on :3000
npm run build    # Production build
npm run lint     # ESLint check
npx tsc --noEmit # TypeScript type check
```

### Database Migrations
```bash
# Run in Supabase SQL editor (scripts/001 through 009):
# 001_create_odds_tables.sql   - games, odds_snapshots, true_lines, ev_opportunities, bet_results
# 002_line_movements.sql       - line_movements, steam_alerts
# 003_clv_tracking.sql         - clv_records
# 004_bet_results_indexes.sql  - Additional indexes on bet_results
# 005_rtm_signal.sql           - rtm_signals
# 006_intelligence_tables.sql  - book_reaction_times, stale_line_alerts, line_lifecycle, intelligence columns on signals
# 007_signal_bet_amount.sql    - bet_amount column on rtm_signals
# 008_kenpom_snapshots.sql     - kenpom_snapshots
# 009_pinnacle_odds_history.sql - pinnacle_odds_history
```

---

## API Routes

### Signals & Picks
- `GET /api/signals/active` - Active RTM signals
- `GET /api/signals/history?days=30` - Graded signal history
- `GET /api/signals/performance?days=30` - Signal performance stats
- `GET /api/picks/` - Picks recommendations

### EV & Odds
- `GET /api/ev-opportunities/` - Current +EV opportunities (filterable: sport, min_ev, sportsbook)
- `GET /api/odds/` - Current odds data
- `GET /api/odds-screen/{sport}` - Odds comparison for sport

### Line Movement & Steam
- `GET /api/line-movements/` - Biggest recent moves
- `GET /api/steam-alerts/` - Active steam alerts (filterable: sport)
- `GET /api/sharp-dashboard/` - Sharp betting dashboard

### Performance & CLV
- `GET /api/performance/summary` - EV scanner performance
- `GET /api/clv/` - CLV records
- `GET /api/clv/summary` - CLV summary stats

### KenPom
- `GET /api/kenpom/today` - Today's CBB edges
- `GET /api/kenpom/tomorrow` - Tomorrow's CBB edges
- `GET /api/kenpom/performance/season` - Season accuracy
- `GET /api/kenpom/performance?days=30` - 30-day performance
- `GET /api/kenpom/edges?date={date}` - Historical edges

### Other
- `GET /api/recap/today` - Today's recap
- `GET /api/recap/yesterday` - Yesterday's recap
- `GET /api/copilot/chat` (POST) - AI co-pilot
- `GET /api/bankroll/` - Bankroll management
- `GET /api/usage/` - API usage stats
- `GET /health` - Health check

---

## Key Config Values (shared/config.py)

| Setting | Value | Purpose |
|---------|-------|---------|
| SCAN_INTERVAL_MINUTES | 10 | Scanner cycle frequency |
| MIN_EV_THRESHOLD | 1.0% | Minimum EV to surface opportunity |
| MIN_GRADE_EV_THRESHOLD | 3.0% | Minimum EV to grade as "play" |
| DEFAULT_KELLY_FRACTION | 0.25 | Quarter Kelly sizing |
| PROP_WINDOW_HOURS | 18.0 | Only scan props within 18h of start |
| STEAM_MIN_BOOKS | 3 | Min books for steam alert |
| STEAM_WINDOW_MINUTES | 30 | Steam detection window |
| MONTHLY_API_CREDITS | 100,000 | The Odds API budget |
| DAILY_CREDIT_BUDGET | 3,333 | Daily API budget |
| SHARP_BOOKS | pinnacle, circasports, bookmaker | Devig sources |
| SIGNAL_BET_AMOUNT | 100.0 | Legacy DB default (P/L uses 1.0 units) |

---

## Environment Variables

### Required (Backend)
- `SUPABASE_URL` - Supabase project URL
- `SUPABASE_SERVICE_KEY` - Service role key
- `THE_ODDS_API_KEY` - The Odds API key

### Required (Frontend)
- `NEXT_PUBLIC_API_URL` - Backend API URL (default: http://localhost:8000)

### Optional
- `DISCORD_WEBHOOK_URL` - Discord notifications
- `ANTHROPIC_API_KEY` - Claude API for co-pilot
- `KENPOM_API_KEY` - KenPom data
- `SCAN_ALL_SPORTS` - Set "1" to override season filter
- `ODDS_API_REGIONS` - Override regions (default: "us,us2,us_ex")
- `WHOP_API_KEY` / `WHOP_CLIENT_ID` / `WHOP_CLIENT_SECRET` - Whop auth
- `NEXT_PUBLIC_WHOP_APP_ID` - Whop app ID

---

## Common Bugs & Pitfalls

### PostgREST / Supabase Gotchas
1. **`on_conflict` comma encoding**: httpx URL-encodes commas in query params (`game_id%2Cmarket_type`). PostgREST can't parse this. Fix: append `on_conflict=col1,col2` directly to the URL string, not as httpx params.
2. **`Prefer: return=representation` timeout**: Large bulk updates with `return=representation` cause 500s. Use `return=minimal,count=exact` instead.
3. **`.isoformat()` produces `+00:00`**: The `+` URL-decodes as a space in PostgREST filters. Use `.strftime("%Y-%m-%dT%H:%M:%SZ")` instead.
4. **FK prevents DELETE**: `bet_results.ev_opportunity_id` references `ev_opportunities(id)`. Cannot DELETE ev_opportunities — must PATCH `status='expired'` or `status='graded'`.
5. **Column name mismatches**: The `games` table uses `start_time`, NOT `commence_time`. KenPom/Pinnacle tables use `commence_time`. Querying wrong column returns 400 from PostgREST, often silently swallowed by `except`.

### Profit/Loss Bugs
6. **100x inflation**: `signal_grader.py` previously used `bet_amount=100` as units parameter, making each loss = -100 instead of -1.0. Fixed: always pass `1.0` for flat signals. The `repair_signal_profit_loss()` function auto-detects and fixes this.
7. **ROI denominator**: ROI should be `total_units / decided_bets * 100`, NOT `total_units / all_bets * 100` (pushes don't count).

### Outcome Ordering
8. **Team name matching**: Outcomes must be matched by team NAME, not array position. API can return outcomes in any order. Always match "home_team" string to find home odds.
9. **Pinnacle never flips**: Pinnacle odds must always be stored as home_odds=home_team, away_odds=away_team regardless of API response ordering.

### Scanner Performance
10. **Batch operations**: Use `_post_many` / `_upsert_many` / `_patch_by_ids` for bulk DB operations. Never loop with individual queries (N+1).
11. **Chunk sizes**: `_post_many` default=100, `_upsert_many`=100, `_patch_by_ids`=500, `bulk_insert_line_movements`=2000.
12. **Cache before loops**: RTM signal engine pre-loads steam, movements, consensus, stale, reactions into caches before scoring loop.

### DB Client (db.py) Key Methods
```python
# Bulk insert
_post_many(table, rows, chunk_size=100)

# Bulk upsert (appends on_conflict to URL directly)
_upsert_many(table, rows, on_conflict, chunk_size=100)

# Query with filters
_get(table, select="*", filters={}, order=None, limit=None)

# Bulk update by filter
_patch(table, filters, data) -> int  # returns count

# Batch update by ID list (chunked)
_patch_by_ids(table, id_column, ids, data, chunk_size=500)
```

---

## Test Suite (7 files, ~236 tests)

| File | Tests | Focus |
|------|-------|-------|
| test_devig.py | ~50 | Devig methods, source hierarchy, edge cases |
| test_ev_audit.py | ~30 | EV formula, pipeline, suspicious edges |
| test_kelly.py | ~35 | Kelly sizing, no caps, custom fractions |
| test_kenpom_snapshots.py | ~50 | Edge calculation, grading, unit P/L |
| test_odds_mapping.py | ~40 | Outcome ordering, name matching, Pinnacle |
| test_pinnacle_history.py | ~15 | Opening/closing lines, movement |
| test_grading.py | ~18 | Win/loss/push, unit-based profit math |

Run: `cd /home/user/Alpha/backend && python -m pytest tests/ -v`

---

## Book Tiers (shared/books.py)

| Tier | Books | Role |
|------|-------|------|
| sharp | Pinnacle, Circa, Bookmaker | Set the market, devig source |
| exchange | Novig, Betfair, Smarkets | Near-zero vig |
| market_maker | DraftKings, FanDuel, BetMGM, Caesars | Large US books |
| soft | ESPN Bet, Hard Rock, BetRivers, etc. | Slow to adjust = +EV targets |

Blocked books: betopenly, betparx (filtered from all displays)
