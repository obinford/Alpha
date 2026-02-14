from fastapi import APIRouter, HTTPException, Query

from db import get_supabase, get_recent_steam_alerts

from datetime import datetime, timedelta, timezone

router = APIRouter()


@router.get("/")
def list_steam_alerts(
    sport: str | None = Query(None, description="Filter by Odds API sport key"),
    hours: float = Query(24, ge=1, le=168, description="Look-back window in hours"),
) -> dict:
    """Return active steam alerts from the look-back window.

    Sorted by detected_at descending. Optionally filter by sport.
    """
    try:
        db = get_supabase()
        since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        alerts = get_recent_steam_alerts(db, since, sport=sport)
        return {
            "count": len(alerts),
            "since_hours": hours,
            "alerts": alerts,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
