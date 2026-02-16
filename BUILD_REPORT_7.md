# BUILD REPORT 7 — Intelligence Layers

**Date:** 2026-02-16
**Branch:** `claude/view-commit-history-JpSsv`

---

## What Was Built

Four intelligence layers that create Private EV — edge no public tool provides. These systems analyze *how* and *when* sportsbooks behave, not just what their odds are.

---

## 1. Book Profiling Engine

**File:** `backend/intelligence/book_profiler.py`

Tracks every sportsbook's behavior patterns relative to sharp books (Pinnacle, Circa, BetOnline).

### What It Does
- **Reaction Time Tracking:** When a sharp book moves a line, the profiler starts a timer and measures how long each soft book takes to match.
- **Exploitability Scoring:** Combines reaction time, stale line frequency, and average edge when stale into a composite exploit score (0-100).
- **Sport & Market Breakdown:** Knows which sport and which market type each book is weakest in (e.g., "FanDuel is slowest on NBA props").
- **Deep Dive Reports:** Full profile per book with reaction time charts by sport, market weakness breakdown, and recent stale line history.

### Key Methods
- `track_book_reaction_time()` — called each scan cycle when sharp books move
- `calculate_book_profiles()` — returns all books ranked by exploitability
- `get_weakest_books(sport, market)` — "for NBA props, target these books first"
- `get_book_report(book)` — full deep dive for one sportsbook

### How It Feeds Into Signals
If a +EV opportunity is on a book that's historically slow for that sport → +15 intelligence points.

---

## 2. Stale Line Detection Engine

**File:** `backend/intelligence/stale_detector.py`

A stale line is when one book hasn't moved but the sharp consensus has. This is structural edge — the most actionable type because the book is provably behind the market.

### What It Does
- **Real-Time Detection:** Every scan cycle, compares each soft book's odds against sharp book consensus.
- **Edge Calculation:** Uses implied probability comparison to calculate the exact EV% of the stale line.
- **Classification:** Labels each stale line as POST_STEAM, SLOW_MOVER, INJURY_LAG, or OPENING_LINE.
- **Lifecycle Management:** Stores new stale lines, resolves them when the book catches up.
- **Discord Alerts:** High-edge stale lines (5%+) trigger instant Discord notifications.

### Stale Line Criteria
1. At least 2 sharp books agree on a new consensus price
2. The soft book's odds are still at or near the old price
3. The difference creates at least 2% EV

### How It Feeds Into Signals
If the +EV opportunity is on a book with an active stale line → +30 intelligence points (the biggest bonus, because stale line edge is structural).

---

## 3. Market Timing Intelligence

**File:** `backend/intelligence/market_timing.py`

When you bet matters almost as much as what you bet.

### What It Does
- **Line Lifecycle Tracking:** Records first-seen time, first movement, biggest move, stabilization, and closing odds for every line.
- **Optimal Window Analysis:** Heat map of when edges are biggest by sport, market type, and hour of day.
- **Hours-Before-Game Analysis:** Shows that NBA props peak at different hours before tip-off than MLB game lines.
- **Edge Decay Estimation:** How fast does edge disappear after detection? (0-5m: 95% remaining, 5-15m: 78%, 15-30m: 55%, 30-60m: 35%, 1-2h: 20%).
- **Timing Context for Signals:** Each signal gets context like "Edge detected 4h before game. Historical avg: edges at this timing hold 73% of value to close."

### How It Feeds Into Signals
If the current time is in the optimal bet window for this sport/market → +10 intelligence points.
If the edge is at peak timing (2-8h before game) → +10 intelligence points.

---

## 4. Prop Correlation Engine

**File:** `backend/intelligence/correlation_engine.py`

Most bettors treat props as independent. They're not.

### What It Does
- **NBA Stat Correlations:** Pre-computed correlation coefficients between all major stat categories (points, rebounds, assists, threes, blocks, steals, PRA).
- **Related Props:** When viewing a player's prop, shows positively and negatively correlated props.
- **Parlay Edge Detection:** Finds prop combinations where positive correlation means the SGP is underpriced.
- **Anti-Correlation Warnings:** Flags when a bet slip has conflicting props (e.g., "LeBron Over Points AND Under PRA — these conflict").
- **Game-Level Correlations:** Links pace to scoring, blowout to bench minutes.

