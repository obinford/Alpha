"""API usage tracking endpoint."""

from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.get("/")
def get_usage() -> dict:
    """Return current API usage stats and budget."""
    try:
        from scrapers.scheduler import load_usage, budget_remaining, MONTHLY_API_BUDGET

        usage = load_usage()
        remaining = budget_remaining(usage)

        return {
            "month": usage.month,
            "requests_used": usage.requests_used,
            "requests_remaining": remaining,
            "monthly_budget": MONTHLY_API_BUDGET,
            "percent_used": round(
                usage.requests_used / MONTHLY_API_BUDGET * 100, 1
            ) if MONTHLY_API_BUDGET > 0 else 0,
            "by_sport": usage.requests_by_sport,
            "last_updated": usage.last_updated,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
