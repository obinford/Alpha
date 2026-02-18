import os
import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv

# Ensure the backend directory is on sys.path so sibling packages (db, models,
# shared config) are importable regardless of the working directory.
_backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

# Also add the project root so that `shared.config` is importable.
_project_root = os.path.dirname(_backend_dir)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from api.routes import (
    picks, odds, models as models_router, copilot, ev,
    line_movements, steam_alerts, sharp_dashboard, usage, clv,
    performance, props, recap, bankroll, odds_screen, signal,
    intelligence, kenpom,
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
    allow_credentials=False,
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
app.include_router(clv.router, prefix="/api/clv", tags=["clv"])
app.include_router(performance.router, prefix="/api/performance", tags=["performance"])
app.include_router(props.router, prefix="/api/props", tags=["props"])
app.include_router(recap.router, prefix="/api/recap", tags=["recap"])
app.include_router(bankroll.router, prefix="/api/bankroll", tags=["bankroll"])
app.include_router(odds_screen.router, prefix="/api/odds-screen", tags=["odds-screen"])
app.include_router(signal.router, prefix="/api/signals", tags=["signals"])
app.include_router(intelligence.router, prefix="/api/intelligence", tags=["intelligence"])
app.include_router(kenpom.router, prefix="/api/kenpom", tags=["kenpom"])


@app.get("/health")
def health_check() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "ok", "service": "rtm-picks-api"}


@app.get("/")
def root_redirect() -> RedirectResponse:
    """Redirect / to the +EV dashboard."""
    return RedirectResponse(url="/dashboard.html")


# Serve frontend static files at / — must be last so API routes take priority.
_frontend_dir = os.path.join(_backend_dir, "..", "frontend")
if os.path.isdir(_frontend_dir):
    app.mount("/", StaticFiles(directory=_frontend_dir, html=True), name="frontend")
