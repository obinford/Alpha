"""Bankroll management API — bet sizing and simulation endpoints."""

from dataclasses import asdict

from fastapi import APIRouter, Query
from pydantic import BaseModel

from analytics.bankroll import (
    calculate_bet_size,
    size_multiple_bets,
    simulate_bankroll,
    american_to_decimal,
    implied_probability,
    kelly_criterion,
)
from db import get_supabase, get_latest_ev_opportunities

router = APIRouter()


class SizingRequest(BaseModel):
    bankroll: float
    odds: int
    true_prob: float
    kelly_fraction: float = 0.25


class BatchSizingRequest(BaseModel):
    bankroll: float
    kelly_fraction: float = 0.25
    bets: list[dict] | None = None  # If None, use current EV opportunities.


class SimulationRequest(BaseModel):
    bankroll: float = 10000
    true_prob: float = 0.55
    odds: int = -110
    kelly_fraction: float = 0.25
    num_bets: int = 500
    num_sims: int = 5000


@router.post("/size")
def size_bet(req: SizingRequest) -> dict:
    """Calculate bet size for a single bet using Kelly criterion."""
    sizing = calculate_bet_size(
        bankroll=req.bankroll,
        odds=req.odds,
        true_prob=req.true_prob,
        kelly_fraction=req.kelly_fraction,
    )
    return asdict(sizing)


@router.get("/size")
def size_bet_get(
    bankroll: float = Query(...),
    odds: int = Query(...),
    true_prob: float = Query(...),
    kelly_fraction: float = Query(0.25),
) -> dict:
    """GET version of bet sizing for easy testing."""
    sizing = calculate_bet_size(
        bankroll=bankroll,
        odds=odds,
        true_prob=true_prob,
        kelly_fraction=kelly_fraction,
    )
    return asdict(sizing)


@router.post("/size-batch")
def size_batch(req: BatchSizingRequest) -> dict:
    """Size multiple bets at once. If bets is empty, uses current EV opps."""
    bets = req.bets
    if not bets:
        # Pull from current EV opportunities.
        try:
            db = get_supabase()
            opps = get_latest_ev_opportunities(db, min_ev=1.0)
            bets = []
            for opp in opps:
                game = opp.get("games", {}) or {}
                bets.append({
                    "odds": opp.get("book_odds", -110),
                    "true_prob": float(opp.get("true_prob", 0.5)),
                    "game": f"{game.get('away_team', '')} @ {game.get('home_team', '')}",
                    "pick": opp.get("side", ""),
                    "sportsbook": opp.get("sportsbook", ""),
                    "ev_pct": opp.get("ev_percentage", 0),
                })
        except Exception:
            bets = []

    if not bets:
        return {"bankroll": req.bankroll, "bets": [], "total_risk": 0}

    sized = size_multiple_bets(
        bankroll=req.bankroll,
        bets=bets,
        kelly_fraction=req.kelly_fraction,
    )

    total_risk = sum(b["bet_amount"] for b in sized)
    total_ev = sum(b["ev_dollars"] for b in sized)

    return {
        "bankroll": req.bankroll,
        "kelly_fraction": req.kelly_fraction,
        "bets": sized,
        "total_risk": round(total_risk, 2),
        "total_ev": round(total_ev, 2),
        "risk_pct": round(total_risk / req.bankroll * 100, 2) if req.bankroll > 0 else 0,
    }


@router.post("/simulate")
def run_simulation(req: SimulationRequest) -> dict:
    """Run Monte Carlo bankroll simulation."""
    result = simulate_bankroll(
        starting_bankroll=req.bankroll,
        true_prob=req.true_prob,
        odds=req.odds,
        kelly_fraction=req.kelly_fraction,
        num_bets=req.num_bets,
        num_sims=req.num_sims,
    )
    return asdict(result)


@router.get("/simulate")
def run_simulation_get(
    bankroll: float = Query(10000),
    true_prob: float = Query(0.55),
    odds: int = Query(-110),
    kelly_fraction: float = Query(0.25),
    num_bets: int = Query(500),
    num_sims: int = Query(5000),
) -> dict:
    """GET version of simulation for easy testing."""
    result = simulate_bankroll(
        starting_bankroll=bankroll,
        true_prob=true_prob,
        odds=odds,
        kelly_fraction=kelly_fraction,
        num_bets=num_bets,
        num_sims=num_sims,
    )
    return asdict(result)
