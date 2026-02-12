from fastapi import APIRouter, HTTPException

from db import get_supabase, get_open_ev_opportunities

router = APIRouter()


@router.get("/")
def list_ev_opportunities() -> list[dict]:
    """Return all currently open +EV opportunities, sorted by EV% descending."""
    try:
        db = get_supabase()
        return get_open_ev_opportunities(db)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
