# BUILD REPORT 5 — Overnight Build: Early Lines & Time-Aware Platform

**Date:** 2026-02-15
**Session:** Build Session 5 — "The Time Machine"

---

## Summary

The entire RTM Picks platform was upgraded from "point-in-time" to "time-aware." The core insight: **mainlines and props are two completely different strategies with different timing windows.** Mainlines (moneyline, spreads, totals) are posted 2-7 days in advance — early lines are where sportsbooks are softest. Props are same-day only, sometimes hours before game time — speed of detection matters most.

All 8 milestones completed.

---

## Milestones

### 1. Scanner: 48h Mainlines, Same-Day Props
- `odds_scraper.py` split into two API calls per sport:
  - Mainlines (h2h, spreads, totals) fetched for ALL upcoming games (48h+)
  - Props (13 market types) only fetched when games exist within 18h window
- API budget optimization: saves 13 credits per sport when no near-term games
- `merge_prop_data()` combines separate API responses into unified game objects
- `commence_time` and `hours_until_start` threaded through entire pipeline
- Console output groups opportunities by date (TODAY / TOMORROW / day name)

### 2. Dashboard Time Context & Early Line Badges
- "Starts" column (first column) with smart time badges:
  - LIVE (red pulse), minutes/hours, "Tomorrow 3:30 PM", "Mon 7:00 PM"
- EARLY LINE badge on opportunities 24+ hours from game time
- Time Window filter: All Upcoming, Today, Tomorrow, Starting Soon, Early Lines
- Sort By filter: Game Time (with date separators), EV%
- Stats row: game count, early line count

### 3. Signal Page: Early Signals & Top Signal Hero
- Time badges on every signal card (EARLY SIGNAL, URGENT with pulse, game time)
- TOP SIGNAL hero section — gradient gold border, rainbow stripe, strongest signal
- Sort options: By Strength (default), By Game Time, By EV%, By Time Posted
- Hero hidden on history/performance views

### 4. Props Page: New Line Detection
- API detects new lines by comparing current vs previous scan timestamps
- "NEW" badge (pulsing green) on freshly posted prop lines
- "X NEW LINES" stat chip
- Time Window filter: All Games, Starting Soon (<3h), Today, New Lines Only
- Starts column with time badges on every prop row
- Player group headers show game time and NEW indicator

### 5. Sharp Tracker: 48-Hour Window
- Default time window changed from 6h to 48h
- Time window selector: 6h, 12h, 24h, 48h
- EARLY STEAM badge on steam alerts for games 24+ hours out
- Game time context on all steam alert cards
- Early Steam count stat card
- Movers limit increased to 40

### 6. Odds Screen: Fix 401 & Sort by Game Time
- Removed `eu` from default API regions (caused 401 on standard plan)
- Games sorted by `commence_time` ascending
- Date separator headers (TODAY, TOMORROW, day name)
- Time badges: LIVE, minutes/hours, "Xh out" for early

### 7. Discord Alerts & Morning Briefing
- Signal alerts now include game time and EARLY/URGENT labels in title
- Game Time field added to Discord signal embeds
- New endpoint: `GET /api/recap/morning-briefing`
  - Today's game count and sports on slate
  - Active and early signal counts
  - Top signal highlight
  - Yesterday's record and units
  - `send_discord=true` to push to Discord channel
- `send_morning_briefing()` Discord function with formatted embed

### 8. Performance Fixes & Testing
- Fixed performance API: `summary` and `by-sport` endpoints now accept `sport`, `sportsbook`, and `range` filter params (were being ignored)
- Added `_range_to_dates()` helper for date range parsing
- Signal Lead Time metric: average hours between signal creation and game start
- `avg_lead_time_hours` added to signal performance API response
- Performance page: "Avg Signal Lead" stat card

---

## Key Technical Decisions

| Decision | Rationale |
|----------|-----------|
| Split mainline/prop API calls | Saves 13 API credits per sport when no near-term games exist |
| 18h prop window | Props rarely posted earlier; prevents wasted API calls |
| New line detection via scan comparison | No schema changes needed; compares side+market+line keys between scans |
| `eu` region removed | The Odds API standard plan returns 401 for EU region |
| `commence_time` threaded everywhere | Required for time-aware sorting, filtering, and display across all pages |
| Lead time metric | Proves value of early line scanning — higher lead time = earlier detection |

---

## Files Modified

### Backend
- `backend/scrapers/odds_scraper.py` — Major refactor for 48h scanning
- `backend/scrapers/odds/odds_api.py` — Fix regions default (us,us2 only)
- `backend/api/routes/props.py` — New line detection, commence_time
- `backend/api/routes/performance.py` — Filter params, range parsing
- `backend/api/routes/signal.py` — Signal lead time metric
- `backend/api/routes/recap.py` — Morning briefing endpoint
- `backend/notifications/discord.py` — Game time in signals, morning briefing
- `backend/rtm_signal_engine/rtm_signal.py` — Time fields in signals

### Frontend
- `frontend/dashboard.html` — Time context, early line badges, filters
- `frontend/signal.html` — Hero section, time badges, sort options
- `frontend/props.html` — New line detection, time badges, time filter
- `frontend/sharp-tracker.html` — 48h window, early steam badges
- `frontend/odds-screen.html` — 401 fix, sort by time, date separators
- `frontend/performance.html` — Signal lead time stat

---

## What This Enables

1. **Early line value capture** — Members see mainline opportunities 24-48h before game time when books are softest
2. **New line speed** — Props flagged as NEW the moment they appear, biggest edges on first scan
3. **Time-aware decision making** — Every page shows game time context so members know urgency
4. **Morning briefing** — Automated daily preview dropped to Discord at market open
5. **Performance validation** — Signal Lead Time metric proves the system finds value early
