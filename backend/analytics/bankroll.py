"""Bankroll management and Kelly criterion sizing.

Provides bet sizing calculations using full Kelly, fractional Kelly, and
flat unit strategies. Includes a bankroll simulator for Monte Carlo analysis.
"""

import math
import random
from dataclasses import dataclass, field


@dataclass
class BetSizing:
    """Result of a bet sizing calculation."""
    strategy: str
    bankroll: float
    edge: float
    odds: int
    kelly_fraction_used: float
    kelly_pct: float        # Full Kelly % of bankroll
    bet_pct: float          # Actual % after fraction applied
    bet_amount: float       # Dollar amount to bet
    units: float            # Number of units (1 unit = 1% of bankroll)
    ev_dollars: float       # Expected value in dollars


@dataclass
class SimulationResult:
    """Result of a bankroll simulation run."""
    starting_bankroll: float
    ending_bankroll: float
    peak_bankroll: float
    min_bankroll: float
    total_bets: int
    win_count: int
    loss_count: int
    net_profit: float
    roi_pct: float
    max_drawdown_pct: float
    ruin_probability: float  # 0-1
    growth_rate: float       # Geometric mean


def american_to_decimal(odds: int) -> float:
    """Convert American odds to decimal odds."""
    if odds > 0:
        return 1.0 + odds / 100.0
    elif odds < 0:
        return 1.0 + 100.0 / abs(odds)
    return 1.0


def implied_probability(odds: int) -> float:
    """Convert American odds to implied probability."""
    if odds > 0:
        return 100.0 / (odds + 100.0)
    elif odds < 0:
        return abs(odds) / (abs(odds) + 100.0)
    return 0.5


def kelly_criterion(true_prob: float, decimal_odds: float) -> float:
    """Calculate full Kelly bet fraction.

    Returns the fraction of bankroll to bet (0.0 to 1.0).
    Negative values are clamped to 0.0 (no bet).
    """
    b = decimal_odds - 1.0  # Net odds
    q = 1.0 - true_prob
    if b <= 0:
        return 0.0
    kelly = (true_prob * b - q) / b
    return max(0.0, kelly)


def calculate_bet_size(
    bankroll: float,
    odds: int,
    true_prob: float,
    kelly_fraction: float = 0.25,
    unit_size: float | None = None,
) -> BetSizing:
    """Calculate optimal bet size using fractional Kelly criterion.

    Args:
        bankroll: Total bankroll in dollars.
        odds: American odds for the bet.
        true_prob: Estimated true probability of winning (0-1).
        kelly_fraction: Fraction of Kelly to use (0.25 = quarter Kelly).
        unit_size: Optional fixed unit size. If None, 1 unit = 1% of bankroll.

    Returns:
        BetSizing with all calculated values.
    """
    decimal = american_to_decimal(odds)
    full_kelly = kelly_criterion(true_prob, decimal)
    bet_pct = full_kelly * kelly_fraction

    bet_amount = bankroll * bet_pct

    # Units: quarter-Kelly fraction scaled by 10, clamped to [0.1, 3.0].
    # e.g. full_kelly=0.146, fraction=0.25 → 0.146*0.25*10 = 0.365u.
    if unit_size is not None and unit_size > 0:
        units = bet_amount / unit_size
    else:
        units = full_kelly * kelly_fraction * 10
    units = max(0.1, min(units, 3.0))

    # Expected value.
    profit_if_win = bet_amount * (decimal - 1)
    ev_dollars = true_prob * profit_if_win - (1 - true_prob) * bet_amount

    return BetSizing(
        strategy=f"{kelly_fraction:.0%} Kelly",
        bankroll=bankroll,
        edge=round((true_prob * decimal - 1) * 100, 2),
        odds=odds,
        kelly_fraction_used=kelly_fraction,
        kelly_pct=round(full_kelly * 100, 4),
        bet_pct=round(bet_pct * 100, 4),
        bet_amount=round(bet_amount, 2),
        units=round(units, 2),
        ev_dollars=round(ev_dollars, 2),
    )


