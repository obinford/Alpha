from fastapi import APIRouter, HTTPException, Query

from db import get_supabase, get_line_movements_for_game, get_biggest_recent_moves

from datetime import datetime, timedelta, timezone

router = APIRouter()


@router.get("/")
def recent_biggest_moves(
    hours: float = Query(6, ge=0.5, le=48, description="Look-back window in hours"),
    limit: int = Query(20, ge=1, le=100, description="Max results"),
) -> dict:
    """Return recent line movements with the biggest odds changes.

    Sorted by absolute odds_change descending. Defaults to last 6 hours.
    """
    try:
        db = get_supabase()
        since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        moves = get_biggest_recent_moves(db, since, limit=limit)
        return {
            "count": len(moves),
            "since_hours": hours,
            "movements": moves,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{game_id}")
def game_line_movements(
    game_id: str,
    market_type: str | None = Query(None, description="Filter by market (h2h, spreads, totals)"),
) -> dict:
    """Return full odds history for a specific game, all bookmakers, sorted by timestamp."""
    try:
        db = get_supabase()
        movements = get_line_movements_for_game(db, game_id, market_type=market_type)
        return {
            "game_id": game_id,
            "count": len(movements),
            "movements": movements,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
