from fastapi import APIRouter

router = APIRouter()


@router.get("/")
def get_odds() -> dict[str, str]:
    """Get current odds data."""
    return {"message": "odds endpoint"}
