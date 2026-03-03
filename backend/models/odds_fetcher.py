"""
RTM Props Model — Historical Odds Fetcher (Phase 3)
Pulls historical pitcher strikeout props from The Odds API.
Caches each day's results for resume capability.
"""

import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ODDS_DIR = PROJECT_ROOT / "data" / "raw" / "historical_odds"
ODDS_DIR.mkdir(parents=True, exist_ok=True)

load_dotenv(PROJECT_ROOT / ".env")

BASE_URL = "https://api.the-odds-api.com/v4"
SPORT = "baseball_mlb"


def get_api_key() -> str:
    """Load API key from environment."""
    key = os.getenv("THE_ODDS_API_KEY", "")
    if not key or key == "your_key_here":
        return ""
    return key


def estimate_credits(seasons: list[int], start_month: int = 4, end_month: int = 10) -> dict:
    """Estimate total API credits needed before making any calls.

    Returns dict with credit breakdown and recommendation.
    """
    total_game_days = 0
    total_events_est = 0

    for year in seasons:
        s_month = max(start_month, 5) if year == 2023 else start_month
        e_month = min(end_month, 9) if year == 2025 else end_month

        days_in_range = 0
        for month in range(s_month, e_month + 1):
            if month in (4, 6, 9):
                days_in_range += 30
            elif month in (5, 7, 8, 10):
                days_in_range += 31
        total_game_days += days_in_range
        # ~15 games per day average during season
        total_events_est += days_in_range * 15

    event_list_credits = total_game_days * 1  # 1 credit per events call
    event_odds_credits = total_events_est * 10  # 10 credits per event odds
    total_credits = event_list_credits + event_odds_credits

    return {
        "seasons": seasons,
        "total_game_days": total_game_days,
        "total_events_est": total_events_est,
        "event_list_credits": event_list_credits,
        "event_odds_credits": event_odds_credits,
        "total_credits": total_credits,
        "fits_monthly_budget": total_credits <= 80000,
    }


def fetch_historical_events(date_str: str, api_key: str) -> list:
    """Get all MLB events for a specific date.

    Args:
        date_str: ISO format date string (e.g. '2024-06-15T18:00:00Z')
        api_key: The Odds API key

    Returns:
        List of event dicts with id, home_team, away_team, commence_time.
    """
    url = f"{BASE_URL}/historical/sports/{SPORT}/events"
    params = {
        "apiKey": api_key,
        "date": date_str,
    }

    resp = _request_with_retry(url, params)
    if resp is None:
        return []

    data = resp.json()
    # The response has {"data": [...events...], "previous_timestamp": ..., "next_timestamp": ...}
    events = data.get("data", data) if isinstance(data, dict) else data
    if isinstance(events, list):
        return events
    return events if isinstance(events, list) else []


def fetch_event_strikeout_odds(event_id: str, date_str: str, api_key: str) -> dict:
    """Get pitcher strikeout odds for a specific event.

    Returns dict with event_id, bookmakers data for pitcher_strikeouts market.
    """
    url = f"{BASE_URL}/historical/sports/{SPORT}/events/{event_id}/odds"
    params = {
        "apiKey": api_key,
        "date": date_str,
        "regions": "us",
        "markets": "pitcher_strikeouts",
        "oddsFormat": "american",
    }

    resp = _request_with_retry(url, params)
    if resp is None:
        return {"event_id": event_id, "bookmakers": [], "error": "request_failed"}

    data = resp.json()
    return {
        "event_id": event_id,
        "data": data.get("data", data) if isinstance(data, dict) else data,
    }


def _request_with_retry(url: str, params: dict, max_retries: int = 3) -> requests.Response | None:
    """Make an API request with exponential backoff retry."""
    for attempt in range(max_retries):
        try:
            resp = requests.get(url, params=params, timeout=30)
            if resp.status_code == 200:
                return resp
            elif resp.status_code == 429:
                wait = 2 ** (attempt + 2)
                print(f"    Rate limited. Waiting {wait}s...")
                time.sleep(wait)
            elif resp.status_code == 401:
                print(f"    ERROR: Invalid API key (401)")
                return None
            elif resp.status_code == 422:
                # Unprocessable — often means no data for this date/event
                return None
            else:
                wait = 2 ** (attempt + 1)
                print(f"    HTTP {resp.status_code}. Retrying in {wait}s...")
                time.sleep(wait)
        except requests.exceptions.RequestException as e:
            wait = 2 ** (attempt + 1)
            if attempt < max_retries - 1:
                print(f"    Request error: {e}. Retrying in {wait}s...")
                time.sleep(wait)
            else:
                print(f"    Request failed after {max_retries} attempts: {e}")
                return None
    return None


def get_season_dates(year: int, start_month: int = 4, end_month: int = 10) -> list[str]:
    """Generate all dates in an MLB season.

    Args:
        year: Season year
        start_month: First month (4=April for full season, 5=May for 2023)
        end_month: Last month (10=October)

    Returns:
        List of date strings in YYYY-MM-DD format.
    """
    start = datetime(year, start_month, 1)
    # End of the last month
    if end_month == 12:
        end = datetime(year + 1, 1, 1) - timedelta(days=1)
    else:
        end = datetime(year, end_month + 1, 1) - timedelta(days=1)

    dates = []
    current = start
    while current <= end:
        dates.append(current.strftime("%Y-%m-%d"))
        current += timedelta(days=1)
    return dates


