"""Kelly Criterion — the definitive implementation for the entire platform.

ALL Kelly calculations across the platform MUST use this module.
No inline Kelly math anywhere. One formula, one source of truth.

Formula:
    full_kelly = (b * p - q) / b
    where b = decimal_odds - 1, p = true probability, q = 1 - p

    quarter_kelly = full_kelly * 0.25
    units = quarter_kelly * 100   (1 unit = 1% of bankroll)

Returns:
    kelly_fraction()  → fractional Kelly as bankroll fraction (e.g. 0.0365)
    kelly_units()     → quarter-Kelly units (e.g. 3.65u)
    kelly_full()      → full Kelly as bankroll fraction (e.g. 0.146)

No caps. No minimums. If Kelly is negative (no edge), return 0.
Let the math speak.
"""

from .ev_calculator import american_to_decimal


def kelly_full(probability: float, american_odds: int) -> float:
    """Calculate full Kelly bet fraction.

    Full Kelly = (b * p - q) / b
    where b = decimal_odds - 1, p = probability, q = 1 - p.

    Args:
        probability: Estimated true probability of winning (0-1).
        american_odds: American odds offered by the sportsbook.

    Returns:
        Full Kelly fraction of bankroll (0.0 if no edge).
    """
    if probability <= 0 or probability >= 1:
        return 0.0
    decimal_odds = american_to_decimal(american_odds)
    b = decimal_odds - 1
    if b <= 0:
        return 0.0
    q = 1 - probability
    fk = (b * probability - q) / b
    return max(0.0, fk)


def kelly_fraction(
    probability: float, american_odds: int, fraction: float = 0.25
) -> float:
    """Calculate fractional Kelly bet size.

    Args:
        probability: Estimated true probability of winning (0-1).
        american_odds: American odds offered by the sportsbook.
        fraction: Kelly fraction (default 0.25 = quarter Kelly).

    Returns:
        Fractional Kelly as a fraction of bankroll (e.g. 0.0365 for 3.65%).
        Returns 0.0 if no edge.
    """
    return kelly_full(probability, american_odds) * fraction


def kelly_units(
    probability: float, american_odds: int, fraction: float = 0.25
) -> float:
    """Calculate Kelly bet size in units (1 unit = 1% of bankroll).

    This is the canonical function for unit sizing across the platform.

    Formula: full_kelly * fraction * 100
    e.g. full_kelly=0.146, fraction=0.25 → 0.146 * 0.25 * 100 = 3.65u

    Args:
        probability: Estimated true probability of winning (0-1).
        american_odds: American odds offered by the sportsbook.
        fraction: Kelly fraction (default 0.25 = quarter Kelly).

    Returns:
        Recommended units to bet (0.0 if no edge). No cap.

    Examples:
        >>> kelly_units(0.55, -110)   # slight favorite edge
        1.38
        >>> kelly_units(0.40, 200)    # underdog with real edge
        2.50
        >>> kelly_units(0.45, -110)   # no edge
        0.0
    """
    return kelly_full(probability, american_odds) * fraction * 100


def kelly_from_ev(ev_pct: float, american_odds: int) -> float:
    """Calculate Kelly units directly from EV% and odds.

    Useful when you have EV% but not the true probability.
    Derives true_prob from EV% and odds, then runs Kelly.

    Args:
        ev_pct: Expected value as a percentage (e.g. 5.2 means +5.2%).
        american_odds: American odds offered by the sportsbook.

    Returns:
        Quarter-Kelly units (1 unit = 1% of bankroll).
    """
    decimal_odds = american_to_decimal(american_odds)
    if decimal_odds <= 0:
        return 0.0
    # EV% = (true_prob * decimal_odds - 1) * 100
    # true_prob = (EV%/100 + 1) / decimal_odds
    true_prob = (ev_pct / 100 + 1) / decimal_odds
    if true_prob <= 0 or true_prob >= 1:
        return 0.0
    return kelly_units(true_prob, american_odds)
