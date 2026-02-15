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


def _calculate_profit(result: str, book_odds: int, units: float = 1.0) -> float:
    """Calculate profit/loss using kelly-based unit sizing.

    Args:
        result: 'win', 'loss', or 'push'.
        book_odds: American odds (e.g. +200, -150).
        units: Recommended units to wager (from kelly sizing).

    WIN: profit = units * (odds payout ratio)
        +200 odds at 0.5 units → 0.5 * 2.0 = +1.0 units
        -150 odds at 0.5 units → 0.5 * 0.667 = +0.333 units
    LOSS: profit = -units
    PUSH: profit = 0.0
    """
    if result == "push":
        return 0.0
    if result == "loss":
        return -units
    # WIN
    if book_odds > 0:
        return units * (book_odds / 100.0)
    return units * (100.0 / abs(book_odds))


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

    Only grades opportunities with EV% >= MIN_GRADE_EV_THRESHOLD (default 3%).
    Uses kelly-based recommended_units for profit/loss sizing.

    Returns a summary dict with counts and stats.
    """
    from db import SupabaseClient
    from shared.config import MIN_GRADE_EV_THRESHOLD, MIN_UNIT_SIZE, MAX_UNIT_SIZE

    client: SupabaseClient = db_client  # type: ignore[assignment]

    # Find open EV opportunities for games that are final.
    open_opps = client._get(
        "ev_opportunities",
        select="*,games(game_id,sport,home_team,away_team,home_score,away_score,status)",
        filters={"status": "eq.open"},
    )

    if not open_opps:
        return {"graded": 0, "wins": 0, "losses": 0, "pushes": 0, "skipped": 0, "below_threshold": 0, "units": 0.0}

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
    below_threshold = 0
    total_units = 0.0
    graded_count = 0

    for opp in open_opps:
        opp_id = opp.get("id")
        if opp_id in graded_ids:
            continue

        game = opp.get("games", {})
        if not game or game.get("status") != "final":
            continue

        # Skip opportunities below the minimum EV threshold.
        ev_pct = float(opp.get("ev_percentage", 0) or 0)
        if ev_pct < MIN_GRADE_EV_THRESHOLD:
            below_threshold += 1
            # Still mark as graded so we don't keep re-checking.
            try:
                resp = client._http.patch(
                    f"{client.base_url}/ev_opportunities",
                    headers={**client.headers, "Prefer": "return=minimal"},
                    params={"id": f"eq.{opp_id}"},
                    json={"status": "graded"},
                    timeout=10,
                )
                resp.raise_for_status()
            except Exception:
                pass
            continue

        result = grade_opportunity(opp, game)
        if result is None:
            skipped += 1
            continue

        book_odds = int(opp.get("book_odds", 0))
        # Use kelly-based sizing: recommended_units or fall back to kelly_fraction.
        rec_units = opp.get("recommended_units")
        if rec_units is not None:
            units = float(rec_units)
        else:
            kelly = opp.get("kelly_fraction")
            if kelly is not None:
                units = float(kelly) * 100  # kelly_fraction is 0.005 → 0.5 units
            else:
                units = 1.0  # fallback

        # Clamp to reasonable range.
        units = max(MIN_UNIT_SIZE, min(units, MAX_UNIT_SIZE))

        profit = _calculate_profit(result, book_odds, units)
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
            resp = client._http.patch(
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
        "below_threshold": below_threshold,
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
    if below_threshold > 0:
        print(f"  Skipped {below_threshold} opportunities below {MIN_GRADE_EV_THRESHOLD}% EV threshold")

    return summary


def recalculate_all_results(db_client: object) -> dict:
    """Recalculate profit/loss for ALL existing bet_results using kelly-based sizing.

    This fixes historical results that were calculated with flat 1-unit sizing.
    """
    from db import SupabaseClient
    from shared.config import MIN_GRADE_EV_THRESHOLD, MIN_UNIT_SIZE, MAX_UNIT_SIZE

    client: SupabaseClient = db_client  # type: ignore[assignment]

    # Fetch all bet_results with their ev_opportunity data.
    all_results = client._get(
        "bet_results",
        select="*,ev_opportunities(id,book_odds,ev_percentage,kelly_fraction,recommended_units)",
    )

    if not all_results:
        return {"updated": 0, "removed": 0, "message": "No existing bet_results found"}

    updated = 0
    removed = 0

    for r in all_results:
        result_id = r.get("id")
        result = r.get("result")
        opp = r.get("ev_opportunities", {}) or {}

        if not result or not result_id:
            continue

        ev_pct = float(opp.get("ev_percentage", 0) or 0)

        # Remove results below EV threshold.
        if ev_pct < MIN_GRADE_EV_THRESHOLD:
            try:
                resp = client._http.request(
                    "DELETE",
                    f"{client.base_url}/bet_results",
                    headers={**client.headers, "Prefer": "return=minimal"},
                    params={"id": f"eq.{result_id}"},
                    timeout=10,
                )
                resp.raise_for_status()
                removed += 1
            except Exception as e:
                print(f"  Warning: Failed to delete bet_result {result_id}: {e}")
            continue

        book_odds = int(opp.get("book_odds", 0))

        # Determine kelly-based units.
        rec_units = opp.get("recommended_units")
        if rec_units is not None:
            units = float(rec_units)
        else:
            kelly = opp.get("kelly_fraction")
            if kelly is not None:
                units = float(kelly) * 100
            else:
                units = 1.0

        units = max(MIN_UNIT_SIZE, min(units, MAX_UNIT_SIZE))

        new_profit = _calculate_profit(result, book_odds, units)
        old_profit = float(r.get("profit_loss", 0))

        # Only update if the value changed.
        if abs(new_profit - old_profit) < 0.001:
            continue

        try:
            resp = client._http.patch(
                f"{client.base_url}/bet_results",
                headers={**client.headers, "Prefer": "return=minimal"},
                params={"id": f"eq.{result_id}"},
                json={"profit_loss": round(new_profit, 4)},
                timeout=10,
            )
            resp.raise_for_status()
            updated += 1
        except Exception as e:
            print(f"  Warning: Failed to update bet_result {result_id}: {e}")

    print(f"  Recalculated {updated} bet_results, removed {removed} below {MIN_GRADE_EV_THRESHOLD}% EV")
    return {
        "updated": updated,
        "removed": removed,
        "message": f"Recalculated {updated} results with kelly sizing, removed {removed} below {MIN_GRADE_EV_THRESHOLD}% EV",
    }
