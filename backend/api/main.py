import os
import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

# Ensure the backend directory is on sys.path so sibling packages (db, models,
# shared config) are importable regardless of the working directory.
_backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from api.routes import (
    picks, odds, models as models_router, copilot, ev,
    line_movements, steam_alerts, sharp_dashboard, usage,
)

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
app.include_router(line_movements.router, prefix="/api/line-movements", tags=["line-movements"])
app.include_router(steam_alerts.router, prefix="/api/steam-alerts", tags=["steam-alerts"])
app.include_router(sharp_dashboard.router, prefix="/api/sharp-dashboard", tags=["sharp-dashboard"])
app.include_router(usage.router, prefix="/api/usage", tags=["usage"])


@app.get("/health")
def health_check() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "ok", "service": "rtm-picks-api"}
