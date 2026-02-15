"""Fetch game scores from The Odds API and update the games table.

Uses the /scores endpoint which returns completed/in-progress game results.
Only fetches scores for sports that have games today to conserve API usage.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "shared"))

import httpx
from datetime import datetime, timedelta, timezone

from config import ODDS_API_BASE_URL

API_BASE = ODDS_API_BASE_URL

# Shared httpx client for connection pooling.
_score_http = httpx.Client(timeout=15)


def fetch_scores(sport_key: str, days_from: int = 1) -> list[dict]:
    """Fetch scores for a sport from The Odds API.

    Args:
        sport_key: API sport key (e.g. 'basketball_nba').
        days_from: Number of days to look back (1-3).

    Returns:
        List of score dicts with game_id, home_team, away_team, scores, completed.
    """
    api_key = os.environ.get("THE_ODDS_API_KEY", "")
    if not api_key:
        return []

    try:
        resp = _score_http.get(
            f"{API_BASE}/{sport_key}/scores",
            params={
                "apiKey": api_key,
                "daysFrom": days_from,
            },
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"  Warning: Score fetch failed for {sport_key}: {e}")
        return []


def update_game_scores(db_client: object, sport_key: str, days_from: int = 1) -> int:
    """Fetch scores and update the games table for completed games.

    Returns the number of games updated to 'final'.
    """
    from db import SupabaseClient

    client: SupabaseClient = db_client  # type: ignore[assignment]
    scores = fetch_scores(sport_key, days_from)
    if not scores:
        return 0

    updated = 0
    for game in scores:
        if not game.get("completed", False):
            continue

        game_id = game.get("id", "")
        scores_list = game.get("scores")
        if not scores_list or len(scores_list) < 2:
            continue

        # Parse home and away scores.
        home_team = game.get("home_team", "")
        away_team = game.get("away_team", "")
        home_score = None
        away_score = None

        for s in scores_list:
            if s.get("name") == home_team:
                home_score = int(s.get("score", 0))
            elif s.get("name") == away_team:
                away_score = int(s.get("score", 0))

        if home_score is None or away_score is None:
            continue

        # Update the game in Supabase.
        try:
            resp = client._http.patch(
                f"{client.base_url}/games",
                headers={**client.headers, "Prefer": "return=minimal"},
                params={"game_id": f"eq.{game_id}"},
                json={
                    "home_score": home_score,
                    "away_score": away_score,
                    "status": "final",
                },
                timeout=10,
            )
            resp.raise_for_status()
            updated += 1
        except Exception:
            pass

    return updated


def fetch_and_update_scores(db_client: object, sport_keys: list[str]) -> int:
    """Fetch scores for all given sports and update games table.

    Only fetches for sports that have games today in the database.
    Returns total number of games updated.
    """
    from db import SupabaseClient

    client: SupabaseClient = db_client  # type: ignore[assignment]
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday_start = today_start - timedelta(days=1)

    total = 0
    for sport_key in sport_keys:
        # Check if this sport has upcoming/recent games.
        try:
            games = client._get(
                "games",
                select="game_id",
                filters={
                    "sport": f"eq.{sport_key}",
                    "start_time": f"gte.{yesterday_start.isoformat()}",
                },
                limit=1,
            )
            if not games:
                continue
        except Exception:
            continue

        count = update_game_scores(client, sport_key, days_from=2)
        if count:
            print(f"  Scores: {count} {sport_key} game(s) updated to final.")
        total += count

    return total
