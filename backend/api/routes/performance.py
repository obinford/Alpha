"""Performance tracking API — graded bet results, ROI, and breakdowns."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query

from db import get_supabase, SupabaseClient

router = APIRouter()


def _get_graded_results(
    client: SupabaseClient,
    sport: str | None = None,
    sportsbook: str | None = None,
    market_type: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    result: str | None = None,
) -> list[dict]:
    """Fetch graded bet results with optional filters."""
    filters: dict[str, str] = {}
    if result:
        filters["result"] = f"eq.{result}"
    if date_from:
        filters["graded_at"] = f"gte.{date_from}"
    if date_to:
        # PostgREST doesn't support two filters on same column with dict,
        # so we do client-side filtering for date_to.
        pass

    rows = client._get(
        "bet_results",
        select="*,ev_opportunities(id,game_id,sportsbook,market_type,side,book_odds,ev_percentage,kelly_fraction,timestamp,games(game_id,sport,home_team,away_team,start_time,home_score,away_score))",
        filters=filters if filters else None,
        order="graded_at.desc",
    )

    # Client-side filtering.
    filtered = []
    for r in rows:
        opp = r.get("ev_opportunities", {}) or {}
        game = opp.get("games", {}) or {}

        if sport and game.get("sport") != sport:
            continue
        if sportsbook and opp.get("sportsbook") != sportsbook:
            continue
        if market_type and opp.get("market_type") != market_type:
            continue
        if date_to and r.get("graded_at", "") > date_to:
            continue

        filtered.append(r)

    return filtered


def _range_to_dates(range_str: str | None) -> tuple[str | None, str | None]:
    """Convert a range string like '7d', '30d', 'today' to date_from/date_to."""
    if not range_str or range_str == "all":
        return None, None
    now = datetime.now(timezone.utc)
    if range_str == "today":
        return now.date().isoformat(), None
    if range_str.endswith("d"):
        days = int(range_str[:-1])
        return (now - timedelta(days=days)).date().isoformat(), None
    return None, None


@router.get("/summary")
def performance_summary(
    sport: str | None = Query(None),
    sportsbook: str | None = Query(None),
    range: str | None = Query(None),
) -> dict:
    """Overall performance summary: record, ROI, units."""
    try:
        db = get_supabase()
        date_from, date_to = _range_to_dates(range)
        results = _get_graded_results(db, sport=sport, sportsbook=sportsbook, date_from=date_from, date_to=date_to)

        wins = sum(1 for r in results if r["result"] == "win")
        losses = sum(1 for r in results if r["result"] == "loss")
        pushes = sum(1 for r in results if r["result"] == "push")
        total = len(results)
        units = sum(float(r.get("profit_loss", 0)) for r in results)
        decided = wins + losses

        evs = []
        for r in results:
            opp = r.get("ev_opportunities", {}) or {}
            ev = opp.get("ev_percentage")
            if ev is not None:
                evs.append(float(ev))

        return {
            "total_bets": total,
            "wins": wins,
            "losses": losses,
            "pushes": pushes,
            "record": f"{wins}-{losses}" + (f"-{pushes}" if pushes else ""),
            "win_rate": round(wins / decided * 100, 1) if decided else 0,
            "units_profit": round(units, 2),
            "roi": round(units / total * 100, 1) if total else 0,
            "avg_ev": round(sum(evs) / len(evs), 2) if evs else 0,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/results")
def performance_results(
    sport: str | None = Query(None),
    sportsbook: str | None = Query(None),
    market_type: str | None = Query(None),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    result: str | None = Query(None),
    range: str | None = Query(None),
) -> dict:
    """Detailed graded results with filters."""
    try:
        db = get_supabase()
        # Support both explicit date_from/date_to and shorthand range param.
        if range and not date_from:
            date_from, date_to = _range_to_dates(range)
        raw = _get_graded_results(
            db, sport=sport, sportsbook=sportsbook,
            market_type=market_type, date_from=date_from,
            date_to=date_to, result=result,
        )

        # Flatten nested ev_opportunities / games for the frontend.
        results = []
        for r in raw:
            opp = r.get("ev_opportunities", {}) or {}
            game = opp.get("games", {}) or {}
            results.append({
                "id": r.get("id"),
                "result": r.get("result"),
                "pnl": float(r.get("profit_loss", 0)),
                "date": r.get("graded_at") or opp.get("timestamp"),
                "timestamp": opp.get("timestamp"),
                "sport": game.get("sport", ""),
                "sportsbook": opp.get("sportsbook", ""),
                "home_team": game.get("home_team", ""),
                "away_team": game.get("away_team", ""),
                "game": f"{game.get('away_team', 'Away')} @ {game.get('home_team', 'Home')}",
                "pick": opp.get("side", ""),
                "side": opp.get("side", ""),
                "odds": opp.get("book_odds"),
                "ev_pct": opp.get("ev_percentage"),
                "kelly": opp.get("kelly_fraction"),
                "market_type": opp.get("market_type", ""),
            })

        return {"count": len(results), "results": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/by-sport")
def performance_by_sport(
    sportsbook: str | None = Query(None),
    range: str | None = Query(None),
) -> dict:
    """Performance breakdown by sport."""
    try:
        return _by_sport_impl(sportsbook, range)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _by_sport_impl(sportsbook: str | None, range: str | None) -> dict:
    db = get_supabase()
    date_from, date_to = _range_to_dates(range)
    results = _get_graded_results(db, sportsbook=sportsbook, date_from=date_from, date_to=date_to)

    by_sport: dict[str, dict] = {}
    for r in results:
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

    result: dict[str, dict] = {}
    for sport_key, s in sorted(by_sport.items()):
        total = s["wins"] + s["losses"] + s["pushes"]
        decided = s["wins"] + s["losses"]
        result[sport_key] = {
            "record": f"{s['wins']}-{s['losses']}" + (f"-{s['pushes']}" if s["pushes"] else ""),
            "win_rate": round(s["wins"] / decided * 100, 1) if decided else 0,
            "units": round(s["units"], 2),
            "roi": round(s["units"] / total * 100, 1) if total else 0,
            "total_bets": total,
        }

    return {"by_sport": result}


@router.get("/by-book")
def performance_by_book() -> dict:
    """Performance breakdown by sportsbook."""
    try:
        return _by_book_impl()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _by_book_impl() -> dict:
    db = get_supabase()
    results = _get_graded_results(db)

    by_book: dict[str, dict] = {}
    for r in results:
        opp = r.get("ev_opportunities", {}) or {}
        book = opp.get("sportsbook", "unknown")

        if book not in by_book:
            by_book[book] = {"wins": 0, "losses": 0, "pushes": 0, "units": 0.0}

        s = by_book[book]
        if r["result"] == "win":
            s["wins"] += 1
        elif r["result"] == "loss":
            s["losses"] += 1
        else:
            s["pushes"] += 1
        s["units"] += float(r.get("profit_loss", 0))

    breakdown = []
    for book, s in sorted(by_book.items()):
        total = s["wins"] + s["losses"] + s["pushes"]
        decided = s["wins"] + s["losses"]
        breakdown.append({
            "sportsbook": book,
            "record": f"{s['wins']}-{s['losses']}" + (f"-{s['pushes']}" if s["pushes"] else ""),
            "win_rate": round(s["wins"] / decided * 100, 1) if decided else 0,
            "units": round(s["units"], 2),
            "roi": round(s["units"] / total * 100, 1) if total else 0,
            "total_bets": total,
        })

    return {"breakdown": breakdown}


@router.post("/recalculate")
def recalculate_results() -> dict:
    """Recalculate all existing bet_results with kelly-based unit sizing.

    Fixes historical results that used flat 1-unit sizing.
    Also removes results below the MIN_GRADE_EV_THRESHOLD.
    """
    try:
        from scrapers.grader import recalculate_all_results

        db = get_supabase()
        return recalculate_all_results(db)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
