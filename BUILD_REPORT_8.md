# BUILD REPORT 8 — Engine Overhaul

**Date:** 2026-02-16
**Branch:** `claude/view-commit-history-JpSsv`
**Session:** Engine rebuild — 7 milestones, 132 tests, 6 commits

---

## Overview

Complete rebuild of the three most critical systems in the platform:
1. **Devig Engine** — how we find true probabilities
2. **Kelly Criterion** — how we size bets
3. **CLV Pipeline** — how we prove edge

Plus: expanded data sources, smarter scheduling, and full EV audit.

---

## Milestone 1: Enable Every Available Book

**Files:** `shared/books.py` (NEW), `shared/config.py`, `backend/scrapers/odds/odds_api.py`, `backend/scrapers/odds_scraper.py`

- Created comprehensive book registry: **40 sportsbooks** classified into 4 tiers:
  - **Sharp** (5): Pinnacle (1.0), BetOnline (0.8), Circa (0.75), Bovada (0.7), LowVig (0.7)
  - **Exchange** (9): Novig (0.9), Betfair Exchange (0.9), Smarkets (0.85), Matchbook (0.85), etc.
  - **Market Maker** (5): DraftKings (0.5), FanDuel (0.5), BetMGM (0.5), Caesars (0.5), Fanatics (0.4)
  - **Soft** (21): ESPN Bet, Hard Rock, BetRivers, etc.
- Expanded API regions from `us,us2` → `us,us2,eu,us_ex` (configurable via env var)
- This unlocks **Pinnacle** (EU region) as a devig source — the gold standard
- Added book discovery logging per scan

---

## Milestone 2: Rebuild the Devig Engine

**Files:** `backend/models/devig.py` (NEW), `backend/scrapers/odds_scraper.py`, `backend/tests/test_devig.py` (NEW)

**The most important code in the platform.** Accurate devigging = accurate true probabilities = accurate EV.

### Source Hierarchy
| Priority | Source | Confidence | When Used |
|----------|--------|-----------|-----------|
| 1 | Pinnacle | HIGH | Pinnacle available in EU region |
| 2 | Exchange consensus | MEDIUM | Novig, Betfair, Matchbook available |
| 3 | Sharp book weighted avg | LOW | Circa, BetOnline, Bovada available |
| 4 | Market average | CAUTION | Only soft books available (last resort) |

### Four Devig Methods
1. **Multiplicative** — divide each implied prob by overround (best for balanced markets)
2. **Additive** — subtract equal share of overround (better for heavy favorites)
3. **Power** — find exponent k where imp_a^k + imp_b^k = 1 (more theoretically sound)
4. **Shin** — models overround as insider trading (handles informed trading)