### Key Correlations Used
- Points ↔ Field Goals Made: r=0.85 (strong)
- Points ↔ Threes: r=0.55 (moderate)
- Points ↔ Assists: r=-0.15 (negative — high scoring = fewer assists)
- Rebounds ↔ Blocks: r=0.35 (moderate)
- Assists ↔ Turnovers: r=0.45 (moderate — more ball handling = more turnovers)

### How It Feeds Into Signals
If the prop has strong or moderate correlations confirming the direction → +15 intelligence points.

---

## How the Intelligence Score Works

The intelligence score (0-100) is a new component in the RTM Signal confluence model:

| Factor | Points | Condition |
|--------|--------|-----------|
| Stale Line | +30 | Book has active stale line for this game/market |
| Slow Book | +15 | Book's avg reaction time > 3 min for this sport |
| Optimal Window | +10 | Current time is near peak edge window |
| Correlation | +15 | Correlated props confirm this direction |
| Peak Timing | +10 | Edge detected 2-8h before game start |
| **Max** | **80** | (capped at 100) |

### Updated Signal Weights

**Non-NBA (no projections):**
```
signal_strength = (
    ev_score * 0.40 +
    steam_score * 0.20 +
    consensus_score * 0.20 +
    intelligence_score * 0.20
)
```

**NBA (has projections):**
```
signal_strength = (
    ev_score * 0.25 +
    steam_score * 0.15 +
    projection_score * 0.25 +
    consensus_score * 0.15 +
    intelligence_score * 0.20
)
```

---

## New API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/intelligence/book-profiles` | GET | All book profiles ranked by exploitability |
| `/api/intelligence/book-profiles/{book}` | GET | Single book deep dive |
| `/api/intelligence/weakest-books?sport=&market=` | GET | Best books to target |
| `/api/intelligence/stale-lines` | GET | All active stale lines |
| `/api/intelligence/stale-lines/history?days=` | GET | Resolved stale lines |
| `/api/intelligence/timing/optimal-windows?sport=` | GET | Best bet timing |
| `/api/intelligence/timing/edge-decay?sport=` | GET | Edge decay rates |
| `/api/intelligence/timing/lifecycle/{game_id}` | GET | Line lifecycle for a game |
| `/api/intelligence/correlations/{player}?prop_type=` | GET | Correlated props |
| `/api/intelligence/parlay-edges` | GET | +EV correlated parlays |
| `/api/intelligence/check-correlation` | POST | Check if two props correlate |

---

## New Frontend Pages

### Intelligence Center (`frontend/intelligence.html`)
Unified dashboard with 4 sections:
1. **Stale Lines (Real-Time)** — Active stale lines sorted by edge, auto-refresh every 30s
2. **Book Profiles** — Top 8 most exploitable books with quick stats
3. **Market Timing** — Current optimal windows, edge decay visualization
4. **Prop Correlations** — Today's best correlated parlay opportunities

### Book Intelligence (`frontend/book-profiles.html`)
Full book profiling page:
- Grid of book cards ranked by exploit score
- Each card: reaction time, stale frequency, best sport to target, avg edge
- Click for deep dive modal: sport breakdown, market weakness, recent stale lines

### Updated Pages
- **Signal page** — Now shows 5-component score grid (EV, Steam, Projection, Consensus, Intel) + intelligence badges (STALE LINE, OPTIMAL WINDOW, CORRELATED)
- **Props page** — "Correlations" button on player groups shows related props
- **All pages** — Nav updated with Intelligence + Book Intel links

---

## Database Tables Added

### `book_reaction_times`
Tracks how long each soft book takes to match sharp book movements.
- Indexed on: `soft_book`, `sport`, `game_id`

### `stale_line_alerts`
Active and resolved stale line detections.
- Indexed on: `status`, `detected_at`, `stale_book`

