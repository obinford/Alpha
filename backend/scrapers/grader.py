"""Auto-grading for +EV opportunities.

Grades open EV opportunities as WIN/LOSS/PUSH once their game is final.
Calculates profit/loss and inserts into bet_results table.
"""

import os
import sys
import re
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "shared"))


def _parse_spread(side: str) -> tuple[str, float] | None:
    """Parse team name and spread from a side string like 'Team Name -3.5'."""
    match = re.match(r"^(.+?)\s+([+-]?\d+\.?\d*)$", side.strip())
    if match:
        return match.group(1).strip(), float(match.group(2))
    return None


def _parse_total(side: str) -> tuple[str, float] | None:
    """Parse Over/Under and total from side string like 'Over 220.5'."""
    match = re.match(r"^(Over|Under)\s+(\d+\.?\d*)$", side.strip())
    if match:
        return match.group(1), float(match.group(2))
    return None


def _calculate_profit(result: str, book_odds: int) -> float:
    """Calculate profit/loss in units for a graded bet.

    WIN with positive odds (+200): profit = odds/100
    WIN with negative odds (-150): profit = 100/abs(odds)
    LOSS: -1.0
    PUSH: 0.0
    """
    if result == "push":
        return 0.0
    if result == "loss":
        return -1.0
    # WIN
    if book_odds > 0:
        return book_odds / 100.0
    return 100.0 / abs(book_odds)


def grade_opportunity(opp: dict, game: dict) -> str | None:
    """Grade a single opportunity against game results.

    Returns 'win', 'loss', 'push', or None if can't be graded.
    """
    market = opp.get("market_type", "")
    side = opp.get("side", "")
    home_score = game.get("home_score")
    away_score = game.get("away_score")
    home_team = game.get("home_team", "")
    away_team = game.get("away_team", "")

    if home_score is None or away_score is None:
        return None

    home_score = int(home_score)
    away_score = int(away_score)

    # --- Player props: can't grade without player stats ---
    if market.startswith("player_"):
        return None

    # --- Moneyline (h2h) ---
    if market == "h2h":
        # side is the team name
        team = side.strip()
        if team == home_team:
            if home_score > away_score:
                return "win"
            elif home_score < away_score:
                return "loss"
            else:
                return "push"
        elif team == away_team:
            if away_score > home_score:
                return "win"
            elif away_score < home_score:
                return "loss"
            else:
                return "push"
        return None

    # --- Spreads ---
    if market == "spreads":
        parsed = _parse_spread(side)
        if not parsed:
            return None
        team, spread = parsed

        if team == home_team:
            adjusted = home_score + spread
            if adjusted > away_score:
                return "win"
            elif adjusted < away_score:
                return "loss"
            else:
                return "push"
        elif team == away_team:
            adjusted = away_score + spread
            if adjusted > home_score:
                return "win"
            elif adjusted < home_score:
                return "loss"
            else:
                return "push"
        return None

    # --- Totals ---
    if market == "totals":
        parsed = _parse_total(side)
        if not parsed:
            return None
        direction, total_line = parsed
        actual_total = home_score + away_score

        if direction == "Over":
            if actual_total > total_line:
                return "win"
            elif actual_total < total_line:
                return "loss"
            else:
                return "push"
        else:  # Under
            if actual_total < total_line:
                return "win"
            elif actual_total > total_line:
                return "loss"
            else:
                return "push"

    return None


def grade_opportunities(db_client: object) -> dict:
    """Grade all ungraded EV opportunities where the game is final.

    Returns a summary dict with counts and stats.
    """
    from db import SupabaseClient
    import httpx as _httpx

    client: SupabaseClient = db_client  # type: ignore[assignment]

    # Find open EV opportunities for games that are final.
    open_opps = client._get(
        "ev_opportunities",
        select="*,games(game_id,sport,home_team,away_team,home_score,away_score,status)",
        filters={"status": "eq.open"},
    )

    if not open_opps:
        return {"graded": 0, "wins": 0, "losses": 0, "pushes": 0, "skipped": 0, "units": 0.0}

    # Check which ones already have bet_results.
    graded_ids = set()
    try:
        existing = client._get(
            "bet_results",
            select="ev_opportunity_id",
        )
        graded_ids = {r["ev_opportunity_id"] for r in existing}
    except Exception:
        pass

    wins = 0
    losses = 0
    pushes = 0
    skipped = 0
    total_units = 0.0
    graded_count = 0

    for opp in open_opps:
        opp_id = opp.get("id")
        if opp_id in graded_ids:
            continue

        game = opp.get("games", {})
        if not game or game.get("status") != "final":
            continue

        result = grade_opportunity(opp, game)
        if result is None:
            skipped += 1
            continue

        book_odds = int(opp.get("book_odds", 0))
        profit = _calculate_profit(result, book_odds)
        total_units += profit

        if result == "win":
            wins += 1
        elif result == "loss":
            losses += 1
        else:
            pushes += 1

        # Insert bet_result.
        try:
            client._post("bet_results", {
                "ev_opportunity_id": opp_id,
                "result": result,
                "profit_loss": round(profit, 4),
                "graded_at": datetime.now(timezone.utc).isoformat(),
            })
            graded_count += 1
        except Exception as e:
            print(f"  Warning: Failed to insert bet_result for opp {opp_id}: {e}")
            continue

        # Update EV opportunity status.
        try:
            resp = _httpx.patch(
                f"{client.base_url}/ev_opportunities",
                headers={**client.headers, "Prefer": "return=minimal"},
                params={"id": f"eq.{opp_id}"},
                json={"status": "graded"},
                timeout=10,
            )
            resp.raise_for_status()
        except Exception:
            pass

    summary = {
        "graded": graded_count,
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "skipped": skipped,
        "units": round(total_units, 2),
    }

    if graded_count > 0:
        total_decided = wins + losses
        win_rate = (wins / total_decided * 100) if total_decided else 0
        print(
            f"  Graded {graded_count} bets: {wins}-{losses}"
            f"{f'-{pushes}' if pushes else ''} "
            f"| {total_units:+.2f} units | Win rate: {win_rate:.0f}%"
        )

    return summary
