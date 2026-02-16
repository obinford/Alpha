"""Stale Line Detection Engine — find books that haven't caught up to sharp moves.

A stale line is when one book hasn't moved but the sharp consensus has.
This is structural edge — the most actionable type of signal because
the book is provably behind the market.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "shared"))

from config import SHARP_BOOKS


# Minimum EV% difference to qualify as a stale line.
STALE_THRESHOLD_EV = 2.0

# Minimum number of sharp books that must agree.
MIN_SHARP_AGREEMENT = 2


class StaleLineDetector:
    """Detect and track stale lines across sportsbooks."""

    def __init__(self, db_client: Any | None = None) -> None:
        self._db = db_client
        # Cache of avg reaction seconds per (book, sport) — preloaded once.
        self._reaction_cache: dict[tuple[str, str], float] | None = None

    def _preload_reaction_cache(self, books: set[str], sports: set[str]) -> None:
        """Batch-load average reaction times for all soft book/sport combos.

        Replaces per-stale-line DB queries in _classify_stale_type with a
        single query up front.
        """
        if self._db is None or self._reaction_cache is not None:
            return
        self._reaction_cache = {}
        try:
            rows = self._db._get(
                "book_reaction_times",
                select="soft_book,sport,reaction_seconds",
            )
            # Group by (book, sport) and compute average.
            totals: dict[tuple[str, str], list[float]] = {}
            for r in rows:
                if r.get("reaction_seconds") is None:
                    continue
                key = (r["soft_book"], r["sport"])
                totals.setdefault(key, []).append(float(r["reaction_seconds"]))
            for key, times in totals.items():
                self._reaction_cache[key] = sum(times) / len(times)
        except Exception:
            self._reaction_cache = {}

    def detect_stale_lines(self, current_odds_snapshot: list[dict]) -> list[dict]:
        """Detect stale lines from a current odds snapshot.

        For every game+market+side combination:
        1. Get current odds from ALL books.
        2. Calculate consensus odds (average across sharp books).
        3. For each soft book, check if odds differ significantly.
        4. If difference creates >= 2% EV, flag as stale.

        Args:
            current_odds_snapshot: List of odds dicts with keys:
                game_id, sport, market_type, side, bookmaker, odds

        Returns:
            List of stale line dicts.
        """
        # Preload reaction times so _classify_stale_type doesn't N+1 query.
        all_books = {s.get("bookmaker", "") for s in current_odds_snapshot}
        all_sports = {s.get("sport", "") for s in current_odds_snapshot}
        self._preload_reaction_cache(all_books, all_sports)

        # Group by (game_id, market_type, side).
        groups: dict[tuple[str, str, str], list[dict]] = {}
        for snap in current_odds_snapshot:
            key = (
                snap.get("game_id", ""),
                snap.get("market_type", ""),
                snap.get("side", ""),
            )
            groups.setdefault(key, []).append(snap)

        stale_lines = []

        for (game_id, market_type, side), odds_list in groups.items():
            # Separate sharp and soft books.
            sharp_odds = []
            soft_entries = []
            sport = ""

            for entry in odds_list:
                book = entry.get("bookmaker", "")
                odds_val = float(entry.get("odds", 0))
                sport = entry.get("sport", sport)

                if book in SHARP_BOOKS:
                    sharp_odds.append(odds_val)
                else:
                    soft_entries.append(entry)

            # Need at least MIN_SHARP_AGREEMENT sharp books to establish consensus.
            if len(sharp_odds) < MIN_SHARP_AGREEMENT:
                continue

            consensus = sum(sharp_odds) / len(sharp_odds)

            # Check each soft book against consensus.
            for soft in soft_entries:
                soft_odds = float(soft.get("odds", 0))
                book = soft.get("bookmaker", "")

                # Calculate implied edge.
                edge_pct = self._calculate_edge(soft_odds, consensus)

                if edge_pct >= STALE_THRESHOLD_EV:
                    stale_type = self._classify_stale_type(
                        book, sport, market_type
                    )

                    stale_lines.append({
                        "game_id": game_id,
                        "sport": sport,
                        "market_type": market_type,
                        "side": side,
                        "stale_book": book,
                        "stale_odds": soft_odds,
                        "consensus_odds": round(consensus, 1),
                        "edge_percentage": round(edge_pct, 2),
                        "stale_type": stale_type,
                        "detected_at": datetime.now(timezone.utc).isoformat(),
                        "status": "active",
                    })

        # Sort by edge descending.
        stale_lines.sort(key=lambda s: s["edge_percentage"], reverse=True)
        return stale_lines

    def _calculate_edge(self, stale_odds: float, consensus_odds: float) -> float:
        """Calculate EV edge between stale odds and sharp consensus.

        Uses implied probability comparison.
        """
        stale_prob = self._odds_to_implied(stale_odds)
        consensus_prob = self._odds_to_implied(consensus_odds)

        if stale_prob <= 0 or consensus_prob <= 0:
            return 0.0

        # Edge = (true_prob * decimal_odds) - 1, expressed as percentage.
        stale_decimal = self._american_to_decimal(stale_odds)
        ev = (consensus_prob * stale_decimal - 1) * 100
        return max(0.0, ev)

    def _odds_to_implied(self, american_odds: float) -> float:
        """Convert American odds to implied probability."""
        if american_odds >= 100:
            return 100 / (american_odds + 100)
        elif american_odds <= -100:
            return abs(american_odds) / (abs(american_odds) + 100)
        return 0.5

    def _american_to_decimal(self, american_odds: float) -> float:
        """Convert American odds to decimal odds."""
        if american_odds >= 100:
            return (american_odds / 100) + 1
        elif american_odds <= -100:
            return (100 / abs(american_odds)) + 1
        return 2.0

    def _classify_stale_type(
        self, book: str, sport: str, market_type: str
    ) -> str:
        """Classify why this line is stale.

        Uses cached reaction times (preloaded in detect_stale_lines) to
        avoid per-line DB queries.
        """
        if self._reaction_cache:
            avg_time = self._reaction_cache.get((book, sport))
            if avg_time is not None and avg_time > 300:  # > 5 min average
                return "SLOW_MOVER"

        # Default classification based on market type.
        if market_type.startswith("player_"):
            return "SLOW_MOVER"
        return "POST_STEAM"

    def store_stale_lines(self, stale_lines: list[dict]) -> int:
        """Store new stale line alerts in Supabase.

        Deduplicates against existing active alerts for the same game/market/side/book.
        Returns number of new alerts stored.
        """
        if not stale_lines or self._db is None:
            return 0

        # Get existing active alerts for dedup.
        try:
            existing = self._db._get(
                "stale_line_alerts",
                select="game_id,market_type,side,stale_book",
                filters={"status": "eq.active"},
            )
            existing_keys = {
                (r["game_id"], r["market_type"], r["side"], r["stale_book"])
                for r in existing
            }
        except Exception:
            existing_keys = set()

        new_alerts = []
        for sl in stale_lines:
            key = (sl["game_id"], sl["market_type"], sl["side"], sl["stale_book"])
            if key not in existing_keys:
                new_alerts.append({
                    "game_id": sl["game_id"],
                    "sport": sl["sport"],
                    "market_type": sl["market_type"],
                    "side": sl["side"],
                    "stale_book": sl["stale_book"],
                    "stale_odds": sl["stale_odds"],
                    "consensus_odds": sl["consensus_odds"],
                    "edge_percentage": sl["edge_percentage"],
                    "stale_type": sl["stale_type"],
                    "status": "active",
                })

        if new_alerts:
            try:
                self._db._post_many("stale_line_alerts", new_alerts)
            except Exception as e:
                print(f"Warning: Failed to store stale line alerts: {e}")
                return 0

        return len(new_alerts)

    def resolve_stale_lines(self, current_odds_snapshot: list[dict]) -> int:
        """Resolve stale lines that have been corrected (book caught up).

        Returns number of resolved alerts.
        """
        if self._db is None:
            return 0

        try:
            active = self._db._get(
                "stale_line_alerts",
                select="id,game_id,market_type,side,stale_book,consensus_odds",
                filters={"status": "eq.active"},
            )
        except Exception:
            return 0

        if not active:
            return 0

        # Build current odds lookup.
        current_map: dict[tuple[str, str, str, str], float] = {}
        for snap in current_odds_snapshot:
            key = (
                snap.get("game_id", ""),
                snap.get("market_type", ""),
                snap.get("side", ""),
                snap.get("bookmaker", ""),
            )
            current_map[key] = float(snap.get("odds", 0))

        resolved_count = 0
        now = datetime.now(timezone.utc).isoformat()

        for alert in active:
            key = (
                alert["game_id"],
                alert["market_type"],
                alert["side"],
                alert["stale_book"],
            )
            current_odds = current_map.get(key)

            if current_odds is not None:
                # Check if the edge has dropped below threshold.
                edge = self._calculate_edge(current_odds, alert["consensus_odds"])
                if edge < STALE_THRESHOLD_EV:
                    # Book caught up — resolve.
                    try:
                        self._db._http.patch(
                            f"{self._db.base_url}/stale_line_alerts",
                            headers=self._db.headers,
                            params={"id": f"eq.{alert['id']}"},
                            json={"status": "resolved", "resolved_at": now},
                        )
                        resolved_count += 1
                    except Exception:
                        pass

        return resolved_count

    def get_active_stale_lines(self) -> list[dict]:
        """Return all currently active stale lines sorted by edge%."""
        if self._db is None:
            return []

        try:
            return self._db._get(
                "stale_line_alerts",
                select="*",
                filters={"status": "eq.active"},
                order="edge_percentage.desc",
            )
        except Exception:
            return []

    def get_stale_line_history(self, days: int = 7) -> list[dict]:
        """Return resolved stale lines from the past N days."""
        if self._db is None:
            return []

        since = (
            datetime.now(timezone.utc) - timedelta(days=days)
        ).isoformat()

        try:
            return self._db._get(
                "stale_line_alerts",
                select="*",
                filters={
                    "status": "eq.resolved",
                    "detected_at": f"gte.{since}",
                },
                order="detected_at.desc",
            )
        except Exception:
            return []


def build_odds_snapshot_from_games(games: list) -> list[dict]:
    """Build a flat odds snapshot list from Game objects for stale detection.

    Args:
        games: List of Game objects from the odds API.

    Returns:
        Flat list of dicts with game_id, sport, market_type, side, bookmaker, odds.
    """
    snapshot = []
    for game in games:
        for bk in game.bookmakers:
            for mkt in bk.markets:
                for outcome in mkt.outcomes:
                    if outcome.description:
                        point_str = (
                            f" {outcome.point}" if outcome.point is not None else ""
                        )
                        side = f"{outcome.description} {outcome.name}{point_str}"
                    else:
                        side = outcome.name + (
                            f" {outcome.point}" if outcome.point is not None else ""
                        )
                    snapshot.append({
                        "game_id": game.id,
                        "sport": game.sport_key,
                        "market_type": mkt.key,
                        "side": side,
                        "bookmaker": bk.key,
                        "odds": outcome.price,
                    })
    return snapshot
