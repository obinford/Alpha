#!/usr/bin/env python3
"""Closing Line Value (CLV) tracker for the RTM Picks Platform.

CLV measures how our bet odds compare to the closing line (odds at game start).
Positive CLV = we got better odds than the market settled on = proven edge.

Flow:
1. When an EV opportunity is found, a CLV record is created with status='open'.
2. Near game start (or shortly after), this module fetches the closing odds
   and calculates CLV.
3. Records are updated with closing_odds, closing_true_prob, and clv_percentage.

Usage:
    python backend/scrapers/clv_tracker.py          # process all open CLV records
    python backend/scrapers/clv_tracker.py --stats   # show CLV summary stats
"""

import os
import sys
from datetime import datetime, timedelta, timezone

# Allow running as a standalone script from the repo root.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "shared"))

from dotenv import load_dotenv

from models.ev_calculator import (
    american_to_implied_prob,
    calculate_no_vig_probability,
)


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def create_clv_record(
    client: object,
    game_id: str,
    sport: str,
    sportsbook: str,
    market_type: str,
    side: str,
    bet_odds: float,
    bet_true_prob: float,
    ev_at_bet: float,
    bet_timestamp: str,
) -> None:
    """Create an open CLV record when an EV opportunity is found."""
    from db import SupabaseClient

    db: SupabaseClient = client  # type: ignore[assignment]
    db._post("clv_records", {
        "game_id": game_id,
        "sport": sport,
        "sportsbook": sportsbook,
        "market_type": market_type,
        "side": side,
        "bet_odds": bet_odds,
        "bet_true_prob": round(bet_true_prob, 6),
        "ev_at_bet": round(ev_at_bet, 2),
        "bet_timestamp": bet_timestamp,
        "status": "open",
    })


def bulk_create_clv_records(
    client: object,
    rows: list[dict],
) -> None:
    """Bulk-insert CLV records."""
    from db import SupabaseClient

    db: SupabaseClient = client  # type: ignore[assignment]
    if rows:
        db._post_many("clv_records", rows)


def get_open_clv_records(client: object) -> list[dict]:
    """Fetch all CLV records that haven't been closed yet."""
    from db import SupabaseClient

    db: SupabaseClient = client  # type: ignore[assignment]
    return db._get(
        "clv_records",
        select="*,games(game_id,sport,home_team,away_team,start_time,status)",
        filters={"status": "eq.open"},
        order="bet_timestamp.asc",
    )


def get_clv_records(
    client: object,
    sport: str | None = None,
    hours: int = 72,
    status: str | None = None,
) -> list[dict]:
    """Fetch CLV records with optional filters."""
    from db import SupabaseClient

    db: SupabaseClient = client  # type: ignore[assignment]
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()

    filters: dict[str, str] = {
        "created_at": f"gte.{since}",
    }
    if sport:
        filters["sport"] = f"eq.{sport}"
    if status:
        filters["status"] = f"eq.{status}"

    return db._get(
        "clv_records",
        select="*,games(game_id,sport,home_team,away_team,start_time)",
        filters=filters,
        order="created_at.desc",
    )


def get_clv_summary(client: object, days: int = 30) -> dict:
    """Calculate CLV summary statistics."""
    from db import SupabaseClient

    db: SupabaseClient = client  # type: ignore[assignment]
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    closed = db._get(
        "clv_records",
        select="clv_percentage,devigged_clv,ev_at_bet,sport",
        filters={
            "status": "eq.closed",
            "created_at": f"gte.{since}",
        },
    )

    if not closed:
        return {
            "total_records": 0,
            "avg_clv": 0,
            "avg_devigged_clv": 0,
            "positive_clv_pct": 0,
            "avg_ev_at_bet": 0,
            "by_sport": {},
            "days": days,
        }

    clvs = [float(r["clv_percentage"]) for r in closed if r.get("clv_percentage") is not None]
    devigged_clvs = [float(r["devigged_clv"]) for r in closed if r.get("devigged_clv") is not None]
    evs = [float(r["ev_at_bet"]) for r in closed]

    # By sport.
    by_sport: dict[str, list[float]] = {}
    by_sport_devigged: dict[str, list[float]] = {}
    for r in closed:
        sport = r.get("sport", "unknown")
        clv = r.get("clv_percentage")
        dclv = r.get("devigged_clv")
        if clv is not None:
            by_sport.setdefault(sport, []).append(float(clv))
        if dclv is not None:
            by_sport_devigged.setdefault(sport, []).append(float(dclv))

    sport_stats = {}
    for sport, sport_clvs in by_sport.items():
        d_clvs = by_sport_devigged.get(sport, [])
        sport_stats[sport] = {
            "count": len(sport_clvs),
            "avg_clv": round(sum(sport_clvs) / len(sport_clvs), 2) if sport_clvs else 0,
            "avg_devigged_clv": round(sum(d_clvs) / len(d_clvs), 2) if d_clvs else 0,
            "positive_pct": round(
                sum(1 for c in sport_clvs if c > 0) / len(sport_clvs) * 100, 1
            ) if sport_clvs else 0,
        }

    positive_count = sum(1 for c in clvs if c > 0)
    return {
        "total_records": len(closed),
        "avg_clv": round(sum(clvs) / len(clvs), 2) if clvs else 0,
        "avg_devigged_clv": round(sum(devigged_clvs) / len(devigged_clvs), 2) if devigged_clvs else 0,
        "positive_clv_pct": round(positive_count / len(clvs) * 100, 1) if clvs else 0,
        "avg_ev_at_bet": round(sum(evs) / len(evs), 2) if evs else 0,
        "by_sport": sport_stats,
        "days": days,
    }


