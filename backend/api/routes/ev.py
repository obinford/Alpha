from fastapi import APIRouter, HTTPException, Query

from db import get_supabase, get_latest_ev_opportunities

router = APIRouter()


@router.get("/")
def list_ev_opportunities(
    sport: str | None = Query(None, description="Filter by Odds API sport key (e.g. basketball_nba)"),
    min_ev: float | None = Query(None, ge=0, description="Minimum EV percentage threshold"),
    sportsbook: str | None = Query(None, description="Filter by sportsbook key (e.g. draftkings)"),
) -> dict:
    """Return +EV opportunities from the most recent scan.

    Results are sorted by EV% descending. Optionally filter by sport,
    minimum EV percentage, or sportsbook.
    """
    try:
        db = get_supabase()
        opportunities = get_latest_ev_opportunities(
            db,
            sport=sport,
            min_ev=min_ev,
            sportsbook=sportsbook,
        )
        return {
            "count": len(opportunities),
            "opportunities": opportunities,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
