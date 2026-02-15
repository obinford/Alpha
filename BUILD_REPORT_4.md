# BUILD REPORT 4 — The RTM Signal

## Summary

Built the RTM Signal — a proprietary confluence betting model that
combines four independent systems into a single scoring engine. This is
the flagship $200/month feature.

**8 milestones completed. All pushed.**

---

## What Was Built

### Milestone 1: Player Stats Data Pipeline
- `backend/projections/stats_fetcher.py` — NBA.com API via nba_api
- `backend/projections/stats_cache.py` — File-based JSON cache (6h/12h/24h TTL)
- `backend/projections/mock_data.py` — Realistic mock data for 15 NBA players
- **Blocker:** NBA.com blocked by proxy (403). Workaround: comprehensive mock data

### Milestone 2: Projection Engine
- `backend/projections/projection_engine.py` — Weighted projection model
- `backend/projections/league_averages.py` — Matchup baselines + home/away boosts
- Weights: 40% recent form, 30% season avg, 20% matchup, 10% home/away
- Matchup factor = opponent_stat / league_average, clamped [0.80, 1.25]
- Projects 7 stats: points, rebounds, assists, threes, steals, blocks, PRA

### Milestone 3: Monte Carlo Prop Simulator
- `backend/projections/simulator.py` — 10,000 simulation engine
- `backend/projections/math_utils.py` — Odds conversion utilities
- Distribution selection by prop type:
  - Points/PRA: Shifted gamma (right-skewed, continuous)
  - Rebounds/Assists: Negative binomial (count-based, overdispersed)
  - Threes/Steals/Blocks: Poisson (discrete rare events)
- **Key insight verified:** Mean > Median (skewness = 0.617). Sportsbooks
  set lines at the median. Mean-based projections can exploit this.

### Milestone 4: RTM Signal Confluence Model
- `backend/rtm_signal_engine/rtm_signal.py` — The scoring engine
- `scripts/005_rtm_signal.sql` — Supabase migration for rtm_signals table
- Four component scores (0-100 each):
  - **EV Score:** Edge from devigged sharp books (0-12%+ → 0-100)
  - **Steam Score:** Sharp money confirmation (3-5+ books moving)
  - **Projection Score:** Our Monte Carlo prob vs sportsbook line
  - **Consensus Score:** Market-wide line movement agreement
- Weights:
  - Game lines: EV 40%, Steam 30%, Proj 0%, Consensus 30%
  - Props: EV 25%, Steam 20%, Proj 35%, Consensus 20%
- Signal tiers: 75+ = 5-star STRONG, 60+ = 4-star SIGNAL, 45+ = 3-star LEAN

### Milestone 5: RTM Signal Dashboard
- `frontend/signal.html` — Flagship page with:
  - Signal cards with star ratings (5-star gold glow, 4-star green, 3-star blue)
  - Component score bars (EV, Steam, Projection, Consensus)
  - Kelly sizing badges
  - Three views: Active Signals, Signal History, Performance
  - Auto-refresh every 60 seconds
- `backend/api/routes/signal.py` — API endpoints:
  - GET /api/signals/active — Current active signals
  - GET /api/signals/history — Graded signal history with filters
  - GET /api/signals/performance — Stats, tier breakdown, sport breakdown
  - GET /api/signals/projection/{player_id} — Player projection with simulation
- Signal link added as second nav item across all 9 frontend pages

### Milestone 6: Signal Grading & Analytics
- `backend/rtm_signal_engine/signal_grader.py` — Auto-grades signals
  when games finalize (WIN/LOSS/PUSH with profit/loss calculation)
- Performance analytics with streak tracking, component score analysis
  for winners vs losers, tier and sport breakdowns
- Daily recap updated to include signal stats (fired, graded, record, units)

### Milestone 7: Full Pipeline Integration
- Signal generation wired into `odds_scraper.py` scan cycle
- Signal grading runs automatically after EV grading
- Handles non-NBA sports (projection_score = 0, uses game line weights)
- NBA props use live projections from the engine
- Discord alerts fire for 4+ star signals
- Renamed `signal/` → `rtm_signal_engine/` (stdlib conflict fix)

### Milestone 8: Documentation & Polish
- This build report
- BLOCKERS.md updated
- .env.example updated (Discord webhook, fixed service key name)
- .gitignore updated (projection cache)

---

## New Files Created (18)

```
backend/projections/__init__.py
backend/projections/stats_cache.py
backend/projections/stats_fetcher.py
backend/projections/mock_data.py
backend/projections/league_averages.py
backend/projections/projection_engine.py
backend/projections/math_utils.py
backend/projections/simulator.py
backend/rtm_signal_engine/__init__.py
backend/rtm_signal_engine/rtm_signal.py
backend/rtm_signal_engine/signal_grader.py
backend/api/routes/signal.py
frontend/signal.html
scripts/005_rtm_signal.sql
BLOCKERS.md
BUILD_REPORT_4.md
```

## Files Modified (12)

```
backend/api/main.py              — Added signal router
backend/scrapers/odds_scraper.py — Wired signal generation + grading
backend/notifications/discord.py — Added send_signal_alert()
backend/notifications/daily_recap.py — Added signal stats
backend/.env.example             — Added Discord webhook
.gitignore                       — Added projections/cache/
frontend/dashboard.html          — Added Signal nav link
frontend/sharp-tracker.html      — Added Signal nav link
frontend/props.html              — Added Signal nav link
frontend/odds-screen.html        — Added Signal nav link
frontend/performance.html        — Added Signal nav link
frontend/clv-report.html         — Added Signal nav link
frontend/daily-recap.html        — Added Signal nav link + signal stats
frontend/bankroll.html           — Added Signal nav link
```

## SQL Migrations

- `scripts/005_rtm_signal.sql` — Creates `rtm_signals` table with indexes on
  game_id, created_at, signal_strength, star_rating, status

## Integration Test Results

```
1. Projection Engine:
   LeBron James: 21.5 pts (std: 6.1)
   Nikola Jokic: 25.7 pts (std: 8.1)
   Kevin Durant: 26.1 pts (std: 6.7)

2. Simulator:
   Over 22.5 prob=0.423, Under=0.577
   Fair Over odds: +136, Fair Under: -136

3. Signal Generation:
   1 signal from 3 opportunities
   RTM LEAN ⭐⭐⭐ | LeBron James Over 7.5 AST at fanduel -105 | Str: 52

4. All imports OK, FastAPI loads with 40 routes
```

## Blockers

- **NBA.com API blocked by proxy (403)** — Worked around with mock data
  for 15 players. Production will use live data.

## What's Next

1. Deploy to Railway (backend) and verify Supabase connection
2. Run `scripts/005_rtm_signal.sql` migration in Supabase
3. Set `use_mock=False` in production for live NBA.com data
4. Add MLB player projection data (pybaseball)
5. Tune signal weights based on real grading data
6. Add player prop grading (requires game stat ingestion)
7. Consider adding NFL/NHL projection models
