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
        # Persistent client for connection pooling across requests.
        self._http = httpx.Client(timeout=15)

    def _post(self, table: str, data: dict[str, Any]) -> dict:
        resp = self._http.post(
            f"{self.base_url}/{table}",
            headers=self.headers,
            json=data,
        )
        resp.raise_for_status()
        return resp.json()

    def _post_many(
        self, table: str, rows: list[dict[str, Any]], chunk_size: int = 100
    ) -> list[dict]:
        """Bulk-insert multiple rows, batched in chunks to avoid 400 errors.

        Supabase/PostgREST rejects very large payloads.  Splitting into
        chunks of ``chunk_size`` (default 100) keeps each request well
        within limits while still being far faster than row-by-row.
        """
        if not rows:
            return []
        results: list[dict] = []
        for i in range(0, len(rows), chunk_size):
            chunk = rows[i : i + chunk_size]
            resp = self._http.post(
                f"{self.base_url}/{table}",
                headers=self.headers,
                json=chunk,
                timeout=30,
            )
            if resp.status_code >= 400:
                # Log the actual Supabase error body before raising.
                try:
                    body = resp.text
                except Exception:
                    body = "<unreadable>"
                print(
                    f"  [DB] Supabase error on {table} "
                    f"(chunk {i // chunk_size + 1}, "
                    f"{len(chunk)} rows, HTTP {resp.status_code}): {body}"
                )
            resp.raise_for_status()
            results.extend(resp.json())
        return results

    def _upsert(
        self, table: str, data: dict[str, Any], on_conflict: str
    ) -> dict:
        headers = {
            **self.headers,
            "Prefer": "return=representation,resolution=merge-duplicates",
        }
        resp = self._http.post(
            f"{self.base_url}/{table}",
            headers=headers,
            json=data,
        )
        resp.raise_for_status()
        return resp.json()

    def _upsert_many(
        self,
        table: str,
        rows: list[dict[str, Any]],
        on_conflict: str,
        chunk_size: int = 100,
    ) -> list[dict]:
        """Bulk-upsert multiple rows, batched in chunks.

        Same as _post_many but with merge-duplicates resolution on the
        specified conflict column(s).
        """
        if not rows:
            return []
        headers = {
            **self.headers,
            "Prefer": "return=representation,resolution=merge-duplicates",
        }
        results: list[dict] = []
        for i in range(0, len(rows), chunk_size):
            chunk = rows[i : i + chunk_size]
            resp = self._http.post(
                f"{self.base_url}/{table}",
                headers=headers,
                json=chunk,
                timeout=30,
            )
            if resp.status_code >= 400:
                try:
                    body = resp.text
                except Exception:
                    body = "<unreadable>"
                print(
                    f"  [DB] Supabase error on {table} "
                    f"(chunk {i // chunk_size + 1}, "
                    f"{len(chunk)} rows, HTTP {resp.status_code}): {body}"
                )
            resp.raise_for_status()
            results.extend(resp.json())
        return results

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
        resp = self._http.get(
            f"{self.base_url}/{table}",
            headers=headers,
            params=params,
        )
        resp.raise_for_status()
        return resp.json()

    def _patch_by_ids(
        self,
        table: str,
        id_column: str,
        ids: list,
        data: dict[str, Any],
    ) -> None:
        """Batch-PATCH rows matching an IN filter on *id_column*.

        Sends one PATCH per chunk of 100 IDs, applying the same *data*
        update to all matching rows.
        """
        if not ids:
            return
        for i in range(0, len(ids), 100):
            chunk = ids[i : i + 100]
            id_list = ",".join(str(x) for x in chunk)
            resp = self._http.patch(
                f"{self.base_url}/{table}",
                headers={**self.headers, "Prefer": "return=minimal"},
                params={id_column: f"in.({id_list})"},
                json=data,
                timeout=30,
            )
            resp.raise_for_status()


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


# ---------------------------------------------------------------------------
# line_movements
# ---------------------------------------------------------------------------

def get_latest_odds_for_game(
    client: SupabaseClient,
    game_id: str,
) -> list[dict]:
    """Fetch the most recent odds row for each bookmaker/market/side combo."""
    return client._get(
        "line_movements",
        select="bookmaker,market_type,side,odds,timestamp",
        filters={"game_id": f"eq.{game_id}"},
        order="timestamp.desc",
    )


def bulk_insert_line_movements(
    client: SupabaseClient,
    rows: list[dict[str, Any]],
) -> None:
    """Bulk-insert line movement rows in a single request."""
    if rows:
        client._post_many("line_movements", rows)


def get_line_movements_for_game(
    client: SupabaseClient,
    game_id: str,
    market_type: str | None = None,
) -> list[dict]:
    """Full odds history for a game, all bookmakers, sorted by timestamp."""
    filters: dict[str, str] = {"game_id": f"eq.{game_id}"}
    if market_type is not None:
        filters["market_type"] = f"eq.{market_type}"
    return client._get(
        "line_movements",
        select="*",
        filters=filters,
        order="timestamp.asc",
    )


def get_biggest_recent_moves(
    client: SupabaseClient,
    since: str,
    limit: int = 20,
) -> list[dict]:
    """Top line movements by absolute odds_change since a given timestamp."""
    return client._get(
        "line_movements",
        select="*,games(game_id,sport,home_team,away_team,start_time)",
        filters={
            "timestamp": f"gte.{since}",
            "odds_change": "not.is.null",
        },
        order="odds_change.desc",
        limit=limit,
    )


# ---------------------------------------------------------------------------
# steam_alerts
# ---------------------------------------------------------------------------

def bulk_insert_steam_alerts(
    client: SupabaseClient,
    rows: list[dict[str, Any]],
) -> None:
    """Bulk-insert steam alert rows."""
    if rows:
        client._post_many("steam_alerts", rows)


def get_recent_steam_alerts(
    client: SupabaseClient,
    since: str,
    sport: str | None = None,
) -> list[dict]:
    """Active steam alerts since a timestamp, sorted by detected_at desc."""
    filters: dict[str, str] = {
        "detected_at": f"gte.{since}",
        "status": "eq.active",
    }
    if sport is not None:
        filters["sport"] = f"eq.{sport}"
    return client._get(
        "steam_alerts",
        select="*,games(game_id,sport,home_team,away_team,start_time)",
        filters=filters,
        order="detected_at.desc",
    )


def get_recent_steam_alert_keys(
    client: SupabaseClient,
    since: str,
) -> list[dict]:
    """Fetch recent alert identifiers to avoid duplicates."""
    return client._get(
        "steam_alerts",
        select="game_id,market_type,side,detected_at",
        filters={"detected_at": f"gte.{since}"},
        order="detected_at.desc",
    )
