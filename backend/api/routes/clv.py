"""CLV (Closing Line Value) API endpoints."""

from fastapi import APIRouter, HTTPException, Query

router = APIRouter()


@router.get("/")
def get_clv_records(
    sport: str | None = Query(None, description="Filter by sport key"),
    hours: int = Query(72, description="Look-back window in hours"),
    status: str | None = Query(None, description="Filter by status (open/closed/expired)"),
) -> list[dict]:
    """Return CLV records with optional filters."""
    try:
        from scrapers.clv_tracker import get_clv_records as _get_records
        from db import get_supabase

        db = get_supabase()
        return _get_records(db, sport=sport, hours=hours, status=status)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/summary")
def get_clv_summary(
    days: int = Query(30, description="Summary window in days"),
) -> dict:
    """Return CLV summary statistics."""
    try:
        from scrapers.clv_tracker import get_clv_summary as _get_summary
        from db import get_supabase

        db = get_supabase()
        return _get_summary(db, days=days)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
