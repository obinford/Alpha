#!/usr/bin/env python3
"""Smart API scheduler for the RTM Picks Platform.

Determines which sports to scan and how often, based on:
- Whether a sport has games today
- How close games are to starting (ramp up frequency near tip-off)
- API usage budget tracking

Usage:
    python backend/scrapers/scheduler.py              # run smart scheduler
    python backend/scrapers/scheduler.py --dry-run    # show plan without scanning
    python backend/scrapers/scheduler.py --once       # single smart scan then exit
"""

import json
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

# Allow running as a standalone script from the repo root.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "shared"))

from dotenv import load_dotenv

from config import (
    ODDS_API_SPORT_KEYS, SPORT_DISPLAY_NAMES,
    MONTHLY_API_CREDITS, DAILY_CREDIT_BUDGET, CREDIT_WARNING_THRESHOLD,
)

# ---------------------------------------------------------------------------
# Scheduling tiers — scan interval depends on proximity to game start
# ---------------------------------------------------------------------------

# (hours_until_start_lte, interval_minutes)
# Checked top-to-bottom; first match wins.
PROXIMITY_TIERS: list[tuple[float, int]] = [
    (0.5, 2),     # 0–30 min before start: every 2 minutes
    (1.0, 5),     # 30–60 min: every 5 minutes
    (3.0, 10),    # 1–3 hours: every 10 minutes
    (6.0, 20),    # 3–6 hours: every 20 minutes
    (12.0, 30),   # 6–12 hours: every 30 minutes
    (24.0, 60),   # 12–24 hours: every 60 minutes
]

# If no game is within 24h, skip scanning entirely.
DEFAULT_INTERVAL_MINUTES = 60

# Base API cost per sport per scan (1 request for odds).
# Props add 1 more request per sport, so effective cost = 2.
API_COST_PER_SPORT = 2

# Budget from config ($59 plan = 100,000 credits/month).
MONTHLY_API_BUDGET = MONTHLY_API_CREDITS

# Usage tracking file.
USAGE_FILE = os.path.join(os.path.dirname(__file__), "..", "..", ".api_usage.json")


@dataclass
class SportSchedule:
    """Scheduling info for a single sport."""
    sport_alias: str       # e.g. "NBA"
    sport_key: str         # e.g. "basketball_nba"
    display_name: str      # e.g. "NBA"
    has_games_today: bool = False
    next_game_hours: float | None = None  # hours until next game (None = unknown)
    interval_minutes: int = DEFAULT_INTERVAL_MINUTES
    last_scan_utc: datetime | None = None
    should_scan_now: bool = False
    skip_reason: str = ""


@dataclass
class UsageTracker:
    """Tracks API usage for budget management (monthly + daily)."""
    month: str = ""                    # e.g. "2026-02"
    day: str = ""                      # e.g. "2026-02-16"
    requests_used: int = 0             # monthly total
    daily_requests: int = 0            # today's total
    requests_by_sport: dict[str, int] = field(default_factory=dict)
    last_updated: str = ""

    def to_dict(self) -> dict:
        return {
            "month": self.month,
            "day": self.day,
            "requests_used": self.requests_used,
            "daily_requests": self.daily_requests,
            "requests_by_sport": self.requests_by_sport,
            "last_updated": self.last_updated,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "UsageTracker":
        return cls(
            month=d.get("month", ""),
            day=d.get("day", ""),
            requests_used=d.get("requests_used", 0),
            daily_requests=d.get("daily_requests", 0),
            requests_by_sport=d.get("requests_by_sport", {}),
            last_updated=d.get("last_updated", ""),
        )


def load_usage() -> UsageTracker:
    """Load API usage from disk."""
    now = datetime.now(timezone.utc)
    current_month = now.strftime("%Y-%m")
    current_day = now.strftime("%Y-%m-%d")
    try:
        with open(USAGE_FILE) as f:
            data = json.load(f)
        tracker = UsageTracker.from_dict(data)
        # Reset if new month.
        if tracker.month != current_month:
            tracker = UsageTracker(month=current_month, day=current_day)
        # Reset daily counter if new day.
        elif tracker.day != current_day:
            tracker.day = current_day
            tracker.daily_requests = 0
        return tracker
    except (FileNotFoundError, json.JSONDecodeError):
        return UsageTracker(month=current_month, day=current_day)


def save_usage(tracker: UsageTracker) -> None:
    """Persist API usage to disk."""
    tracker.last_updated = datetime.now(timezone.utc).isoformat()
    with open(USAGE_FILE, "w") as f:
        json.dump(tracker.to_dict(), f, indent=2)


def record_usage(tracker: UsageTracker, sport_key: str, cost: int = API_COST_PER_SPORT) -> None:
    """Record API request usage."""
    tracker.requests_used += cost
    tracker.daily_requests += cost
    tracker.requests_by_sport[sport_key] = (
        tracker.requests_by_sport.get(sport_key, 0) + cost
    )
    save_usage(tracker)


def budget_remaining(tracker: UsageTracker) -> int:
    """Return remaining API requests for the month."""
    return max(0, MONTHLY_API_BUDGET - tracker.requests_used)


def daily_budget_remaining(tracker: UsageTracker) -> int:
    """Return remaining daily API requests."""
    return max(0, DAILY_CREDIT_BUDGET - tracker.daily_requests)


def is_daily_warning(tracker: UsageTracker) -> bool:
    """Return True if daily usage exceeds warning threshold."""
    return tracker.daily_requests >= int(DAILY_CREDIT_BUDGET * CREDIT_WARNING_THRESHOLD)


# ---------------------------------------------------------------------------
# Game schedule checking
# ---------------------------------------------------------------------------

def check_sport_schedule(sport_key: str) -> tuple[bool, float | None]:
    """Check if a sport has upcoming games today by querying Supabase.

    Returns (has_games_today, hours_until_next_game).
    """
    try:
        from db import get_supabase

        db = get_supabase()
        now = datetime.now(timezone.utc)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1)

        games = db._get(
            "games",
            select="start_time",
            filters={
                "sport": f"eq.{sport_key}",
                "start_time": f"gte.{today_start.isoformat()}",
                "status": "eq.upcoming",
            },
            order="start_time.asc",
            limit=5,
        )

        if not games:
            return False, None

        # Parse closest game time.
        closest_start_str = games[0]["start_time"]
        # Handle both ISO format variations.
        closest_start = datetime.fromisoformat(
            closest_start_str.replace("Z", "+00:00")
        )
        hours_until = max(0, (closest_start - now).total_seconds() / 3600)

        return True, round(hours_until, 2)
    except Exception:
        # If we can't check schedule, assume games exist (safer to scan).
        return True, None


