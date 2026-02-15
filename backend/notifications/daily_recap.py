"""Daily recap generator — builds a performance summary for a given day.

Aggregates graded bet results, CLV data, and steam alerts into a recap dict
that can be sent to Discord or served via the API.
"""

from datetime import date, datetime, timedelta, timezone

from db import SupabaseClient, get_supabase
from notifications.discord import send_daily_recap


def generate_recap(
    client: SupabaseClient | None = None,
    target_date: date | None = None,
) -> dict:
    """Build a daily recap dict for the given date (defaults to yesterday).

    Returns a dict with: date, record, units, roi, total_bets, best_bet,
    worst_bet, steam_alerts, avg_clv, by_sport, alltime_record, alltime_roi,
    results (list of individual graded bets).
    """
    db = client or get_supabase()
    if target_date is None:
        target_date = (datetime.now(timezone.utc) - timedelta(days=1)).date()

    date_str = target_date.isoformat()
    next_day = (target_date + timedelta(days=1)).isoformat()

    # --- Graded results for the target date ---
    day_results = db._get(
        "bet_results",
        select="*,ev_opportunities(id,game_id,sportsbook,market_type,side,book_odds,ev_percentage,kelly_fraction,timestamp,games(game_id,sport,home_team,away_team,start_time,home_score,away_score))",
        filters={
            "graded_at": f"gte.{date_str}",
        },
        order="graded_at.asc",
    )
    # Client-side filter for upper bound on date.
    day_results = [r for r in day_results if r.get("graded_at", "") < next_day]

    wins = sum(1 for r in day_results if r["result"] == "win")
    losses = sum(1 for r in day_results if r["result"] == "loss")
    pushes = sum(1 for r in day_results if r["result"] == "push")
    total = len(day_results)
    units = sum(float(r.get("profit_loss", 0)) for r in day_results)
    decided = wins + losses

    # Best / worst bet.
    best_bet = "—"
    worst_bet = "—"
    if day_results:
        sorted_by_pnl = sorted(day_results, key=lambda r: float(r.get("profit_loss", 0)))
        best = sorted_by_pnl[-1]
        worst = sorted_by_pnl[0]
        best_opp = best.get("ev_opportunities", {}) or {}
        worst_opp = worst.get("ev_opportunities", {}) or {}
        best_bet = f"{best_opp.get('side', '?')} ({float(best.get('profit_loss', 0)):+.2f}u)"
        worst_bet = f"{worst_opp.get('side', '?')} ({float(worst.get('profit_loss', 0)):+.2f}u)"

    # By sport breakdown.
    by_sport: dict[str, dict] = {}
    flat_results = []
    for r in day_results:
        opp = r.get("ev_opportunities", {}) or {}
        game = opp.get("games", {}) or {}
        sport = game.get("sport", "unknown")

        if sport not in by_sport:
            by_sport[sport] = {"wins": 0, "losses": 0, "pushes": 0, "units": 0.0}
        s = by_sport[sport]
        if r["result"] == "win":
            s["wins"] += 1
        elif r["result"] == "loss":
            s["losses"] += 1
        else:
            s["pushes"] += 1
        s["units"] += float(r.get("profit_loss", 0))

        # Flatten for the API.
        flat_results.append({
            "id": r.get("id"),
            "result": r.get("result"),
            "pnl": float(r.get("profit_loss", 0)),
            "date": r.get("graded_at"),
            "sport": sport,
            "sportsbook": opp.get("sportsbook", ""),
            "game": f"{game.get('away_team', '')} @ {game.get('home_team', '')}",
            "pick": opp.get("side", ""),
            "odds": opp.get("book_odds"),
            "ev_pct": opp.get("ev_percentage"),
        })

    sport_breakdown = {}
    for sport_key, s in sorted(by_sport.items()):
        sport_breakdown[sport_key] = {
            "record": f"{s['wins']}-{s['losses']}" + (f"-{s['pushes']}" if s["pushes"] else ""),
            "units": round(s["units"], 2),
        }

    # --- Steam alerts count for the day ---
    steam_count = 0
    try:
        steam_rows = db._get(
            "steam_moves",
            select="id",
            filters={"detected_at": f"gte.{date_str}"},
        )
        steam_rows = [r for r in steam_rows if r.get("detected_at", "") < next_day]
        steam_count = len(steam_rows)
    except Exception:
        pass

    # --- All-time stats ---
    all_results = db._get("bet_results", select="result,profit_loss")
    all_wins = sum(1 for r in all_results if r["result"] == "win")
    all_losses = sum(1 for r in all_results if r["result"] == "loss")
    all_pushes = sum(1 for r in all_results if r["result"] == "push")
    all_total = len(all_results)
    all_units = sum(float(r.get("profit_loss", 0)) for r in all_results)

    # --- Average CLV for the day ---
    avg_clv = 0.0
    try:
        clv_rows = db._get(
            "clv_records",
            select="clv_percentage",
            filters={"recorded_at": f"gte.{date_str}"},
        )
        clv_rows = [r for r in clv_rows if r.get("recorded_at", "") < next_day]
        if clv_rows:
            avg_clv = sum(float(r.get("clv_percentage", 0)) for r in clv_rows) / len(clv_rows)
    except Exception:
        pass

    # --- RTM Signal stats for the day ---
    signal_stats = {"fired": 0, "graded": 0, "record": "—", "units": 0.0}
    try:
        day_signals = db._get(
            "rtm_signals",
            select="star_rating,result,profit_loss,signal_strength,created_at",
            filters={"created_at": f"gte.{date_str}"},
        )
        day_signals = [s for s in day_signals if s.get("created_at", "") < next_day]
        signal_stats["fired"] = len(day_signals)
        graded_sigs = [s for s in day_signals if s.get("result") in ("win", "loss", "push")]
        if graded_sigs:
            sig_wins = sum(1 for s in graded_sigs if s["result"] == "win")
            sig_losses = sum(1 for s in graded_sigs if s["result"] == "loss")
            sig_pushes = sum(1 for s in graded_sigs if s["result"] == "push")
            sig_units = sum(float(s.get("profit_loss", 0)) for s in graded_sigs)
            signal_stats["graded"] = len(graded_sigs)
            signal_stats["record"] = f"{sig_wins}-{sig_losses}" + (f"-{sig_pushes}" if sig_pushes else "")
            signal_stats["units"] = round(sig_units, 2)
    except Exception:
        pass

    return {
        "date": date_str,
        "record": f"{wins}-{losses}" + (f"-{pushes}" if pushes else ""),
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "total_bets": total,
        "units": round(units, 2),
        "roi": round(units / total * 100, 1) if total else 0,
        "best_bet": best_bet,
        "worst_bet": worst_bet,
        "steam_alerts": steam_count,
        "avg_clv": round(avg_clv, 2),
        "by_sport": sport_breakdown,
        "alltime_record": f"{all_wins}-{all_losses}" + (f"-{all_pushes}" if all_pushes else ""),
        "alltime_units": round(all_units, 2),
        "alltime_roi": round(all_units / all_total * 100, 1) if all_total else 0,
        "signal_stats": signal_stats,
        "results": flat_results,
    }


def generate_and_send_recap(
    client: SupabaseClient | None = None,
    target_date: date | None = None,
) -> dict:
    """Generate daily recap and send to Discord."""
    recap = generate_recap(client, target_date)
    if recap["total_bets"] > 0:
        send_daily_recap(recap)
    return recap
