"""API routes for RTM Intelligence Layers.

Provides endpoints for book profiling, stale line detection,
market timing intelligence, and prop correlation analysis.
"""

from __future__ import annotations

import os
import sys

from fastapi import APIRouter, Query

# Ensure imports work regardless of working directory.
_backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)
_project_root = os.path.dirname(_backend_dir)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from db import get_supabase
from intelligence.book_profiler import BookProfiler
from intelligence.stale_detector import StaleLineDetector
from intelligence.market_timing import MarketTimingEngine
from intelligence.correlation_engine import PropCorrelationEngine

router = APIRouter()


def _get_db():
    try:
        return get_supabase()
    except Exception:
        return None


# ─── Book Profiles ──────────────────────────────────────────────────────────

@router.get("/book-profiles")
def get_book_profiles():
    """All book profiles ranked by exploitability."""
    db = _get_db()
    profiler = BookProfiler(db)
    profiles = profiler.calculate_book_profiles()
    return {"profiles": profiles, "count": len(profiles)}


@router.get("/book-profiles/{book}")
def get_book_profile(book: str):
    """Deep dive for a single sportsbook."""
    db = _get_db()
    profiler = BookProfiler(db)
    report = profiler.get_book_report(book)
    if report is None:
        return {"error": "No data for this book", "sportsbook": book}
    return report


@router.get("/weakest-books")
def get_weakest_books(
    sport: str = Query(default=None, description="Sport key to filter by"),
    market: str = Query(default=None, description="Market type to filter by"),
):
    """Best books to target right now for a given sport/market."""
    db = _get_db()
    profiler = BookProfiler(db)
    books = profiler.get_weakest_books(sport=sport, market_type=market)
    return {"books": books, "count": len(books)}


# ─── Stale Lines ────────────────────────────────────────────────────────────

@router.get("/stale-lines")
def get_active_stale_lines():
    """All currently active stale lines sorted by edge."""
    db = _get_db()
    detector = StaleLineDetector(db)
    lines = detector.get_active_stale_lines()
    return {"stale_lines": lines, "count": len(lines)}


@router.get("/stale-lines/history")
def get_stale_line_history(
    days: int = Query(default=7, description="Number of days of history"),
):
    """Resolved stale lines with results."""
    db = _get_db()
    detector = StaleLineDetector(db)
    history = detector.get_stale_line_history(days=days)
    return {"history": history, "count": len(history)}


# ─── Market Timing ──────────────────────────────────────────────────────────

@router.get("/timing/optimal-windows")
def get_optimal_windows(
    sport: str = Query(default=None, description="Sport key"),
):
    """Best bet timing by sport."""
    db = _get_db()
    engine = MarketTimingEngine(db)
    windows = engine.get_optimal_bet_window(sport=sport)
    return windows


@router.get("/timing/edge-decay")
def get_edge_decay(
    sport: str = Query(default=None, description="Sport key"),
):
    """How fast edges disappear after detection."""
    db = _get_db()
    engine = MarketTimingEngine(db)
    decay = engine.calculate_edge_decay(sport=sport)
    return decay


@router.get("/timing/lifecycle/{game_id}")
def get_line_lifecycle(game_id: str):
    """Full line lifecycle for a specific game."""
    db = _get_db()
    engine = MarketTimingEngine(db)
    lifecycle = engine.get_game_lifecycle(game_id)
    return {"game_id": game_id, "lifecycle": lifecycle}


# ─── Prop Correlations ──────────────────────────────────────────────────────

@router.get("/correlations/{player_name}")
def get_player_correlations(
    player_name: str,
    prop_type: str = Query(default="points", description="Prop type"),
):
    """What correlates with this player's prop."""
    engine = PropCorrelationEngine()
    correlations = engine.get_correlated_props(player_name, prop_type)
    return correlations


@router.get("/parlay-edges")
def get_parlay_edges():
    """Current +EV correlated parlays."""
    engine = PropCorrelationEngine()
    edges = engine.detect_parlay_edges()
    return {"parlay_edges": edges, "count": len(edges)}


@router.post("/check-correlation")
def check_correlation(body: dict):
    """Check if two props correlate or conflict."""
    engine = PropCorrelationEngine()
    result = engine.check_correlation(
        player1=body.get("player1", ""),
        prop1=body.get("prop1", ""),
        player2=body.get("player2", ""),
        prop2=body.get("prop2", ""),
    )
    return result
