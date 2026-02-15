"""Auto-grading for RTM Signals.

Grades active signals as WIN/LOSS/PUSH once their game is final.
Reuses the grading logic from scrapers.grader for game-line signals.
For player props, marks as 'ungraded' (requires manual stat data).
"""

import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scrapers.grader import grade_opportunity, _calculate_profit


def grade_signals(db_client) -> dict:
    """Grade all active RTM signals where the game is final.

    Returns a summary dict with counts and stats.
    """
    # Use db_client._http to bypass egress proxy.

    # Fetch active signals.
    active_signals = db_client._get(
        "rtm_signals",
        select="*",
        filters={"status": "eq.active"},
    )

    if not active_signals:
        return {
            "graded": 0, "wins": 0, "losses": 0, "pushes": 0,
            "skipped": 0, "units": 0.0,
        }

    # Fetch final games.
    game_ids = list({s["game_id"] for s in active_signals})

    # Get game results for all relevant game IDs.
    game_results: dict[str, dict] = {}
    for gid in game_ids:
        try:
            games = db_client._get(
                "games",
                select="game_id,sport,home_team,away_team,home_score,away_score,status",
                filters={"game_id": f"eq.{gid}"},
                limit=1,
            )
            if games and games[0].get("status") == "final":
                game_results[gid] = games[0]
        except Exception:
            continue

    wins = 0
    losses = 0
    pushes = 0
    skipped = 0
    total_units = 0.0
    graded_count = 0

    for signal in active_signals:
        game_id = signal["game_id"]
        game = game_results.get(game_id)
        if not game:
            continue

        market_type = signal.get("market_type", "")
        side = signal.get("side", "")
        book_odds = int(signal.get("book_odds", 0))

        # Player props can't be graded without player stats.
        if market_type.startswith("player_"):
            skipped += 1
            continue

        # Use the existing grading logic.
        opp_dict = {"market_type": market_type, "side": side}
        result = grade_opportunity(opp_dict, game)

        if result is None:
            skipped += 1
            continue

        # Use kelly-based units from signal, fall back to 1.0.
        # kelly_size is stored as kelly_fraction * 100 (same scale as recommended_units).
        kelly_size = signal.get("kelly_size")
        if kelly_size is not None and float(kelly_size) > 0:
            units = max(0.1, min(float(kelly_size), 5.0))
        else:
            units = 1.0
        profit = _calculate_profit(result, book_odds, units)
        total_units += profit

        if result == "win":
            wins += 1
        elif result == "loss":
            losses += 1
        else:
            pushes += 1

        # Update signal in database.
        try:
            signal_id = signal["id"]
            resp = db_client._http.patch(
                f"{db_client.base_url}/rtm_signals",
                headers={**db_client.headers, "Prefer": "return=minimal"},
                params={"id": f"eq.{signal_id}"},
                json={
                    "status": "graded",
                    "result": result,
                    "profit_loss": round(profit, 4),
                    "graded_at": datetime.now(timezone.utc).isoformat(),
                },
                timeout=10,
            )
            resp.raise_for_status()
            graded_count += 1
        except Exception as e:
            print(f"  Warning: Failed to grade signal {signal.get('id')}: {e}")
            continue

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
            f"  Signal grading: {graded_count} graded: {wins}-{losses}"
            f"{f'-{pushes}' if pushes else ''} "
            f"| {total_units:+.2f} units | Win rate: {win_rate:.0f}%"
        )

    return summary


