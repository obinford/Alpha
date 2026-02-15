"""Odds and probability conversion utilities."""


def american_to_decimal(odds: int | float) -> float:
    """Convert American odds to decimal odds."""
    odds = float(odds)
    if odds > 0:
        return 1.0 + odds / 100.0
    elif odds < 0:
        return 1.0 + 100.0 / abs(odds)
    return 2.0


def decimal_to_american(decimal_odds: float) -> int:
    """Convert decimal odds to American odds."""
    if decimal_odds >= 2.0:
        return round((decimal_odds - 1) * 100)
    elif decimal_odds > 1.0:
        return round(-100 / (decimal_odds - 1))
    return -100


def american_to_implied_prob(odds: int | float) -> float:
    """Convert American odds to implied probability (0-1)."""
    odds = float(odds)
    if odds > 0:
        return 100.0 / (odds + 100.0)
    elif odds < 0:
        return abs(odds) / (abs(odds) + 100.0)
    return 0.5


def implied_prob_to_american(prob: float) -> int:
    """Convert implied probability (0-1) to American odds."""
    if prob <= 0 or prob >= 1:
        return 0
    if prob >= 0.5:
        return round(-prob / (1 - prob) * 100)
    else:
        return round((1 - prob) / prob * 100)


def devig_pair(over_odds: int, under_odds: int) -> tuple[float, float]:
    """Remove vig from an over/under odds pair.

    Returns (true_over_prob, true_under_prob) summing to 1.0.
    Uses the multiplicative method (power devig).
    """
    over_implied = american_to_implied_prob(over_odds)
    under_implied = american_to_implied_prob(under_odds)
    total = over_implied + under_implied
    if total <= 0:
        return 0.5, 0.5
    return over_implied / total, under_implied / total
