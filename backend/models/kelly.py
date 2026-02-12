"""Kelly Criterion bankroll management."""


def kelly_fraction(
    probability: float, decimal_odds: float, fraction: float = 0.25
) -> float:
    """Calculate fractional Kelly bet size.

    Args:
        probability: Estimated true probability of winning (0-1).
        decimal_odds: Decimal odds offered by the sportsbook.
        fraction: Kelly fraction for safety (default 0.25 = quarter Kelly).

    Returns:
        Recommended bet size as fraction of bankroll.
    """
    raise NotImplementedError
