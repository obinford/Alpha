"""Supabase database client for the RTM Picks Platform.

Uses httpx against the PostgREST API directly, avoiding heavy SDK
dependencies that may not work in all environments.
"""

import os
from typing import Any

import httpx


class SupabaseClient:
    """Lightweight Supabase PostgREST client."""

    def __init__(self, url: str, key: str) -> None:
        self.base_url = f"{url}/rest/v1"
        self.headers = {
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }

    def _post(self, table: str, data: dict[str, Any]) -> dict:
        resp = httpx.post(
            f"{self.base_url}/{table}",
            headers=self.headers,
            json=data,
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()

    def _post_many(self, table: str, rows: list[dict[str, Any]]) -> list[dict]:
        """Bulk-insert multiple rows in a single POST request."""
        if not rows:
            return []
        resp = httpx.post(
            f"{self.base_url}/{table}",
            headers=self.headers,
            json=rows,
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    def _upsert(
        self, table: str, data: dict[str, Any], on_conflict: str
    ) -> dict:
        headers = {
            **self.headers,
            "Prefer": "return=representation,resolution=merge-duplicates",
        }
        resp = httpx.post(
            f"{self.base_url}/{table}",
            headers=headers,
            json=data,
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()

    def _get(
        self,
        table: str,
        select: str = "*",
        filters: dict[str, str] | None = None,
        order: str | None = None,
        limit: int | None = None,
    ) -> list[dict]:
        params: dict[str, str] = {"select": select}
        if filters:
            for col, val in filters.items():
                params[col] = val
        if order:
            params["order"] = order
        headers = {**self.headers}
        if limit is not None:
            headers["Range"] = f"0-{limit - 1}"
        resp = httpx.get(
            f"{self.base_url}/{table}",
            headers=headers,
            params=params,
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()


def get_supabase() -> SupabaseClient:
    """Create and return a Supabase client using service-role credentials."""
    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        raise RuntimeError(
            "SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in .env"
        )
    return SupabaseClient(url, key)


# ---------------------------------------------------------------------------
# games
# ---------------------------------------------------------------------------

def upsert_game(
    client: SupabaseClient,
    game_id: str,
    sport: str,
    home_team: str,
    away_team: str,
    start_time: str,
    status: str = "upcoming",
) -> None:
    """Insert or update a game row (idempotent on game_id)."""
    client._upsert(
        "games",
        {
            "game_id": game_id,
            "sport": sport,
            "home_team": home_team,
            "away_team": away_team,
            "start_time": start_time,
            "status": status,
        },
        on_conflict="game_id",
    )


# ---------------------------------------------------------------------------
# odds_snapshots
# ---------------------------------------------------------------------------

def insert_odds_snapshot(
    client: SupabaseClient,
    game_id: str,
    sportsbook: str,
    market_type: str,
    home_odds: float,
    away_odds: float,
    spread_value: float | None = None,
    total_value: float | None = None,
) -> None:
    """Insert a single odds snapshot row."""
    client._post(
        "odds_snapshots",
        {
            "game_id": game_id,
            "sportsbook": sportsbook,
            "market_type": market_type,
            "home_odds": home_odds,
            "away_odds": away_odds,
            "spread_value": spread_value,
            "total_value": total_value,
        },
    )


# ---------------------------------------------------------------------------
# true_lines
# ---------------------------------------------------------------------------

def insert_true_line(
    client: SupabaseClient,
    game_id: str,
    market_type: str,
    true_home_prob: float,
    true_away_prob: float,
    sharp_book: str,
    no_vig_line: float | None = None,
) -> None:
    """Insert a devigged true-line row."""
    client._post(
        "true_lines",
        {
            "game_id": game_id,
            "market_type": market_type,
            "true_home_prob": true_home_prob,
            "true_away_prob": true_away_prob,
            "sharp_book": sharp_book,
            "no_vig_line": no_vig_line,
        },
    )


# ---------------------------------------------------------------------------
# ev_opportunities
# ---------------------------------------------------------------------------

def insert_ev_opportunity(
    client: SupabaseClient,
    game_id: str,
    sportsbook: str,
    market_type: str,
    side: str,
    book_odds: float,
    book_implied_prob: float,
    true_prob: float,
    ev_percentage: float,
    kelly_frac: float,
    recommended_units: float,
) -> None:
    """Insert a +EV opportunity row."""
    client._post(
        "ev_opportunities",
        {
            "game_id": game_id,
            "sportsbook": sportsbook,
            "market_type": market_type,
            "side": side,
            "book_odds": book_odds,
            "book_implied_prob": book_implied_prob,
            "true_prob": true_prob,
            "ev_percentage": ev_percentage,
            "kelly_fraction": kelly_frac,
            "recommended_units": recommended_units,
            "status": "open",
        },
    )


def bulk_insert_ev_opportunities(
    client: SupabaseClient,
    rows: list[dict[str, Any]],
) -> None:
    """Bulk-insert +EV opportunity rows in a single request.

    All rows should share the same ``timestamp`` value so
    ``get_latest_ev_opportunities`` can retrieve the full batch.
    """
    client._post_many("ev_opportunities", rows)


def get_open_ev_opportunities(client: SupabaseClient) -> list[dict]:
    """Fetch all currently-open EV opportunities, joined with game info."""
    return client._get(
        "ev_opportunities",
        select="*,games(game_id,sport,home_team,away_team,start_time)",
        filters={"status": "eq.open"},
        order="ev_percentage.desc",
    )


def get_latest_ev_opportunities(
    client: SupabaseClient,
    sport: str | None = None,
    min_ev: float | None = None,
    sportsbook: str | None = None,
) -> list[dict]:
    """Fetch EV opportunities from the most recent scan, with optional filters.

    Finds the latest scan timestamp, then returns all rows from that scan
    joined with game info, sorted by ev_percentage descending.
    """
    # Find the most recent scan timestamp.
    latest = client._get(
        "ev_opportunities",
        select="timestamp",
        order="timestamp.desc",
        limit=1,
    )
    if not latest:
        return []

    latest_ts = latest[0]["timestamp"]

    filters: dict[str, str] = {"timestamp": f"eq.{latest_ts}"}
    if min_ev is not None:
        filters["ev_percentage"] = f"gte.{min_ev}"
    if sportsbook is not None:
        filters["sportsbook"] = f"eq.{sportsbook}"

    results = client._get(
        "ev_opportunities",
        select="*,games(game_id,sport,home_team,away_team,start_time)",
        filters=filters,
        order="ev_percentage.desc",
    )

    if sport is not None:
        results = [r for r in results if r.get("games", {}).get("sport") == sport]

    return results
