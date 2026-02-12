"""Expected Value calculator - compares book odds to sharp no-vig lines."""


def calculate_no_vig_probability(
    line_a: float, line_b: float
) -> tuple[float, float]:
    """Remove vig from a two-way market to get true probabilities.

    Args:
        line_a: American odds for side A.
        line_b: American odds for side B.

    Returns:
        Tuple of (prob_a, prob_b) as true probabilities summing to 1.0.
    """
    raise NotImplementedError


def calculate_ev(
    book_odds: float, true_probability: float
) -> float:
    """Calculate expected value of a bet.

    Args:
        book_odds: American odds offered by the sportsbook.
        true_probability: True probability of the outcome (0-1).

    Returns:
        Expected value as a percentage.
    """
    raise NotImplementedError
