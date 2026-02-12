from fastapi import APIRouter

router = APIRouter()


@router.post("/chat")
def chat() -> dict[str, str]:
    """AI co-pilot chat endpoint."""
    return {"message": "copilot endpoint"}
