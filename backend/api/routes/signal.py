"""RTM Signal API — active signals, history, and performance."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Query

from db import get_supabase

router = APIRouter()


@router.get("/active")
def active_signals(
    sport: str | None = Query(None),
    min_stars: int = Query(3, ge=1, le=5),
) -> dict:
    """Current active signals sorted by strength."""
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

    return {"count": len(rows), "signals": rows}


@router.get("/history")
def signal_history(
    sport: str | None = Query(None),
    min_stars: int = Query(3, ge=1, le=5),
    status: str | None = Query(None),
    days: int = Query(30, ge=1, le=365),
) -> dict:
    """Graded signal history with filters."""
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

    return {"count": len(rows), "signals": rows}


@router.get("/performance")
def signal_performance(days: int = Query(30, ge=1, le=365)) -> dict:
    """Signal system performance stats."""
    db = get_supabase()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    rows = db._get(
        "rtm_signals",
        select="*",
        filters={"created_at": f"gte.{cutoff}"},
    )

    graded = [r for r in rows if r.get("result") in ("win", "loss", "push")]
    total = len(graded)
    wins = sum(1 for r in graded if r["result"] == "win")
    losses = sum(1 for r in graded if r["result"] == "loss")
    pushes = sum(1 for r in graded if r["result"] == "push")
    units = sum(float(r.get("profit_loss", 0)) for r in graded)
    decided = wins + losses

    # By star tier.
    by_tier: dict[int, dict] = {}
    for r in graded:
        tier = int(r.get("star_rating", 3))
        if tier not in by_tier:
            by_tier[tier] = {"wins": 0, "losses": 0, "pushes": 0, "units": 0.0}
        t = by_tier[tier]
        if r["result"] == "win":
            t["wins"] += 1
        elif r["result"] == "loss":
            t["losses"] += 1
        else:
            t["pushes"] += 1
        t["units"] += float(r.get("profit_loss", 0))

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
    for r in graded:
        sp = r.get("sport", "unknown")
        if sp not in by_sport:
            by_sport[sp] = {"wins": 0, "losses": 0, "units": 0.0}
        s = by_sport[sp]
        if r["result"] == "win":
            s["wins"] += 1
        elif r["result"] == "loss":
            s["losses"] += 1
        s["units"] += float(r.get("profit_loss", 0))

    sport_breakdown = {}
    for sp, s in sorted(by_sport.items()):
        d = s["wins"] + s["losses"]
        sport_breakdown[sp] = {
            "record": f"{s['wins']}-{s['losses']}",
            "win_rate": round(s["wins"] / d * 100, 1) if d else 0,
            "units": round(s["units"], 2),
        }

    # Average signal strength of winners vs losers.
    winner_strengths = [float(r.get("signal_strength", 0)) for r in graded if r["result"] == "win"]
    loser_strengths = [float(r.get("signal_strength", 0)) for r in graded if r["result"] == "loss"]

    return {
        "total_signals": len(rows),
        "graded_signals": total,
        "pending_signals": len(rows) - total,
        "record": f"{wins}-{losses}" + (f"-{pushes}" if pushes else ""),
        "win_rate": round(wins / decided * 100, 1) if decided else 0,
        "total_units": round(units, 2),
        "roi": round(units / total * 100, 1) if total else 0,
        "avg_winner_strength": round(sum(winner_strengths) / len(winner_strengths), 1) if winner_strengths else 0,
        "avg_loser_strength": round(sum(loser_strengths) / len(loser_strengths), 1) if loser_strengths else 0,
        "by_tier": tier_breakdown,
        "by_sport": sport_breakdown,
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