# ---------------------------------------------------------------------------
# CLV calculation
# ---------------------------------------------------------------------------

def calculate_clv(bet_implied_prob: float, closing_implied_prob: float) -> float:
    """Calculate CLV as percentage.

    CLV = (closing_prob - bet_implied_prob) / bet_implied_prob * 100

    Positive = we got better odds than closing (edge confirmed).
    Negative = line moved against us.
    """
    if bet_implied_prob <= 0:
        return 0.0
    return (closing_implied_prob - bet_implied_prob) / bet_implied_prob * 100


def get_closing_odds_from_snapshots(
    client: object,
    game_id: str,
    market_type: str,
    side: str,
    sportsbook: str,
) -> float | None:
    """Get the most recent odds for a game/market/side/book combo.

    This serves as the "closing" odds — the last recorded odds before game start.
    """
    from db import SupabaseClient

    db: SupabaseClient = client  # type: ignore[assignment]

    rows = db._get(
        "line_movements",
        select="odds,timestamp",
        filters={
            "game_id": f"eq.{game_id}",
            "bookmaker": f"eq.{sportsbook}",
            "market_type": f"eq.{market_type}",
            "side": f"eq.{side}",
        },
        order="timestamp.desc",
        limit=1,
    )

    if rows:
        return float(rows[0]["odds"])
    return None


def get_closing_sharp_line(
    client: object,
    game_id: str,
    market_type: str,
    side: str,
) -> float | None:
    """Get the closing true probability from the sharp book (devigged).

    Looks at the most recent true_lines entry for the game/market
    and maps the side string to the correct probability.
    """
    from db import SupabaseClient

    db: SupabaseClient = client  # type: ignore[assignment]

    # Get the closing true line.
    true_rows = db._get(
        "true_lines",
        select="true_home_prob,true_away_prob,timestamp",
        filters={
            "game_id": f"eq.{game_id}",
            "market_type": f"eq.{market_type}",
        },
        order="timestamp.desc",
        limit=1,
    )

    if not true_rows:
        return None

    row = true_rows[0]
    home_prob = float(row.get("true_home_prob", 0))
    away_prob = float(row.get("true_away_prob", 0))

    if not home_prob and not away_prob:
        return None

    # Get game info to match side to home/away.
    game_rows = db._get(
        "games",
        select="home_team,away_team",
        filters={"game_id": f"eq.{game_id}"},
        limit=1,
    )

    side_lower = side.lower().strip()

    if not game_rows:
        # Can't determine team — use heuristic.
        if "over" in side_lower:
            return home_prob
        elif "under" in side_lower:
            return away_prob
        return None

    home_team = (game_rows[0].get("home_team", "") or "").lower()
    away_team = (game_rows[0].get("away_team", "") or "").lower()

    # Match side to team name.
    if home_team and home_team in side_lower:
        return home_prob
    elif away_team and away_team in side_lower:
        return away_prob
    # Totals: Over/Under.
    elif "over" in side_lower:
        return home_prob
    elif "under" in side_lower:
        return away_prob

    return None


# ---------------------------------------------------------------------------
# CLV processing
# ---------------------------------------------------------------------------