### Scanner Integration
- `scan_game()` replaced: now uses `build_devig_line_map()` with full hierarchy
- Source books excluded from soft-book comparison (don't bet the book you devigged from)
- Props scanner rebuilt with `_build_prop_devig_map()` for per-player hierarchical devigging
- `store_true_lines()` and `store_ev_opportunities()` include devig metadata
- `EVOpportunity` dataclass extended with `devig_source`, `devig_confidence`, `devig_method`

**Test coverage:** 61 tests across all methods, source hierarchy, edge cases

---

## Milestone 3: Fix Kelly Criterion Permanently

**Files:** `backend/models/kelly.py`, `backend/tests/test_kelly.py` (NEW), `backend/rtm_signal_engine/rtm_signal.py`, `backend/api/routes/signal.py`, `backend/analytics/bankroll.py`, `frontend/signal.html`

### The Formula (immutable)
```
full_kelly = (b * p - q) / b
where b = decimal_odds - 1, p = true probability, q = 1 - p

quarter_kelly = full_kelly * 0.25
units = quarter_kelly * 100   (1 unit = 1% of bankroll)
```

### What Changed
- Enhanced `kelly.py` with four canonical functions: `kelly_full()`, `kelly_fraction()`, `kelly_units()`, `kelly_from_ev()`
- **No caps. No minimums.** If Kelly is negative (no edge), return 0. Let the math speak.
- Replaced inline Kelly in `rtm_signal.py` with `kelly_units()` call
- Replaced inline Kelly in `signal.py` API route with `kelly_units()` call
- Removed `Math.min(kelly, 3.0)` cap from frontend hero card
- `bankroll.py` now imports from canonical module

### Previous Bugs Fixed
1. **Session 6:** All signals showing 3.00u (MAX_UNIT_SIZE cap) → removed cap
2. **Session 6:** Values 4x too high (0.25 not applied) → added API-level recalculation
3. **Session 8:** Frontend hero card still had `Math.min(kelly, 3.0)` → removed

**Test coverage:** 40 tests including hand-calculated verification, formula relationships, no-cap verification, edge cases, kelly_from_ev roundtrip, parametric monotonicity

---

## Milestone 4: CLV as Primary Metric

**Files:** `backend/scrapers/clv_tracker.py`, `backend/api/routes/signal.py`

CLV (Closing Line Value) is the gold standard for proving edge.

### What Changed
- Fixed `get_closing_sharp_line()` — was returning `None` (broken since creation). Now properly maps side strings to home/away team by looking up game info.
- Added **devigged CLV**: compares bet implied probability against closing sharp true probability (not just closing book odds)
- Enhanced summary stats with `avg_devigged_clv` per-sport
- Signal performance endpoint (`/signals/performance`) now includes CLV summary inline

### CLV Flow
1. EV opportunity found → CLV record created (status: open)
2. Game starts → closing odds captured from `line_movements` table
3. Raw CLV computed: bet odds vs closing odds at same book
4. Devigged CLV computed: bet odds vs closing sharp true probability
5. Surfaced via `/api/clv/summary` and `/api/signals/performance`

---

## Milestone 5: Tiered Scan Frequency

**Files:** `backend/scrapers/scheduler.py`

### Budget Upgrade
- From free tier (500/month) → **$59 plan (100,000/month)**
- Added daily budget tracking: **3,333 credits/day**
- Warning at 80% daily usage
- Budget enforcement uses `min(monthly, daily)` remaining

### Scan Intervals (unchanged — already correct)
| Time to Game | Interval |
|-------------|----------|
| 0–30 min | 2 min |
| 30–60 min | 5 min |
| 1–3 hours | 10 min |
| 3–6 hours | 20 min |
| 6–12 hours | 30 min |
| 12–24 hours | 60 min |
| No games within 24h | Skip |

---

## Milestone 6: EV Calculation Audit

**Files:** `backend/models/ev_calculator.py`, `backend/tests/test_ev_audit.py` (NEW)

### Edge Validation
Added `validate_edge()` to `ev_calculator.py`:
- Classifies edge confidence: HIGH / MEDIUM / LOW / CAUTION
- Flags: `EXTREME_EV` (>20%), `INVALID_PROB`, `LARGE_FAV_EDGE` (>15% on favorite)
- Integrates with devig confidence from Milestone 2

### Audit Results
All formulas verified with hand-calculated examples:
- `EV% = (true_prob × decimal_odds - 1) × 100` ✓
- `Kelly units = full_kelly × 0.25 × 100` ✓
- `CLV = (closing_implied - bet_implied) / bet_implied × 100` ✓
- Devig preserves ordering (favorite stays favorite) ✓
- EV at sharp's own price ≈ -vig% (correct) ✓

**Test coverage:** 31 tests covering formula verification, full pipeline, confidence scoring, suspicious edge detection, odds conversion, devig information preservation

---

## Test Suite Summary

| Module | Tests | Status |
|--------|-------|--------|
| Devig Engine | 61 | ✅ All passing |
| Kelly Criterion | 40 | ✅ All passing |
| EV Audit | 31 | ✅ All passing |
| **Total** | **132** | **✅ All passing** |

---

## Files Changed (This Session)

### New Files
- `shared/books.py` — 40-book registry with tiers and weights
- `backend/models/devig.py` — hierarchical devig engine
- `backend/tests/test_devig.py` — 61 devig tests
- `backend/tests/test_kelly.py` — 40 Kelly tests
- `backend/tests/test_ev_audit.py` — 31 EV audit tests

### Modified Files
- `shared/config.py` — regions, credit budgeting
- `backend/scrapers/odds/odds_api.py` — configurable regions
- `backend/scrapers/odds_scraper.py` — hierarchical devig integration
- `backend/scrapers/scheduler.py` — daily credit budgeting
- `backend/scrapers/clv_tracker.py` — devigged CLV
- `backend/models/kelly.py` — definitive module
- `backend/models/ev_calculator.py` — edge validation
- `backend/rtm_signal_engine/rtm_signal.py` — canonical Kelly, devig metadata
- `backend/api/routes/signal.py` — canonical Kelly, CLV in performance
- `backend/analytics/bankroll.py` — imports from canonical Kelly
- `frontend/signal.html` — removed 3.0u cap

---

## Known Blockers

1. **Live API testing**: Cannot verify EU/US_EX regions without API key in environment
2. **Supabase schema**: New columns (`devig_source`, `devig_confidence`, `devig_method`, `devigged_clv`) need to be added to tables before deploy
3. **Props devig**: Per-player hierarchical devigging works in code but needs live data to verify pairing logic
