"""RTM Signal API — active signals, history, and performance."""

import json
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query

from db import get_supabase

router = APIRouter()

# Signals only target -160 to +200 odds.  Filter old out-of-range rows.
_SIGNAL_MIN_ODDS = -160
_SIGNAL_MAX_ODDS = 200


def _normalize_signal(row: dict) -> dict:
    """Map DB column names to frontend field names."""
    # DB stores kelly_size, frontend reads kelly_fraction.
    if "kelly_size" in row and "kelly_fraction" not in row:
        row["kelly_fraction"] = row.pop("kelly_size")
    return row


def _filter_odds_range(rows: list[dict]) -> list[dict]:
    """Keep only signals within the -160 to +200 odds window."""
    out = []
    for r in rows:
        try:
            odds = int(r.get("book_odds", 0))
        except (ValueError, TypeError):
            continue
        if _SIGNAL_MIN_ODDS <= odds <= _SIGNAL_MAX_ODDS:
            out.append(_normalize_signal(r))
    return out


def _dedup_signals(rows: list[dict]) -> list[dict]:
    """Deduplicate signals by (game_id, market_type, side), keeping strongest.

    Merges alternate sportsbooks into the ``other_books`` list.
    """
    groups: dict[str, list[dict]] = {}
    for r in rows:
        key = f"{r.get('game_id', '')}|{r.get('market_type', '')}|{(r.get('side', '') or '').strip().lower()}"
        groups.setdefault(key, []).append(r)

    deduped = []
    for key, group in groups.items():
        group.sort(key=lambda s: float(s.get("signal_strength", 0)), reverse=True)
        best = group[0]
        # Parse existing other_books if stored as JSON string.
        existing_others = best.get("other_books")
        if isinstance(existing_others, str):
            try:
                existing_others = json.loads(existing_others)
            except (json.JSONDecodeError, TypeError):
                existing_others = []
        elif not isinstance(existing_others, list):
            existing_others = []

        # Add alternates from duplicate rows.
        seen_books = {best.get("sportsbook", "").lower()}
        for ob in existing_others:
            seen_books.add(ob.get("sportsbook", "").lower())
        for alt in group[1:]:
            alt_book = (alt.get("sportsbook", "") or "").lower()
            if alt_book and alt_book not in seen_books:
                existing_others.append({
                    "sportsbook": alt.get("sportsbook", ""),
                    "book_odds": alt.get("book_odds"),
                    "ev_pct": alt.get("edge_percentage"),
                })
                seen_books.add(alt_book)

        best["other_books"] = existing_others
        deduped.append(best)

    deduped.sort(key=lambda s: float(s.get("signal_strength", 0)), reverse=True)
    return deduped


@router.get("/active")
def active_signals(
    sport: str | None = Query(None),
    min_stars: int = Query(3, ge=1, le=5),
) -> dict:
    """Current active signals sorted by strength."""
    try:
        db = get_supabase()
        filters: dict[str, str] = {"status": "eq.active"}
        if min_stars > 1:
            filters["star_rating"] = f"gte.{min_stars}"

        rows = db._get(
            "rtm_signals",
            select="*",
            filters=filters,
            order="signal_strength.desc",
        )

        if sport:
            rows = [r for r in rows if r.get("sport") == sport]

        # Filter to -160/+200 odds range, then deduplicate.
        rows = _filter_odds_range(rows)
        signals = _dedup_signals(rows)
        return {"count": len(signals), "signals": signals}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/history")
def signal_history(
    sport: str | None = Query(None),
    min_stars: int = Query(3, ge=1, le=5),
    status: str | None = Query(None),
    days: int = Query(30, ge=1, le=365),
) -> dict:
    """Graded signal history with filters."""
    try:
        db = get_supabase()
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

        filters: dict[str, str] = {"created_at": f"gte.{cutoff}"}
        if min_stars > 1:
            filters["star_rating"] = f"gte.{min_stars}"
        if status:
            filters["status"] = f"eq.{status}"

        rows = db._get(
            "rtm_signals",
            select="*",
            filters=filters,
            order="created_at.desc",
        )

        if sport:
            rows = [r for r in rows if r.get("sport") == sport]

        # Filter to -160/+200 odds range.
        rows = _filter_odds_range(rows)
        return {"count": len(rows), "signals": rows}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/performance")