def process_open_records(client: object) -> tuple[int, int]:
    """Process all open CLV records.

    For games that have started, capture closing odds and compute CLV.
    Batched: pre-loads closing odds/lines in bulk, then patches in bulk.
    Returns (processed_count, expired_count).
    """
    records = get_open_clv_records(client)
    if not records:
        return 0, 0

    now = datetime.now(timezone.utc)

    from db import SupabaseClient
    from config import CLV_EXPIRATION_HOURS

    db: SupabaseClient = client  # type: ignore[assignment]

    # Partition records into actionable vs not-yet-started.
    expired_ids: list = []
    to_process: list[dict] = []

    for rec in records:
        game = rec.get("games", {})
        if not game:
            continue
        start_str = game.get("start_time", "")
        if not start_str:
            continue
        game_start = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
        if game_start > now:
            continue
        if (now - game_start).total_seconds() > CLV_EXPIRATION_HOURS * 3600:
            expired_ids.append(rec["id"])
        else:
            to_process.append(rec)

    # Bulk-expire old records in one PATCH.
    if expired_ids:
        try:
            db._patch_by_ids("clv_records", "id", expired_ids, {"status": "expired"})
        except Exception:
            pass

    if not to_process:
        return 0, len(expired_ids)

    # Bulk-fetch closing odds: latest line_movements for all game IDs.
    game_ids = list({r["game_id"] for r in to_process})
    all_movements: list[dict] = []
    for i in range(0, len(game_ids), 50):
        chunk = game_ids[i : i + 50]
        id_list = ",".join(chunk)
        try:
            rows = db._get(
                "line_movements",
                select="game_id,bookmaker,market_type,side,odds,timestamp",
                filters={"game_id": f"in.({id_list})"},
                order="timestamp.desc",
            )
            all_movements.extend(rows)
        except Exception:
            pass

    # Build lookup: (game_id, bookmaker, market_type, side) -> latest odds.
    closing_odds_map: dict[tuple[str, str, str, str], float] = {}
    for mv in all_movements:
        key = (mv["game_id"], mv.get("bookmaker", ""), mv.get("market_type", ""), mv.get("side", ""))
        if key not in closing_odds_map:
            closing_odds_map[key] = float(mv["odds"])

    # Bulk-fetch closing true lines for all game IDs.
    all_true_lines: list[dict] = []
    for i in range(0, len(game_ids), 50):
        chunk = game_ids[i : i + 50]
        id_list = ",".join(chunk)
        try:
            rows = db._get(
                "true_lines",
                select="game_id,market_type,true_home_prob,true_away_prob,timestamp",
                filters={"game_id": f"in.({id_list})"},
                order="timestamp.desc",
            )
            all_true_lines.extend(rows)
        except Exception:
            pass

    # Build lookup: (game_id, market_type) -> (home_prob, away_prob).
    true_line_map: dict[tuple[str, str], tuple[float, float]] = {}
    for tl in all_true_lines:
        key = (tl["game_id"], tl.get("market_type", ""))
        if key not in true_line_map:
            true_line_map[key] = (
                float(tl.get("true_home_prob", 0)),
                float(tl.get("true_away_prob", 0)),
            )

    # Build game team lookup from the already-fetched records.
    game_teams: dict[str, tuple[str, str]] = {}
    for rec in to_process:
        game = rec.get("games", {})
        if game:
            game_teams[rec["game_id"]] = (
                (game.get("home_team", "") or "").lower(),
                (game.get("away_team", "") or "").lower(),
            )

    # Process each record using cached data (zero DB calls).
    closed_updates: list[dict] = []
    processed = 0
    now_iso = now.isoformat()

    for rec in to_process:
        gid = rec["game_id"]
        mkt = rec["market_type"]
        side = rec["side"]
        book = rec["sportsbook"]

        closing_odds = closing_odds_map.get((gid, book, mkt, side))
        if closing_odds is None:
            continue

        bet_implied = american_to_implied_prob(int(rec["bet_odds"]))
        closing_implied = american_to_implied_prob(int(closing_odds))
        clv = calculate_clv(bet_implied, closing_implied)

        # Devigged CLV from true lines.
        devigged_clv = None
        true_probs = true_line_map.get((gid, mkt))
        if true_probs:
            home_prob, away_prob = true_probs
            if home_prob or away_prob:
                side_lower = side.lower().strip()
                home_team, away_team = game_teams.get(gid, ("", ""))
                closing_true_prob = None
                if home_team and home_team in side_lower:
                    closing_true_prob = home_prob
                elif away_team and away_team in side_lower:
                    closing_true_prob = away_prob
                elif "over" in side_lower:
                    closing_true_prob = home_prob
                elif "under" in side_lower:
                    closing_true_prob = away_prob
                if closing_true_prob is not None and closing_true_prob > 0:
                    devigged_clv = round(
                        calculate_clv(bet_implied, closing_true_prob), 2
                    )

        update_row: dict = {
            "id": rec["id"],
            "closing_odds": closing_odds,
            "closing_true_prob": round(closing_implied, 6),
            "clv_percentage": round(clv, 2),
            "closing_timestamp": now_iso,
            "status": "closed",
        }
        if devigged_clv is not None:
            update_row["devigged_clv"] = devigged_clv
        else:
            update_row["devigged_clv"] = None

        closed_updates.append(update_row)
        processed += 1

    # Batch-PATCH closed CLV records grouped by update payload shape.
    # id is GENERATED ALWAYS so we can't upsert; use _patch_by_ids in bulk.
    if closed_updates:
        # Group by the set of non-id fields so identical payloads batch together.
        # Most records share the same structure, so this collapses N calls to ~1-2.
        from collections import defaultdict
        groups: dict[tuple, list] = defaultdict(list)
        for row in closed_updates:
            rec_id = row.pop("id")
            # Use frozenset of items as grouping key (all values are hashable).
            key = tuple(sorted(row.items()))
            groups[key].append(rec_id)

        failed = 0
        for payload_key, ids in groups.items():
            data = dict(payload_key)
            try:
                db._patch_by_ids("clv_records", "id", ids, data)
            except Exception:
                failed += len(ids)
        if failed:
            print(f"  Warning: {failed}/{len(closed_updates)} CLV patches failed.")

    return processed, len(expired_ids)


