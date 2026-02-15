"""Daily recap API — performance summaries for specific dates."""

from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Query

from db import get_supabase
from notifications.daily_recap import generate_recap

router = APIRouter()


@router.get("/today")
def recap_today() -> dict:
    """Recap for today (in-progress day)."""
    db = get_supabase()
    today = datetime.now(timezone.utc).date()
    return generate_recap(db, today)


@router.get("/yesterday")
def recap_yesterday() -> dict:
    """Recap for yesterday (most common use case)."""
    db = get_supabase()
    yesterday = datetime.now(timezone.utc).date() - timedelta(days=1)
    return generate_recap(db, yesterday)


@router.get("/date/{target_date}")
def recap_for_date(target_date: str) -> dict:
    """Recap for a specific date (YYYY-MM-DD format)."""
    db = get_supabase()
    d = date.fromisoformat(target_date)
    return generate_recap(db, d)


@router.get("/recent")
def recap_recent(days: int = Query(7, ge=1, le=30)) -> dict:
    """Recent recaps for the last N days."""
    db = get_supabase()
    today = datetime.now(timezone.utc).date()

    recaps = []
    totals = {"wins": 0, "losses": 0, "pushes": 0, "units": 0.0, "total_bets": 0}

    for i in range(days):
        d = today - timedelta(days=i)
        recap = generate_recap(db, d)
        # Only include days with bets.
        if recap["total_bets"] > 0:
            recaps.append(recap)
        totals["wins"] += recap["wins"]
        totals["losses"] += recap["losses"]
        totals["pushes"] += recap["pushes"]
        totals["units"] += recap["units"]
        totals["total_bets"] += recap["total_bets"]

    decided = totals["wins"] + totals["losses"]
    return {
        "days": days,
        "recaps": recaps,
        "period_summary": {
            "record": f"{totals['wins']}-{totals['losses']}" + (f"-{totals['pushes']}" if totals["pushes"] else ""),
            "total_bets": totals["total_bets"],
            "units": round(totals["units"], 2),
            "roi": round(totals["units"] / totals["total_bets"] * 100, 1) if totals["total_bets"] else 0,
            "win_rate": round(totals["wins"] / decided * 100, 1) if decided else 0,
        },
    }