def signal_performance(days: int = Query(30, ge=1, le=365)) -> dict:
    """Signal system performance stats."""
    try:
        return _signal_performance_impl(days)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _signal_performance_impl(days: int) -> dict:
    db = get_supabase()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    rows = db._get(
        "rtm_signals",
        select="*",
        filters={"created_at": f"gte.{cutoff}"},
        order="created_at.asc",
    )

    graded = [r for r in rows if r.get("result") in ("win", "loss", "push")]
    pending = [r for r in rows if r.get("result") not in ("win", "loss", "push")]
    wins = sum(1 for r in graded if r["result"] == "win")
    losses = sum(1 for r in graded if r["result"] == "loss")
    pushes = sum(1 for r in graded if r["result"] == "push")
    total_pnl = sum(float(r.get("profit_loss", 0)) for r in graded)
    decided = wins + losses
    bet_amount = 100.0
    total_wagered = len(graded) * bet_amount

    # Streak tracking (most recent first).
    streak = "—"
    streak_count = 0
    streak_type = None
    for r in sorted(graded, key=lambda x: x.get("graded_at", ""), reverse=True):
        res = r["result"]
        if res == "push":
            continue
        if streak_type is None:
            streak_type = res
            streak_count = 1
        elif res == streak_type:
            streak_count += 1
        else:
            break
    if streak_type:
        streak = f"{streak_count}{'W' if streak_type == 'win' else 'L'}"

    # Best / worst day by P/L.
    by_day: dict[str, float] = {}
    for r in graded:
        day = (r.get("graded_at") or r.get("created_at", ""))[:10]
        if day:
            by_day[day] = by_day.get(day, 0) + float(r.get("profit_loss", 0))
    best_day = None
    worst_day = None
    if by_day:
        best_key = max(by_day, key=by_day.get)  # type: ignore[arg-type]
        worst_key = min(by_day, key=by_day.get)  # type: ignore[arg-type]
        best_day = {"date": best_key, "pnl": round(by_day[best_key], 2)}
        worst_day = {"date": worst_key, "pnl": round(by_day[worst_key], 2)}

    # Running P/L chart data (cumulative by day).
    running_pnl: list[dict] = []
    cumulative = 0.0
    for day in sorted(by_day):
        cumulative += by_day[day]
        running_pnl.append({"date": day, "pnl": round(cumulative, 2)})

    # By star tier.
    by_tier: dict[int, dict] = {}
    for r in graded:
        tier = int(r.get("star_rating", 3))
        if tier not in by_tier:
            by_tier[tier] = {"wins": 0, "losses": 0, "pushes": 0, "pnl": 0.0}
        t = by_tier[tier]
        if r["result"] == "win":
            t["wins"] += 1
        elif r["result"] == "loss":
            t["losses"] += 1
        else:
            t["pushes"] += 1
        t["pnl"] += float(r.get("profit_loss", 0))

    tier_breakdown = {}
    for tier, t in sorted(by_tier.items(), reverse=True):
        d = t["wins"] + t["losses"]
        total_t = d + t["pushes"]
        wagered_t = total_t * bet_amount
        tier_breakdown[f"{tier}_star"] = {
            "record": f"{t['wins']}-{t['losses']}" + (f"-{t['pushes']}" if t["pushes"] else ""),
            "win_rate": round(t["wins"] / d * 100, 1) if d else 0,
            "pnl": round(t["pnl"], 2),
            "roi": round(t["pnl"] / wagered_t * 100, 1) if wagered_t else 0,
            "total": total_t,
        }

    # By sport.
    by_sport: dict[str, dict] = {}
    for r in graded:
        sp = r.get("sport", "unknown")
        if sp not in by_sport:
            by_sport[sp] = {"wins": 0, "losses": 0, "pnl": 0.0}
        s = by_sport[sp]
        if r["result"] == "win":
            s["wins"] += 1
        elif r["result"] == "loss":
            s["losses"] += 1
        s["pnl"] += float(r.get("profit_loss", 0))

    sport_breakdown = {}
    for sp, s in sorted(by_sport.items()):
        d = s["wins"] + s["losses"]
        sport_breakdown[sp] = {
            "record": f"{s['wins']}-{s['losses']}",
            "win_rate": round(s["wins"] / d * 100, 1) if d else 0,
            "pnl": round(s["pnl"], 2),
        }

    # CLV summary — the gold standard metric.
    clv_data = {}
    try:
        from scrapers.clv_tracker import get_clv_summary
        clv_data = get_clv_summary(db, days=days)
    except Exception:
        pass

    return {
        "total_signals": len(rows),
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "pending": len(pending),
        "record": f"{wins}-{losses}" + (f"-{pushes}" if pushes else ""),
        "win_rate": round(wins / decided * 100, 1) if decided else 0,
        "total_wagered": round(total_wagered, 2),
        "total_profit_loss": round(total_pnl, 2),
        "roi_percent": round(total_pnl / total_wagered * 100, 1) if total_wagered else 0,
        "streak": streak,
        "best_day": best_day,
        "worst_day": worst_day,
        "running_pnl": running_pnl,
        "by_tier": tier_breakdown,
        "by_sport": sport_breakdown,
        "clv": clv_data,
    }


@router.get("/projection/{player_id}")
def player_projection(
    player_id: int,
    opponent: str = Query("BOS"),
    home_away: str = Query("home"),
) -> dict:
    """Get RTM's projection for a specific player."""
    from projections.projection_engine import ProjectionEngine

    # Try live data first, fall back to mock.
    engine = ProjectionEngine(use_mock=True)
    proj = engine.project_player(player_id, opponent, home_away)

    if proj is None:
        return {"error": f"No projection available for player {player_id}"}

    # Add simulation data for each stat.
    from projections.simulator import PropSimulator
    sim = PropSimulator(num_simulations=10_000)
    sim_data = {}
    for stat, vals in proj.get("projections", {}).items():
        dist_data = sim.get_distribution_data(
            vals["mean"], vals["std_dev"], stat, vals["mean"]
        )
        sim_data[stat] = dist_data

    return {
        **proj,
        "simulation": sim_data,
    }