def get_signal_performance(db_client, days: int = 30) -> dict:
    """Calculate comprehensive signal performance stats.

    Returns detailed breakdown by star tier, sport, and time period.
    """
    from datetime import timedelta

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    all_signals = db_client._get(
        "rtm_signals",
        select="*",
        filters={"created_at": f"gte.{cutoff}"},
        order="created_at.desc",
    )

    graded = [s for s in all_signals if s.get("result") in ("win", "loss", "push")]
    total = len(graded)
    wins = sum(1 for s in graded if s["result"] == "win")
    losses = sum(1 for s in graded if s["result"] == "loss")
    pushes = sum(1 for s in graded if s["result"] == "push")
    units = sum(float(s.get("profit_loss", 0)) for s in graded)
    decided = wins + losses

    # Streak tracking.
    current_streak = 0
    streak_type = None
    for s in sorted(graded, key=lambda x: x.get("graded_at", ""), reverse=True):
        r = s["result"]
        if r == "push":
            continue
        if streak_type is None:
            streak_type = r
            current_streak = 1
        elif r == streak_type:
            current_streak += 1
        else:
            break

    # By star tier.
    by_tier: dict[int, dict] = {}
    for s in graded:
        tier = int(s.get("star_rating", 3))
        if tier not in by_tier:
            by_tier[tier] = {"wins": 0, "losses": 0, "pushes": 0, "units": 0.0, "signals": 0}
        t = by_tier[tier]
        t["signals"] += 1
        if s["result"] == "win":
            t["wins"] += 1
        elif s["result"] == "loss":
            t["losses"] += 1
        else:
            t["pushes"] += 1
        t["units"] += float(s.get("profit_loss", 0))

    tier_breakdown = {}
    for tier, t in sorted(by_tier.items(), reverse=True):
        d = t["wins"] + t["losses"]
        total_t = d + t["pushes"]
        tier_breakdown[f"{tier}_star"] = {
            "record": f"{t['wins']}-{t['losses']}" + (f"-{t['pushes']}" if t["pushes"] else ""),
            "win_rate": round(t["wins"] / d * 100, 1) if d else 0,
            "units": round(t["units"], 2),
            "roi": round(t["units"] / total_t * 100, 1) if total_t else 0,
            "total": total_t,
        }

    # By sport.
    by_sport: dict[str, dict] = {}
    for s in graded:
        sp = s.get("sport", "unknown")
        if sp not in by_sport:
            by_sport[sp] = {"wins": 0, "losses": 0, "pushes": 0, "units": 0.0}
        b = by_sport[sp]
        if s["result"] == "win":
            b["wins"] += 1
        elif s["result"] == "loss":
            b["losses"] += 1
        else:
            b["pushes"] += 1
        b["units"] += float(s.get("profit_loss", 0))

    sport_breakdown = {}
    for sp, b in sorted(by_sport.items()):
        d = b["wins"] + b["losses"]
        sport_breakdown[sp] = {
            "record": f"{b['wins']}-{b['losses']}" + (f"-{b['pushes']}" if b["pushes"] else ""),
            "win_rate": round(b["wins"] / d * 100, 1) if d else 0,
            "units": round(b["units"], 2),
        }

    # Average signal strength of winners vs losers.
    winner_strengths = [float(s.get("signal_strength", 0)) for s in graded if s["result"] == "win"]
    loser_strengths = [float(s.get("signal_strength", 0)) for s in graded if s["result"] == "loss"]

    # Component score averages for winners vs losers.
    def avg_component(signals, key):
        vals = [float(s.get(key, 0)) for s in signals]
        return round(sum(vals) / len(vals), 1) if vals else 0

    winners = [s for s in graded if s["result"] == "win"]
    losers = [s for s in graded if s["result"] == "loss"]

    return {
        "period_days": days,
        "total_signals": len(all_signals),
        "graded_signals": total,
        "pending_signals": len(all_signals) - total,
        "record": f"{wins}-{losses}" + (f"-{pushes}" if pushes else ""),
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "win_rate": round(wins / decided * 100, 1) if decided else 0,
        "total_units": round(units, 2),
        "roi": round(units / total * 100, 1) if total else 0,
        "avg_winner_strength": round(sum(winner_strengths) / len(winner_strengths), 1) if winner_strengths else 0,
        "avg_loser_strength": round(sum(loser_strengths) / len(loser_strengths), 1) if loser_strengths else 0,
        "current_streak": f"{current_streak} {'W' if streak_type == 'win' else 'L'}" if streak_type else "—",
        "winner_avg_ev": avg_component(winners, "ev_score"),
        "loser_avg_ev": avg_component(losers, "ev_score"),
        "winner_avg_steam": avg_component(winners, "steam_score"),
        "loser_avg_steam": avg_component(losers, "steam_score"),
        "by_tier": tier_breakdown,
        "by_sport": sport_breakdown,
    }
