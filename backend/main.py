from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from api.routes import picks, odds, models as models_router, copilot, ev

load_dotenv()

app = FastAPI(
    title="RTM Picks Platform API",
    description="AI-powered sports betting intelligence",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(picks.router, prefix="/api/picks", tags=["picks"])
app.include_router(odds.router, prefix="/api/odds", tags=["odds"])
app.include_router(models_router.router, prefix="/api/models", tags=["models"])
app.include_router(copilot.router, prefix="/api/copilot", tags=["copilot"])
app.include_router(ev.router, prefix="/api/ev-opportunities", tags=["ev"])


@app.get("/health")
def health_check() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "ok", "service": "rtm-picks-api"}
