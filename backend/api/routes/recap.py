"""Daily recap API — performance summaries for specific dates."""

from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Query

from db import get_supabase
from notifications.daily_recap import generate_recap
from notifications.discord import send_morning_briefing

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


@router.get("/morning-briefing")
def morning_briefing(send_discord: bool = Query(False)) -> dict:
    """Generate morning briefing: today's slate + yesterday's results + active signals.

    Pass send_discord=true to also push to Discord.
    """
    db = get_supabase()
    today = datetime.now(timezone.utc).date()
    today_str = today.isoformat()
    tomorrow_str = (today + timedelta(days=1)).isoformat()
    yesterday = today - timedelta(days=1)

    # Yesterday's recap.
    yday_recap = generate_recap(db, yesterday)

    # Today's games count.
    games_today = []
    sports_on_slate = set()
    try:
        rows = db._get(
            "games",
            select="game_id,sport,home_team,away_team,start_time",
            filters={"start_time": f"gte.{today_str}"},
            order="start_time.asc",
        )
        rows = [r for r in rows if r.get("start_time", "") < tomorrow_str]
        games_today = rows
        for r in rows:
            sport = r.get("sport", "")
            if sport:
                label = {
                    "baseball_mlb": "MLB", "basketball_nba": "NBA",
                    "americanfootball_nfl": "NFL", "icehockey_nhl": "NHL",
                    "americanfootball_ncaaf": "CFB", "basketball_ncaab": "CBB",
                }.get(sport, sport)
                sports_on_slate.add(label)
    except Exception:
        pass

    # Active signals.
    active_signals = []
    early_count = 0
    try:
        sigs = db._get(
            "rtm_signals",
            select="*",
            filters={"status": "eq.active"},
            order="signal_strength.desc",
        )
        active_signals = sigs
        for s in sigs:
            ct = s.get("commence_time")
            if ct:
                try:
                    from datetime import datetime as dt
                    start = dt.fromisoformat(ct.replace("Z", "+00:00"))
                    delta = (start - datetime.now(timezone.utc)).total_seconds() / 3600
                    if delta >= 24:
                        early_count += 1
                except Exception:
                    pass
    except Exception:
        pass

    top_signal = active_signals[0] if active_signals else None

    briefing = {
        "date": today_str,
        "games_today": len(games_today),
        "sports_on_slate": sorted(sports_on_slate),
        "active_signals": len(active_signals),
        "early_signals": early_count,
        "top_signal": top_signal,
        "yesterday_record": yday_recap.get("record", "\u2014"),
        "yesterday_units": yday_recap.get("units", 0),
        "yesterday_roi": yday_recap.get("roi", 0),
        "signal_stats": yday_recap.get("signal_stats", {}),
        "games": [
            {
                "sport": r.get("sport", ""),
                "home_team": r.get("home_team", ""),
                "away_team": r.get("away_team", ""),
                "start_time": r.get("start_time", ""),
            }
            for r in games_today[:20]
        ],
    }

    if send_discord:
        send_morning_briefing(briefing)

    return briefing
