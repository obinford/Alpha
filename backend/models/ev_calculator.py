"""Expected Value calculator - compares book odds to sharp no-vig lines."""


def american_to_implied_prob(american_odds: int) -> float:
    """Convert American odds to implied probability.

    Args:
        american_odds: American odds (e.g. -110, +150).

    Returns:
        Implied probability (0-1), including vig.
    """
    if american_odds < 0:
        return -american_odds / (-american_odds + 100)
    return 100 / (american_odds + 100)


def american_to_decimal(american_odds: int) -> float:
    """Convert American odds to decimal odds.

    Args:
        american_odds: American odds (e.g. -110, +150).

    Returns:
        Decimal odds (e.g. 1.91, 2.50).
    """
    if american_odds < 0:
        return 1 + 100 / -american_odds
    return 1 + american_odds / 100


def calculate_no_vig_probability(
    line_a: int, line_b: int
) -> tuple[float, float]:
    """Remove vig from a two-way market to get true probabilities.

    Uses the multiplicative method: divide each implied probability by the
    sum of all implied probabilities (the overround).

    Args:
        line_a: American odds for side A.
        line_b: American odds for side B.

    Returns:
        Tuple of (prob_a, prob_b) as true probabilities summing to 1.0.
    """
    implied_a = american_to_implied_prob(line_a)
    implied_b = american_to_implied_prob(line_b)
    overround = implied_a + implied_b
    return implied_a / overround, implied_b / overround


def calculate_ev(book_odds: int, true_probability: float) -> float:
    """Calculate expected value of a bet.

    EV% = (true_probability * decimal_odds - 1) * 100

    Args:
        book_odds: American odds offered by the sportsbook.
        true_probability: True probability of the outcome (0-1).

    Returns:
        Expected value as a percentage (e.g. 5.2 means +5.2% EV).
    """
    decimal_odds = american_to_decimal(book_odds)
    ev = (true_probability * decimal_odds) - 1
    return ev * 100


def validate_edge(
    ev_pct: float, true_prob: float, book_odds: int,
    devig_confidence: str = "",
) -> tuple[str, list[str]]:
    """Classify edge confidence and flag suspicious values.

    Returns:
        (confidence_label, warnings_list)
        confidence_label: HIGH, MEDIUM, LOW, or CAUTION
        warnings_list: list of warning strings (empty = clean)
    """
    warnings: list[str] = []

    # Flag extreme EVs.
    if ev_pct > 20.0:
        warnings.append(f"EXTREME_EV: {ev_pct:.1f}% — likely stale line or data error")

    # Flag invalid probabilities.
    if true_prob <= 0 or true_prob >= 1:
        warnings.append(f"INVALID_PROB: {true_prob}")

    # Flag suspicious large-favorite edges.
    if ev_pct > 15.0 and true_prob > 0.5:
        warnings.append("LARGE_FAV_EDGE: >15% EV on a favorite is unusual")

    # Confidence based on devig source.
    if devig_confidence:
        confidence = devig_confidence
    elif ev_pct > 10.0:
        confidence = "LOW"  # High EV without known source → suspicious
    elif ev_pct > 5.0:
        confidence = "MEDIUM"
    else:
        confidence = "HIGH"

    if warnings:
        confidence = "CAUTION"

    return confidence, warnings