### `line_lifecycle`
Full lifecycle of every line from first posting to close.
- Indexed on: `sport`, `game_start_time`, `game_id`

### `rtm_signals` (updated)
- Added: `intelligence_score NUMERIC DEFAULT 0`
- Added: `intelligence_context JSONB`

---

## How to Test Each System

### Book Profiler
Run the scanner for several cycles. Check:
```
GET /api/intelligence/book-profiles
```
Should see books ranked by exploit score with reaction times.

### Stale Line Detection
During active game windows, check:
```
GET /api/intelligence/stale-lines
```
Should see stale lines when a book hasn't matched sharp consensus.

### Market Timing
After accumulating scan data across different hours:
```
GET /api/intelligence/timing/optimal-windows
```
Shows which hours have historically highest edge.

### Prop Correlations
Immediately testable (uses pre-computed correlations):
```
GET /api/intelligence/correlations/LeBron James?prop_type=points
GET /api/intelligence/parlay-edges
```

### Signal Integration
Run the signal engine — check signals for intelligence_score > 0:
```
GET /api/signals/active
```
Look for signals with intelligence badges in the frontend.

---

## What Data Needs to Accumulate

| System | Time to First Results | Time to Reliable Results |
|--------|----------------------|-------------------------|
| Book Profiler | 2-3 scan cycles | 24-48 hours |
| Stale Lines | 1 scan cycle | Immediate (real-time) |
| Market Timing | 24 hours | 1-2 weeks |
| Correlations | Immediate | Pre-computed |

---

## Known Limitations

1. **Book profiler** needs multiple scan cycles to build meaningful profiles. First few hours will have limited data.
2. **Stale line classification** (POST_STEAM vs INJURY_LAG) uses heuristics — no news feed integration yet.
3. **Market timing** edge decay uses industry-estimated defaults until enough lifecycle data accumulates.
4. **Prop correlations** are NBA-only with pre-computed coefficients. Real game-log based calculations would be more accurate.
5. **Cross-player correlations** (teammates) require team/opponent context not yet available.
6. **Line lifecycle tracking** creates many DB records — may need periodic cleanup for games older than 30 days.

---

## What to Build Next

1. **News Integration** — Wire in injury news to classify stale lines as INJURY_LAG and alert faster.
2. **Real Correlation Computation** — Use nba_api game logs to compute actual correlation coefficients per player pair.
3. **Book Grading Over Time** — Track how book exploitability changes week-over-week.
4. **Telegram Alerts** — Stale line alerts via Telegram for members who prefer it.
5. **Auto-Bet Recommendations** — "Bet this NOW at FanDuel before they catch up" with one-click deeplinks.
6. **Edge Decay Calibration** — Once lifecycle data accumulates, replace estimated decay with empirical data.
7. **Multi-Sport Correlations** — Extend correlation engine to NFL (rushing + receiving), MLB (pitcher + hitter matchups).

---

## File Inventory

### New Files
- `backend/intelligence/__init__.py`
- `backend/intelligence/book_profiler.py`
- `backend/intelligence/stale_detector.py`
- `backend/intelligence/market_timing.py`
- `backend/intelligence/correlation_engine.py`
- `backend/intelligence/cache/.gitkeep`
- `backend/api/routes/intelligence.py`
- `frontend/intelligence.html`
- `frontend/book-profiles.html`
- `scripts/006_intelligence_layers.sql`

### Modified Files
- `backend/rtm_signal_engine/rtm_signal.py` — intelligence score + weights
- `backend/api/main.py` — intelligence routes registered
- `backend/scrapers/odds_scraper.py` — intelligence layers in scan loop
- `backend/notifications/discord.py` — intelligence badges in alerts
- `shared/config.py` — intelligence scoring constants
- `frontend/signal.html` — intelligence badges + 5-component score grid
- `frontend/props.html` — correlation button + panel
- All 9 existing HTML pages — nav bar updated

---

*These intelligence layers are what make RTM impossible to copy. Anyone can build an EV scanner. Nobody else has book profiling + stale line detection + market timing + prop correlation all feeding into one signal.*
