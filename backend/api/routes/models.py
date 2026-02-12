from fastapi import APIRouter

router = APIRouter()


@router.get("/")
def get_models() -> dict[str, str]:
    """Get model predictions."""
    return {"message": "models endpoint"}
