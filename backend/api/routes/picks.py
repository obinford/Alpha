from fastapi import APIRouter

router = APIRouter()


@router.get("/")
def get_picks() -> dict[str, str]:
    """Get current picks."""
    return {"message": "picks endpoint"}
