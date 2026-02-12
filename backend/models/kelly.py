"""Kelly Criterion bankroll management."""

from .ev_calculator import american_to_decimal


def kelly_fraction(
    probability: float, american_odds: int, fraction: float = 0.25
) -> float:
    """Calculate fractional Kelly bet size.

    Full Kelly = (bp - q) / b
    where b = decimal_odds - 1, p = probability, q = 1 - p.

    Args:
        probability: Estimated true probability of winning (0-1).
        american_odds: American odds offered by the sportsbook.
        fraction: Kelly fraction for safety (default 0.25 = quarter Kelly).

    Returns:
        Recommended bet size as fraction of bankroll (0 if negative edge).
    """
    decimal_odds = american_to_decimal(american_odds)
    b = decimal_odds - 1
    q = 1 - probability
    full_kelly = (b * probability - q) / b
    if full_kelly <= 0:
        return 0.0
    return full_kelly * fraction
