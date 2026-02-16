"""Book Profiling Engine — track and exploit sportsbook behavior patterns.

Every sportsbook reacts differently to sharp line movement.  Some are slow
to move props, some overreact to steam, some copy other books late, and
some hang stale alt lines.  This module tracks reaction times and builds
profiles that tell members which book is weakest for which sport and market.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "shared"))

from config import SHARP_BOOKS


class BookProfiler:
    """Analyze sportsbook behavior patterns to find exploitable weaknesses."""

    def __init__(self, db_client: Any | None = None) -> None:
        self._db = db_client

    # ------------------------------------------------------------------
    # Tracking
    # ------------------------------------------------------------------

    def track_book_reaction_time(
        self,
        game_id: str,
        sport: str,
        market_type: str,
        side: str,
        sharp_book: str,
        sharp_move_time: str,
        soft_book: str,
        soft_move_time: str | None = None,
        edge_at_stale: float | None = None,
    ) -> dict | None:
        """Record how long a soft book takes to match a sharp book movement.

        Args:
            game_id: The game this movement is for.
            sport: Sport key (e.g. basketball_nba).
            market_type: h2h, spreads, totals, or player_* prop.
            side: The side that moved (e.g. "Lakers -3.5").
            sharp_book: Which sharp book moved first.
            sharp_move_time: ISO timestamp of sharp book movement.
            soft_book: Which soft book we're tracking.
            soft_move_time: ISO timestamp when soft book matched (None = still stale).
            edge_at_stale: EV% available while the book was stale.

        Returns:
            The inserted row dict, or None on failure.
        """
        if self._db is None:
            return None

        reaction_seconds = None
        was_stale = soft_move_time is None

        if soft_move_time is not None:
            try:
                sharp_dt = datetime.fromisoformat(sharp_move_time.replace("Z", "+00:00"))
                soft_dt = datetime.fromisoformat(soft_move_time.replace("Z", "+00:00"))
                reaction_seconds = round((soft_dt - sharp_dt).total_seconds(), 2)
            except Exception:
                pass

        row = {
            "game_id": game_id,
            "sport": sport,
            "market_type": market_type,
            "side": side,
            "sharp_book": sharp_book,
            "sharp_move_time": sharp_move_time,
            "soft_book": soft_book,
            "soft_move_time": soft_move_time,
            "reaction_seconds": reaction_seconds,
            "was_stale": was_stale,
            "edge_at_stale": edge_at_stale,
        }

        try:
            result = self._db._post("book_reaction_times", row)
            return result
        except Exception as e:
            print(f"Warning: Failed to store book reaction time: {e}")
            return None

    # ------------------------------------------------------------------
    # Analysis
    # ------------------------------------------------------------------

    def calculate_book_profiles(self) -> list[dict]:
        """Calculate exploitability profiles for all tracked sportsbooks.

        Returns a list of book profile dicts sorted by exploitability
        (slowest avg reaction time first).
        """
        if self._db is None:
            return []

        try:
            rows = self._db._get(
                "book_reaction_times",
                select="soft_book,sport,market_type,reaction_seconds,was_stale,edge_at_stale",
            )
        except Exception:
            return []

        if not rows:
            return []

        # Group by soft book.
        by_book: dict[str, list[dict]] = {}
        for r in rows:
            book = r.get("soft_book", "unknown")
            by_book.setdefault(book, []).append(r)

        profiles = []
        for book, records in by_book.items():
            # Skip sharp books — we don't profile them.
            if book in SHARP_BOOKS:
                continue

            reaction_times = [
                r["reaction_seconds"]
                for r in records
                if r.get("reaction_seconds") is not None
            ]
            stale_count = sum(1 for r in records if r.get("was_stale"))
            stale_edges = [
                float(r["edge_at_stale"])
                for r in records
                if r.get("edge_at_stale") is not None
            ]

            avg_reaction = (
                round(sum(reaction_times) / len(reaction_times), 1)
                if reaction_times
                else None
            )
            stale_frequency = (
                round(stale_count / len(records) * 100, 1) if records else 0
            )
            avg_stale_edge = (
                round(sum(stale_edges) / len(stale_edges), 2)
                if stale_edges
                else None
            )

            # Overreaction: reaction_seconds < 0 or very small but overcorrected.
            # We approximate: if reaction < 30s and the book matched, it might overcorrect.
            overreaction_count = sum(
                1 for r in records
                if r.get("reaction_seconds") is not None
                and r["reaction_seconds"] < 30
            )
            overreaction_rate = (
                round(overreaction_count / len(records) * 100, 1)
                if records
                else 0
            )

            # Best sport to exploit (slowest avg reaction by sport).
            by_sport: dict[str, list[float]] = {}
            for r in records:
                if r.get("reaction_seconds") is not None:
                    by_sport.setdefault(r["sport"], []).append(r["reaction_seconds"])

            best_sport = None
            best_sport_time = 0
            for sport, times in by_sport.items():
                avg = sum(times) / len(times)
                if avg > best_sport_time:
                    best_sport_time = avg
                    best_sport = sport

            # Best market to exploit (slowest avg reaction by market type).
            by_market: dict[str, list[float]] = {}
            for r in records:
                if r.get("reaction_seconds") is not None:
                    by_market.setdefault(r["market_type"], []).append(
                        r["reaction_seconds"]
                    )

            best_market = None
            best_market_time = 0
            for mkt, times in by_market.items():
                avg = sum(times) / len(times)
                if avg > best_market_time:
                    best_market_time = avg
                    best_market = mkt

            # Exploitability score: composite of reaction time, stale frequency, avg edge.
            exploit_score = 0.0
            if avg_reaction is not None:
                exploit_score += min(avg_reaction / 10, 50)  # Up to 50 pts for slow reaction
            exploit_score += stale_frequency * 0.3  # Up to 30 pts for frequent stale lines
            if avg_stale_edge is not None:
                exploit_score += min(avg_stale_edge * 2, 20)  # Up to 20 pts for high edge

            # Reaction time by sport breakdown.
            sport_breakdown = {}
            for sport, times in by_sport.items():
                sport_breakdown[sport] = {
                    "avg_reaction_seconds": round(sum(times) / len(times), 1),
                    "sample_size": len(times),
                }

            # Reaction time by market breakdown.
            market_breakdown = {}
            for mkt, times in by_market.items():
                market_breakdown[mkt] = {
                    "avg_reaction_seconds": round(sum(times) / len(times), 1),
                    "sample_size": len(times),
                }

            profiles.append({
                "sportsbook": book,
                "avg_reaction_seconds": avg_reaction,
                "stale_frequency_pct": stale_frequency,
                "overreaction_rate_pct": overreaction_rate,
                "avg_edge_when_stale": avg_stale_edge,
                "best_sport": best_sport,
                "best_sport_reaction": round(best_sport_time, 1) if best_sport else None,
                "best_market": best_market,
                "best_market_reaction": round(best_market_time, 1) if best_market else None,
                "exploit_score": round(exploit_score, 1),
                "total_observations": len(records),
                "sport_breakdown": sport_breakdown,
                "market_breakdown": market_breakdown,
            })

        # Sort by exploit score descending (most exploitable first).
        profiles.sort(key=lambda p: p["exploit_score"], reverse=True)
        return profiles

    def get_weakest_books(
        self, sport: str | None = None, market_type: str | None = None
    ) -> list[dict]:
        """Return books ranked by exploitability for a given sport/market.

        Args:
            sport: Filter to a specific sport key.
            market_type: Filter to a specific market type.

        Returns:
            List of book profiles sorted by exploitability.
        """
        if self._db is None:
            return []

        filters: dict[str, str] = {}
        if sport:
            filters["sport"] = f"eq.{sport}"
        if market_type:
            filters["market_type"] = f"eq.{market_type}"

        try:
            rows = self._db._get(
                "book_reaction_times",
                select="soft_book,sport,market_type,reaction_seconds,was_stale,edge_at_stale",
                filters=filters if filters else None,
            )
        except Exception:
            return []

        if not rows:
            return []

        # Group by soft book and calculate.
        by_book: dict[str, list[dict]] = {}
        for r in rows:
            book = r.get("soft_book", "unknown")
            if book not in SHARP_BOOKS:
                by_book.setdefault(book, []).append(r)

        results = []
        for book, records in by_book.items():
            reaction_times = [
                r["reaction_seconds"]
                for r in records
                if r.get("reaction_seconds") is not None
            ]
            stale_count = sum(1 for r in records if r.get("was_stale"))
            stale_edges = [
                float(r["edge_at_stale"])
                for r in records
                if r.get("edge_at_stale") is not None
            ]

            avg_reaction = (
                round(sum(reaction_times) / len(reaction_times), 1)
                if reaction_times
                else None
            )
            stale_freq = (
                round(stale_count / len(records) * 100, 1) if records else 0
            )
            avg_edge = (
                round(sum(stale_edges) / len(stale_edges), 2)
                if stale_edges
                else None
            )

            results.append({
                "sportsbook": book,
                "avg_reaction_seconds": avg_reaction,
                "stale_frequency_pct": stale_freq,
                "avg_edge_when_stale": avg_edge,
                "observations": len(records),
            })

        results.sort(
            key=lambda r: r["avg_reaction_seconds"] or 0, reverse=True
        )
        return results

    def get_book_report(self, sportsbook: str) -> dict | None:
        """Full deep-dive profile for a single sportsbook.

        Returns a comprehensive report including reaction times by sport,
        market weaknesses, historical edge data, and comparison to sharp timing.
        """
        if self._db is None:
            return None

        try:
            rows = self._db._get(
                "book_reaction_times",
                select="*",
                filters={"soft_book": f"eq.{sportsbook}"},
                order="created_at.desc",
            )
        except Exception:
            return None

        if not rows:
            return None

        reaction_times = [
            r["reaction_seconds"]
            for r in rows
            if r.get("reaction_seconds") is not None
        ]
        stale_count = sum(1 for r in rows if r.get("was_stale"))
        stale_edges = [
            float(r["edge_at_stale"])
            for r in rows
            if r.get("edge_at_stale") is not None
        ]

        # By sport.
        by_sport: dict[str, dict] = {}
        for r in rows:
            sport = r.get("sport", "unknown")
            if sport not in by_sport:
                by_sport[sport] = {"times": [], "stale": 0, "total": 0, "edges": []}
            by_sport[sport]["total"] += 1
            if r.get("reaction_seconds") is not None:
                by_sport[sport]["times"].append(r["reaction_seconds"])
            if r.get("was_stale"):
                by_sport[sport]["stale"] += 1
            if r.get("edge_at_stale") is not None:
                by_sport[sport]["edges"].append(float(r["edge_at_stale"]))

        sport_profiles = {}
        for sport, data in by_sport.items():
            sport_profiles[sport] = {
                "avg_reaction_seconds": (
                    round(sum(data["times"]) / len(data["times"]), 1)
                    if data["times"]
                    else None
                ),
                "stale_frequency_pct": round(data["stale"] / data["total"] * 100, 1),
                "avg_edge_when_stale": (
                    round(sum(data["edges"]) / len(data["edges"]), 2)
                    if data["edges"]
                    else None
                ),
                "observations": data["total"],
            }

        # By market type.
        by_market: dict[str, dict] = {}
        for r in rows:
            mkt = r.get("market_type", "unknown")
            if mkt not in by_market:
                by_market[mkt] = {"times": [], "stale": 0, "total": 0, "edges": []}
            by_market[mkt]["total"] += 1
            if r.get("reaction_seconds") is not None:
                by_market[mkt]["times"].append(r["reaction_seconds"])
            if r.get("was_stale"):
                by_market[mkt]["stale"] += 1
            if r.get("edge_at_stale") is not None:
                by_market[mkt]["edges"].append(float(r["edge_at_stale"]))

        market_profiles = {}
        for mkt, data in by_market.items():
            market_profiles[mkt] = {
                "avg_reaction_seconds": (
                    round(sum(data["times"]) / len(data["times"]), 1)
                    if data["times"]
                    else None
                ),
                "stale_frequency_pct": round(data["stale"] / data["total"] * 100, 1),
                "avg_edge_when_stale": (
                    round(sum(data["edges"]) / len(data["edges"]), 2)
                    if data["edges"]
                    else None
                ),
                "observations": data["total"],
            }

        # Recent stale lines (last 20).
        recent_stale = [
            {
                "game_id": r["game_id"],
                "sport": r["sport"],
                "market_type": r["market_type"],
                "side": r["side"],
                "sharp_book": r["sharp_book"],
                "sharp_move_time": r["sharp_move_time"],
                "edge_at_stale": r.get("edge_at_stale"),
                "created_at": r.get("created_at"),
            }
            for r in rows
            if r.get("was_stale")
        ][:20]

        return {
            "sportsbook": sportsbook,
            "avg_reaction_seconds": (
                round(sum(reaction_times) / len(reaction_times), 1)
                if reaction_times
                else None
            ),
            "stale_frequency_pct": (
                round(stale_count / len(rows) * 100, 1) if rows else 0
            ),
            "avg_edge_when_stale": (
                round(sum(stale_edges) / len(stale_edges), 2)
                if stale_edges
                else None
            ),
            "total_observations": len(rows),
            "by_sport": sport_profiles,
            "by_market": market_profiles,
            "recent_stale_lines": recent_stale,
        }


def track_reactions_from_movements(
    db_client: Any,
    profiler: BookProfiler,
    recent_movements: list[dict],
) -> int:
    """Analyze recent line movements to detect sharp book moves and track soft book reactions.

    Called during each scan cycle after storing line movements.

    Args:
        db_client: Supabase client.
        profiler: BookProfiler instance.
        recent_movements: Line movement rows from the current scan.

    Returns:
        Number of reaction records created.
    """
    if not recent_movements:
        return 0

    # Group movements by (game_id, market_type, side).
    groups: dict[tuple[str, str, str], list[dict]] = {}
    for mv in recent_movements:
        key = (mv.get("game_id", ""), mv.get("market_type", ""), mv.get("side", ""))
        groups.setdefault(key, []).append(mv)

    count = 0
    for (game_id, market_type, side), moves in groups.items():
        # Find sharp book moves.
        sharp_moves = [m for m in moves if m.get("bookmaker") in SHARP_BOOKS]
        if not sharp_moves:
            continue

        # Get the earliest sharp move.
        sharp_move = min(sharp_moves, key=lambda m: m.get("timestamp", ""))
        sharp_time = sharp_move.get("timestamp")
        sharp_book = sharp_move.get("bookmaker", "")
        sport = sharp_move.get("sport", "")

        if not sharp_time:
            continue

        # Track soft book reactions.
        soft_moves = [m for m in moves if m.get("bookmaker") not in SHARP_BOOKS]

        # Books that moved (have reaction time).
        for sm in soft_moves:
            soft_time = sm.get("timestamp")
            profiler.track_book_reaction_time(
                game_id=game_id,
                sport=sport,
                market_type=market_type,
                side=side,
                sharp_book=sharp_book,
                sharp_move_time=sharp_time,
                soft_book=sm.get("bookmaker", ""),
                soft_move_time=soft_time,
            )
            count += 1

    return count