def determine_interval(hours_until_game: float | None) -> int:
    """Return scan interval in minutes based on proximity to game time."""
    if hours_until_game is None:
        return DEFAULT_INTERVAL_MINUTES

    for max_hours, interval in PROXIMITY_TIERS:
        if hours_until_game <= max_hours:
            return interval

    return DEFAULT_INTERVAL_MINUTES


# ---------------------------------------------------------------------------
# Scheduling plan
# ---------------------------------------------------------------------------

def build_schedule(
    sport_aliases: list[str] | None = None,
) -> list[SportSchedule]:
    """Build a schedule determining which sports to scan and when.

    Args:
        sport_aliases: Optional list of sport aliases to include (e.g. ["NBA", "NFL"]).
                       If None, checks all configured sports.
    """
    if sport_aliases:
        sport_map = {
            alias: ODDS_API_SPORT_KEYS[alias]
            for alias in sport_aliases
            if alias in ODDS_API_SPORT_KEYS
        }
    else:
        sport_map = dict(ODDS_API_SPORT_KEYS)

    schedules: list[SportSchedule] = []
    now = datetime.now(timezone.utc)

    for alias, sport_key in sport_map.items():
        display = SPORT_DISPLAY_NAMES.get(sport_key, alias)
        has_games, hours = check_sport_schedule(sport_key)

        interval = determine_interval(hours)
        sched = SportSchedule(
            sport_alias=alias,
            sport_key=sport_key,
            display_name=display,
            has_games_today=has_games,
            next_game_hours=hours,
            interval_minutes=interval,
        )

        if not has_games:
            sched.should_scan_now = False
            sched.skip_reason = "no games today"
        else:
            sched.should_scan_now = True

        schedules.append(sched)

    return schedules


