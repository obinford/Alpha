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
        select="clv_percentage,ev_at_bet,sport",
        filters={
            "status": "eq.closed",
            "created_at": f"gte.{since}",
        },
    )

    if not closed:
        return {
            "total_records": 0,
            "avg_clv": 0,
            "positive_clv_pct": 0,
            "avg_ev_at_bet": 0,
            "by_sport": {},
            "days": days,
        }

    clvs = [float(r["clv_percentage"]) for r in closed if r.get("clv_percentage") is not None]
    evs = [float(r["ev_at_bet"]) for r in closed]

    # By sport.
    by_sport: dict[str, list[float]] = {}
    for r in closed:
        sport = r.get("sport", "unknown")
        clv = r.get("clv_percentage")
        if clv is not None:
            by_sport.setdefault(sport, []).append(float(clv))

    sport_stats = {}
    for sport, sport_clvs in by_sport.items():
        sport_stats[sport] = {
            "count": len(sport_clvs),
            "avg_clv": round(sum(sport_clvs) / len(sport_clvs), 2) if sport_clvs else 0,
            "positive_pct": round(
                sum(1 for c in sport_clvs if c > 0) / len(sport_clvs) * 100, 1
            ) if sport_clvs else 0,
        }

    positive_count = sum(1 for c in clvs if c > 0)
    return {
        "total_records": len(closed),
        "avg_clv": round(sum(clvs) / len(clvs), 2) if clvs else 0,
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
    """Get the closing true probability from the sharp book.

    Looks at the most recent true_lines entry for the game/market.
    """
    from db import SupabaseClient

    db: SupabaseClient = client  # type: ignore[assignment]

    rows = db._get(
        "true_lines",
        select="true_home_prob,true_away_prob,timestamp",
        filters={
            "game_id": f"eq.{game_id}",
            "market_type": f"eq.{market_type}",
        },
        order="timestamp.desc",
        limit=1,
    )

    if not rows:
        return None

    # Determine which side the record tracks.
    # Side could be a team name, Over/Under, or a player prop.
    # For h2h/spreads: assume home = true_home_prob, else away.
    # This is a simplification; ideally we'd match side to home/away team.
    # For now, use home_prob for the first outcome and away for the second.
    return None  # Needs game context to map side -> prob


# ---------------------------------------------------------------------------
# CLV processing
# ---------------------------------------------------------------------------

def process_open_records(client: object) -> tuple[int, int]:
    """Process all open CLV records.

    For games that have started, capture closing odds and compute CLV.
    Returns (processed_count, expired_count).
    """
    records = get_open_clv_records(client)
    if not records:
        return 0, 0

    now = datetime.now(timezone.utc)
    processed = 0
    expired = 0

    from db import SupabaseClient

    db: SupabaseClient = client  # type: ignore[assignment]

    for rec in records:
        game = rec.get("games", {})
        if not game:
            continue

        start_str = game.get("start_time", "")
        if not start_str:
            continue

        game_start = datetime.fromisoformat(start_str.replace("Z", "+00:00"))

        # Only process games that have started.
        if game_start > now:
            continue

        # If game started more than CLV_EXPIRATION_HOURS ago, expire.
        from config import CLV_EXPIRATION_HOURS
        if (now - game_start).total_seconds() > CLV_EXPIRATION_HOURS * 3600:
            try:
                resp = db._http.patch(
                    f"{db.base_url}/clv_records",
                    headers={**db.headers, "Prefer": "return=minimal"},
                    params={"id": f"eq.{rec['id']}"},
                    json={"status": "expired"},
                    timeout=10,
                )
                resp.raise_for_status()
                expired += 1
            except Exception:
                pass
            continue

        # Try to find closing odds.
        closing_odds = get_closing_odds_from_snapshots(
            client,
            rec["game_id"],
            rec["market_type"],
            rec["side"],
            rec["sportsbook"],
        )

        if closing_odds is None:
            continue

        # Calculate CLV.
        bet_implied = american_to_implied_prob(int(rec["bet_odds"]))
        closing_implied = american_to_implied_prob(int(closing_odds))
        clv = calculate_clv(bet_implied, closing_implied)

        # Update the record.
        update_data = {
            "closing_odds": closing_odds,
            "closing_true_prob": round(closing_implied, 6),
            "clv_percentage": round(clv, 2),
            "closing_timestamp": now.isoformat(),
            "status": "closed",
        }

        try:
            resp = db._http.patch(
                f"{db.base_url}/clv_records",
                headers={**db.headers, "Prefer": "return=minimal"},
                params={"id": f"eq.{rec['id']}"},
                json=update_data,
                timeout=10,
            )
            resp.raise_for_status()
            processed += 1
        except Exception as e:
            print(f"  Warning: Failed to update CLV record {rec['id']}: {e}")

    return processed, expired


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