def fetch_season_odds(year: int, api_key: str, start_month: int = 4, end_month: int = 10) -> list[dict]:
    """Fetch all pitcher strikeout odds for an MLB season.

    Caches each day's results to data/raw/historical_odds/{year}/{date}.json.
    Resumes from cache if partially completed.

    Returns:
        List of all event odds dicts for the season.
    """
    year_dir = ODDS_DIR / str(year)
    year_dir.mkdir(parents=True, exist_ok=True)

    dates = get_season_dates(year, start_month, end_month)
    all_results = []
    total_api_calls = 0
    skipped_cached = 0

    print(f"\n  Fetching {year} season ({len(dates)} dates, {start_month}/{year} - {end_month}/{year})")

    for i, date_str in enumerate(dates):
        cache_file = year_dir / f"{date_str}.json"

        # Resume: skip if cached
        if cache_file.exists():
            try:
                with open(cache_file) as f:
                    day_data = json.load(f)
                all_results.extend(day_data.get("events", []))
                skipped_cached += 1
                continue
            except (json.JSONDecodeError, KeyError):
                pass  # Re-fetch corrupt cache

        # Fetch events for this date
        iso_date = f"{date_str}T18:00:00Z"  # ~2hrs before typical first pitch
        events = fetch_historical_events(iso_date, api_key)
        total_api_calls += 1
        time.sleep(1)  # Rate limit: 1 req/sec

        if not events:
            # No games this day — cache empty result
            with open(cache_file, "w") as f:
                json.dump({"date": date_str, "events": []}, f)
            continue

        # Fetch strikeout odds for each event
        day_events = []
        for event in events:
            event_id = event.get("id", "")
            if not event_id:
                continue

            odds_data = fetch_event_strikeout_odds(event_id, iso_date, api_key)
            total_api_calls += 1
            time.sleep(1)  # Rate limit

            day_events.append({
                "event_id": event_id,
                "home_team": event.get("home_team", ""),
                "away_team": event.get("away_team", ""),
                "commence_time": event.get("commence_time", ""),
                "odds": odds_data,
            })

        # Cache the day's results
        with open(cache_file, "w") as f:
            json.dump({"date": date_str, "events": day_events}, f, indent=2)

        all_results.extend(day_events)

        # Progress
        if (i + 1) % 7 == 0:
            print(f"    {date_str} | {i+1}/{len(dates)} dates | "
                  f"{total_api_calls} API calls | {skipped_cached} cached")

    print(f"  Done: {len(all_results)} events, {total_api_calls} API calls, "
          f"{skipped_cached} from cache")
    return all_results


def run_odds_fetcher(seasons: list[int] = None):
    """Main entry point for the odds fetcher.

    Checks API key, estimates credits, checks for confirmation file,
    then fetches if confirmed.
    """
    if seasons is None:
        seasons = [2024]  # Start conservative — just 2024

    print("=" * 60)
    print("RTM PROPS MODEL — HISTORICAL ODDS FETCHER")
    print("=" * 60)

    # 1. Check API key
    api_key = get_api_key()
    if not api_key:
        print("\n⚠ No valid API key found.")
        print("  Set THE_ODDS_API_KEY in .env file:")
        print(f"  {PROJECT_ROOT / '.env'}")
        print("  Then re-run this script.")
        return None

    # 2. Estimate credits
    estimate = estimate_credits(seasons)
    print(f"\n  Seasons to fetch: {estimate['seasons']}")
    print(f"  Estimated game days: {estimate['total_game_days']}")
    print(f"  Estimated events: {estimate['total_events_est']:,}")
    print(f"  Credits for event lists: {estimate['event_list_credits']:,}")
    print(f"  Credits for event odds: {estimate['event_odds_credits']:,}")
    print(f"  TOTAL CREDITS NEEDED: {estimate['total_credits']:,}")
    print(f"  Monthly budget (100K): {'FITS ✓' if estimate['fits_monthly_budget'] else 'EXCEEDS ✗'}")

    if not estimate["fits_monthly_budget"]:
        print("\n⚠ Credit estimate exceeds budget. Reducing to 2024 only.")
        seasons = [2024]
        estimate = estimate_credits(seasons)
        print(f"  Revised total: {estimate['total_credits']:,} credits")

    # 3. Check confirmation file
    confirm_file = ODDS_DIR / ".confirmed"
    if not confirm_file.exists():
        print(f"\n⚠ Confirmation file not found.")
        print(f"  To proceed with API calls, create:")
        print(f"  {confirm_file}")
        print(f"\n  Example: touch {confirm_file}")
        print(f"\n  This is a safety check to prevent accidental credit usage.")
        print(f"  All code is ready — just create that file and re-run.")
        return None

    # 4. Check how much is already cached
    cached_count = 0
    for year in seasons:
        year_dir = ODDS_DIR / str(year)
        if year_dir.exists():
            cached_count += len(list(year_dir.glob("*.json")))
    if cached_count > 0:
        print(f"\n  Found {cached_count} cached day files (will resume)")

    # 5. Fetch
    print("\n  Starting API fetch...")
    all_data = {}
    for year in seasons:
        s_month = 5 if year == 2023 else 4
        e_month = 9 if year == 2025 else 10
        all_data[year] = fetch_season_odds(year, api_key, s_month, e_month)

    # 6. Save combined results
    combined_file = ODDS_DIR / "all_odds_combined.json"
    with open(combined_file, "w") as f:
        json.dump(all_data, f, indent=2, default=str)
    print(f"\n  Saved combined results to {combined_file}")

    return all_data


if __name__ == "__main__":
    import sys
    seasons = [int(s) for s in sys.argv[1:]] if len(sys.argv) > 1 else [2024]
    run_odds_fetcher(seasons)