def print_schedule(schedules: list[SportSchedule], usage: UsageTracker) -> None:
    """Print the current schedule plan to console."""
    print(f"\n{'=' * 80}")
    print(f"  RTM Smart Scheduler  |  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"{'=' * 80}")

    # Usage stats.
    remaining = budget_remaining(usage)
    daily_remaining = daily_budget_remaining(usage)
    pct_used = (usage.requests_used / MONTHLY_API_BUDGET * 100) if MONTHLY_API_BUDGET > 0 else 0
    daily_pct = (usage.daily_requests / DAILY_CREDIT_BUDGET * 100) if DAILY_CREDIT_BUDGET > 0 else 0
    print(f"\n  Monthly: {usage.requests_used:,}/{MONTHLY_API_BUDGET:,} ({pct_used:.1f}%) | {remaining:,} remaining")
    print(f"  Daily:   {usage.daily_requests:,}/{DAILY_CREDIT_BUDGET:,} ({daily_pct:.1f}%) | {daily_remaining:,} remaining")
    if is_daily_warning(usage):
        print(f"  ⚠  DAILY BUDGET WARNING: {daily_pct:.0f}% used (threshold: {CREDIT_WARNING_THRESHOLD*100:.0f}%)")

    # Schedule table.
    header = f"  {'Sport':<25} {'Games?':<8} {'Next Game':>12} {'Interval':>12} {'Action':<20}"
    print(f"\n{header}")
    print(f"  {'-' * 75}")

    scan_count = 0
    for s in schedules:
        games_str = "Yes" if s.has_games_today else "No"
        hours_str = f"{s.next_game_hours:.1f}h" if s.next_game_hours is not None else "—"
        interval_str = f"{s.interval_minutes}m"
        if s.should_scan_now:
            action = "SCAN"
            scan_count += 1
        else:
            action = f"skip ({s.skip_reason})"
        print(f"  {s.display_name:<25} {games_str:<8} {hours_str:>12} {interval_str:>12} {action:<20}")

    print(f"\n  Sports to scan: {scan_count}/{len(schedules)}")
    estimated_cost = scan_count * API_COST_PER_SPORT
    print(f"  Estimated API cost this cycle: {estimated_cost} request(s)")
    print()


# ---------------------------------------------------------------------------
# Smart scan execution
# ---------------------------------------------------------------------------

def run_smart_scan(
    sport_aliases: list[str] | None = None,
    dry_run: bool = False,
) -> int:
    """Execute a smart scan cycle.

    Returns the number of EV opportunities found.
    """
    usage = load_usage()
    schedules = build_schedule(sport_aliases)
    print_schedule(schedules, usage)

    if dry_run:
        print("  --dry-run: No scans executed.\n")
        return 0

    # Check both monthly and daily budgets.
    sports_to_scan = [s for s in schedules if s.should_scan_now]
    cost = len(sports_to_scan) * API_COST_PER_SPORT
    monthly_remaining = budget_remaining(usage)
    daily_remaining_credits = daily_budget_remaining(usage)
    effective_remaining = min(monthly_remaining, daily_remaining_credits)

    if cost > effective_remaining:
        limit = effective_remaining // API_COST_PER_SPORT
        if effective_remaining == daily_remaining_credits:
            print(f"  DAILY BUDGET: {cost} credits needed but only {daily_remaining_credits} remain today.")
        else:
            print(f"  MONTHLY BUDGET: {cost} credits needed but only {monthly_remaining} remain.")
        print(f"  Reducing to top {limit} sports by proximity.\n")
        sports_to_scan.sort(
            key=lambda s: s.next_game_hours if s.next_game_hours is not None else 999
        )
        sports_to_scan = sports_to_scan[:limit]

    if not sports_to_scan:
        print("  No sports to scan this cycle.\n")
        return 0

    # Run the actual scan.
    from scrapers.odds_scraper import run_scan

    sport_keys = [s.sport_key for s in sports_to_scan]

    # Record usage before scan (in case of crash, we still tracked it).
    for s in sports_to_scan:
        record_usage(usage, s.sport_key)

    count = run_scan(sport_keys)
    return count


# ---------------------------------------------------------------------------
# Scheduler loop
# ---------------------------------------------------------------------------

def main() -> None:
    """Main entry point for the smart scheduler."""
    dotenv_path = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
    load_dotenv(dotenv_path)

    args = sys.argv[1:]
    dry_run = "--dry-run" in args
    once = "--once" in args
    args = [a for a in args if not a.startswith("--")]

    # Sport aliases from CLI.
    sport_aliases = [a.upper() for a in args] if args else None

    if dry_run or once:
        run_smart_scan(sport_aliases, dry_run=dry_run)
        return

    # Continuous loop with smart intervals.
    print("RTM Smart Scheduler started. Press Ctrl+C to stop.\n")

    try:
        while True:
            print(f"\n{'#' * 80}")
            print(f"# Smart scan at {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
            print(f"{'#' * 80}\n")

            # Build schedule to determine the minimum interval.
            schedules = build_schedule(sport_aliases)
            active = [s for s in schedules if s.should_scan_now]

            if active:
                count = run_smart_scan(sport_aliases)
                min_interval = min(s.interval_minutes for s in active)
            else:
                print("  No active sports. Sleeping for 30 minutes.\n")
                min_interval = 30

            print(f"Next scan in {min_interval} minutes...")
            time.sleep(min_interval * 60)

    except KeyboardInterrupt:
        print("\nShutting down smart scheduler...")


if __name__ == "__main__":
    main()