def size_multiple_bets(
    bankroll: float,
    bets: list[dict],
    kelly_fraction: float = 0.25,
) -> list[dict]:
    """Size multiple simultaneous bets with Kelly criterion.

    Each bet dict should have: odds (int), true_prob (float),
    and optionally: game, pick, sportsbook, ev_pct.

    Returns list of dicts with sizing info added.
    """
    results = []
    for bet in bets:
        sizing = calculate_bet_size(
            bankroll=bankroll,
            odds=bet["odds"],
            true_prob=bet["true_prob"],
            kelly_fraction=kelly_fraction,
        )
        results.append({
            **bet,
            "kelly_pct": sizing.kelly_pct,
            "bet_pct": sizing.bet_pct,
            "bet_amount": sizing.bet_amount,
            "units": sizing.units,
            "ev_dollars": sizing.ev_dollars,
            "edge": sizing.edge,
        })

    # Sort by edge descending.
    results.sort(key=lambda x: x.get("edge", 0), reverse=True)
    return results


def simulate_bankroll(
    starting_bankroll: float,
    true_prob: float,
    odds: int,
    kelly_fraction: float = 0.25,
    num_bets: int = 1000,
    num_sims: int = 10000,
    ruin_threshold: float = 0.1,
) -> SimulationResult:
    """Monte Carlo simulation of bankroll growth.

    Args:
        starting_bankroll: Starting bankroll.
        true_prob: True win probability.
        odds: American odds.
        kelly_fraction: Fraction of Kelly to use.
        num_bets: Number of bets per simulation.
        num_sims: Number of simulation runs.
        ruin_threshold: Fraction of starting bankroll considered "ruin".

    Returns:
        Aggregated SimulationResult.
    """
    decimal = american_to_decimal(odds)
    full_kelly = kelly_criterion(true_prob, decimal)
    bet_fraction = full_kelly * kelly_fraction

    ruin_level = starting_bankroll * ruin_threshold
    ruin_count = 0
    ending_bankrolls = []
    peak_bankrolls = []
    min_bankrolls = []
    max_drawdowns = []
    total_wins = 0
    total_bets_placed = 0

    for _ in range(num_sims):
        bankroll = starting_bankroll
        peak = bankroll
        trough = bankroll
        wins = 0
        ruined = False

        for _ in range(num_bets):
            if bankroll <= ruin_level:
                ruined = True
                break

            bet_size = bankroll * bet_fraction
            if random.random() < true_prob:
                bankroll += bet_size * (decimal - 1)
                wins += 1
            else:
                bankroll -= bet_size

            peak = max(peak, bankroll)
            trough = min(trough, bankroll)

        if ruined:
            ruin_count += 1

        drawdown = (peak - trough) / peak if peak > 0 else 0
        ending_bankrolls.append(bankroll)
        peak_bankrolls.append(peak)
        min_bankrolls.append(trough)
        max_drawdowns.append(drawdown)
        total_wins += wins
        total_bets_placed += num_bets

    avg_ending = sum(ending_bankrolls) / len(ending_bankrolls)
    avg_peak = sum(peak_bankrolls) / len(peak_bankrolls)
    avg_min = sum(min_bankrolls) / len(min_bankrolls)
    avg_drawdown = sum(max_drawdowns) / len(max_drawdowns)

    net_profit = avg_ending - starting_bankroll
    total_wagered = starting_bankroll * bet_fraction * num_bets
    roi = (net_profit / total_wagered * 100) if total_wagered > 0 else 0

    # Geometric growth rate.
    growth_rate = (avg_ending / starting_bankroll) ** (1 / num_bets) - 1 if avg_ending > 0 else 0

    return SimulationResult(
        starting_bankroll=starting_bankroll,
        ending_bankroll=round(avg_ending, 2),
        peak_bankroll=round(avg_peak, 2),
        min_bankroll=round(avg_min, 2),
        total_bets=num_bets,
        win_count=round(total_wins / num_sims),
        loss_count=num_bets - round(total_wins / num_sims),
        net_profit=round(net_profit, 2),
        roi_pct=round(roi, 2),
        max_drawdown_pct=round(avg_drawdown * 100, 2),
        ruin_probability=round(ruin_count / num_sims, 4),
        growth_rate=round(growth_rate * 100, 6),
    )