def create_clv_from_ev_opportunities(client: object) -> int:
    """Create CLV records from current EV opportunities.

    Called after each scan to seed CLV tracking for new opportunities.
    Only creates records for opportunities that don't already have one.
    """
    from db import SupabaseClient

    db: SupabaseClient = client  # type: ignore[assignment]

    # Get latest EV opportunities.
    from db import get_latest_ev_opportunities
    ev_opps = get_latest_ev_opportunities(db)
    if not ev_opps:
        return 0

    # Get existing open CLV records to avoid duplicates.
    existing = db._get(
        "clv_records",
        select="game_id,sportsbook,market_type,side",
        filters={"status": "eq.open"},
    )
    existing_keys = {
        (r["game_id"], r["sportsbook"], r["market_type"], r["side"])
        for r in existing
    }

    rows: list[dict] = []
    now_ts = datetime.now(timezone.utc).isoformat()

    for opp in ev_opps:
        game_info = opp.get("games", {})
        sport = game_info.get("sport", "") if game_info else ""

        key = (opp["game_id"], opp["sportsbook"], opp["market_type"], opp["side"])
        if key in existing_keys:
            continue

        rows.append({
            "game_id": opp["game_id"],
            "sport": sport,
            "sportsbook": opp["sportsbook"],
            "market_type": opp["market_type"],
            "side": opp["side"],
            "bet_odds": float(opp["book_odds"]),
            "bet_true_prob": float(opp["true_prob"]),
            "ev_at_bet": float(opp["ev_percentage"]),
            "bet_timestamp": opp.get("timestamp", now_ts),
            "status": "open",
        })

    if rows:
        bulk_create_clv_records(db, rows)

    return len(rows)


# ---------------------------------------------------------------------------
# Console output
# ---------------------------------------------------------------------------

def print_clv_stats(summary: dict) -> None:
    """Print CLV summary to console."""
    print(f"\n{'=' * 70}")
    print(f"  CLV Summary  |  Last {summary['days']} days")
    print(f"{'=' * 70}")

    if summary["total_records"] == 0:
        print("\n  No closed CLV records yet. Run more scans and wait for games to start.\n")
        return

    print(f"\n  Total records:    {summary['total_records']}")
    print(f"  Average CLV:      {summary['avg_clv']:+.2f}%")
    print(f"  Positive CLV:     {summary['positive_clv_pct']:.1f}%")
    print(f"  Average EV@Bet:   {summary['avg_ev_at_bet']:+.2f}%")

    if summary["by_sport"]:
        print(f"\n  {'Sport':<20} {'Count':>8} {'Avg CLV':>10} {'+ CLV%':>10}")
        print(f"  {'-' * 50}")
        for sport, stats in sorted(summary["by_sport"].items()):
            print(
                f"  {sport:<20} {stats['count']:>8} "
                f"{stats['avg_clv']:>+9.2f}% {stats['positive_pct']:>9.1f}%"
            )
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    """Process CLV records and optionally show stats."""
    dotenv_path = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
    load_dotenv(dotenv_path)

    args = sys.argv[1:]
    show_stats = "--stats" in args

    from db import get_supabase

    db = get_supabase()

    if show_stats:
        summary = get_clv_summary(db)
        print_clv_stats(summary)
        return

    # Process open records.
    print("Processing open CLV records...")
    processed, expired = process_open_records(db)
    print(f"  Processed: {processed}, Expired: {expired}")

    # Show current stats.
    summary = get_clv_summary(db)
    print_clv_stats(summary)


if __name__ == "__main__":
    main()
