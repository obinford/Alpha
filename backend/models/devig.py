"""Devigging engine — removes bookmaker vig to find true probabilities.

This is the most important calculation in the platform. Accurate devigging
= accurate true probabilities = accurate EV = profitable betting.

Source hierarchy (highest confidence first):
  1. Pinnacle — gold standard sharp book (devig_confidence = HIGH)
  2. Exchange consensus — Novig, Betfair, Matchbook (MEDIUM)
  3. Sharp book weighted average — Circa, BetOnline, Bovada (LOW)
  4. Market average of all books — last resort (CAUTION)

Devig methods:
  - Multiplicative: divide each implied prob by the overround
  - Additive: subtract equal share of overround from each implied prob
  - Power (Shin): solve for the insider trading parameter
  - The engine picks the most conservative true probability across methods

Usage:
    from models.devig import devig_game_market, DevigResult

    result = devig_game_market(game, "h2h")
    # result.true_probs = {("TeamA", None): 0.55, ("TeamB", None): 0.45}
    # result.source = "pinnacle"
    # result.method = "multiplicative"
    # result.confidence = "HIGH"
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal

from models.ev_calculator import american_to_implied_prob

# Type alias for confidence levels.
Confidence = Literal["HIGH", "MEDIUM", "LOW", "CAUTION"]


@dataclass(frozen=True)
class DevigResult:
    """Result of devigging a two-way market."""

    true_prob_a: float
    true_prob_b: float
    method: str            # multiplicative | additive | power | shin
    source: str            # book key(s) used, e.g. "pinnacle" or "weighted:circa,betonlineag"
    confidence: Confidence
    overround: float       # original overround before devigging

    @property
    def true_probs(self) -> tuple[float, float]:
        return (self.true_prob_a, self.true_prob_b)


# ---------------------------------------------------------------------------
# Devig methods
# ---------------------------------------------------------------------------

def devig_multiplicative(imp_a: float, imp_b: float) -> tuple[float, float]:
    """Multiplicative (proportional) devig.

    Each implied probability is divided by the total overround.
    Best for balanced markets where vig is applied proportionally.

    true_p = implied_p / (implied_a + implied_b)
    """
    total = imp_a + imp_b
    if total <= 0:
        return 0.5, 0.5
    return imp_a / total, imp_b / total


def devig_additive(imp_a: float, imp_b: float) -> tuple[float, float]:
    """Additive devig.

    Equal share of overround is subtracted from each side.
    Better for heavily favored markets where vig is loaded onto the favorite.

    true_p = implied_p - (overround - 1) / 2
    """
    total = imp_a + imp_b
    if total <= 0:
        return 0.5, 0.5
    excess = (total - 1.0) / 2.0
    a = max(0.001, imp_a - excess)
    b = max(0.001, imp_b - excess)
    # Renormalize to exactly 1.0.
    s = a + b
    return a / s, b / s


def devig_power(imp_a: float, imp_b: float) -> tuple[float, float]:
    """Power devig method.

    Finds exponent k such that imp_a^k + imp_b^k = 1.
    More theoretically sound than multiplicative for asymmetric markets.
    Uses binary search to find k.
    """
    if imp_a <= 0 or imp_b <= 0:
        return 0.5, 0.5
    total = imp_a + imp_b
    if abs(total - 1.0) < 0.0001:
        # No vig to remove.
        return imp_a, imp_b

    # Binary search for k where imp_a^k + imp_b^k = 1.
    lo, hi = 0.5, 2.0
    for _ in range(100):
        k = (lo + hi) / 2.0
        val = imp_a ** k + imp_b ** k
        if val > 1.0:
            lo = k
        else:
            hi = k
        if abs(val - 1.0) < 1e-10:
            break

    k = (lo + hi) / 2.0
    a = imp_a ** k
    b = imp_b ** k
    s = a + b
    return a / s, b / s


def devig_shin(imp_a: float, imp_b: float) -> tuple[float, float]:
    """Shin devig method.

    Models the overround as arising from insider (informed) trading.
    Solves for the Shin parameter z where:
      true_p = (sqrt(z^2 + 4*(1-z)*imp_p^2/total) - z) / (2*(1-z))

    Better for markets with potential informed trading (e.g. props).
    """
    total = imp_a + imp_b
    if total <= 0:
        return 0.5, 0.5
    if abs(total - 1.0) < 0.0001:
        return imp_a, imp_b

    # Solve for Shin parameter z: the fraction of informed traders.
    # z = (total - 1) / (n - 1) where n = number of outcomes.
    z = (total - 1.0) / 1.0  # For 2-way market: n=2, so n-1=1.
    z = max(0.0, min(z, 0.99))  # Clamp.

    def shin_prob(imp_p: float) -> float:
        if z >= 1.0:
            return imp_p / total
        discriminant = z * z + 4.0 * (1.0 - z) * (imp_p ** 2) / total
        if discriminant < 0:
            return imp_p / total
        return (math.sqrt(discriminant) - z) / (2.0 * (1.0 - z))

    a = shin_prob(imp_a)
    b = shin_prob(imp_b)
    s = a + b
    if s <= 0:
        return 0.5, 0.5
    return a / s, b / s


# ---------------------------------------------------------------------------
# Conservative devig: run all methods, pick the most conservative
# ---------------------------------------------------------------------------

_DEVIG_METHODS = {
    "multiplicative": devig_multiplicative,
    "additive": devig_additive,
    "power": devig_power,
    "shin": devig_shin,
}


def devig_best(
    odds_a: int, odds_b: int, target_side: int = 0
) -> tuple[float, float, str]:
    """Run all devig methods and return the most conservative for the target side.

    'Most conservative' means the lowest true probability for the side we're
    considering betting on. This protects against overestimating our edge.

    Args:
        odds_a: American odds for side A.
        odds_b: American odds for side B.
        target_side: 0 for side A, 1 for side B.

    Returns:
        (true_prob_a, true_prob_b, method_name)
    """
    imp_a = american_to_implied_prob(odds_a)
    imp_b = american_to_implied_prob(odds_b)

    results: list[tuple[float, float, str]] = []
    for name, fn in _DEVIG_METHODS.items():
        pa, pb = fn(imp_a, imp_b)
        results.append((pa, pb, name))

    # Pick the result with the lowest true_prob for the target side.
    if target_side == 0:
        results.sort(key=lambda r: r[0])
    else:
        results.sort(key=lambda r: r[1])

    return results[0]


def devig_pair(
    odds_a: int, odds_b: int, method: str = "multiplicative"
) -> tuple[float, float]:
    """Devig a two-way market using the specified method.

    Args:
        odds_a: American odds for side A.
        odds_b: American odds for side B.
        method: One of "multiplicative", "additive", "power", "shin".

    Returns:
        (true_prob_a, true_prob_b) summing to ~1.0.
    """
    imp_a = american_to_implied_prob(odds_a)
    imp_b = american_to_implied_prob(odds_b)
    fn = _DEVIG_METHODS.get(method, devig_multiplicative)
    return fn(imp_a, imp_b)


# ---------------------------------------------------------------------------
# Hierarchical source selection
# ---------------------------------------------------------------------------

# Book classification for source hierarchy.
# Order matters — first match wins within each tier.
_PINNACLE_KEYS = {"pinnacle"}
_EXCHANGE_KEYS = {"novig", "betfair_ex_uk", "betfair_ex_eu", "smarkets", "matchbook"}
_SHARP_KEYS = {"pinnacle", "circa", "betonlineag", "bovada", "lowvig"}

# Weights for weighted average (when doing sharp consensus).
_SHARP_WEIGHTS: dict[str, float] = {
    "pinnacle": 1.0,
    "circa": 0.75,
    "betonlineag": 0.8,
    "bovada": 0.7,
    "lowvig": 0.7,
    "novig": 0.9,
    "betfair_ex_uk": 0.9,
    "betfair_ex_eu": 0.9,
    "smarkets": 0.85,
    "matchbook": 0.85,
}


@dataclass
class BookOdds:
    """Odds from a single bookmaker for a two-outcome market."""
    key: str
    odds_a: int
    odds_b: int
    weight: float = 0.5


def _weighted_devig(
    book_odds_list: list[BookOdds], method: str = "multiplicative"
) -> tuple[float, float]:
    """Compute weighted average of devigged probabilities from multiple books.

    Each book is devigged individually, then results are combined using weights.
    """
    if not book_odds_list:
        return 0.5, 0.5

    total_weight = sum(bo.weight for bo in book_odds_list)
    if total_weight <= 0:
        total_weight = 1.0

    sum_a = 0.0
    sum_b = 0.0
    for bo in book_odds_list:
        pa, pb = devig_pair(bo.odds_a, bo.odds_b, method)
        w = bo.weight / total_weight
        sum_a += pa * w
        sum_b += pb * w

    # Renormalize.
    s = sum_a + sum_b
    if s <= 0:
        return 0.5, 0.5
    return sum_a / s, sum_b / s


def select_devig_source(
    available_books: dict[str, tuple[int, int]],
) -> tuple[list[BookOdds], str, Confidence]:
    """Select the best devig source from available bookmakers.

    Hierarchy:
      1. Pinnacle → HIGH confidence
      2. Exchange consensus → MEDIUM
      3. Sharp book weighted average → LOW
      4. Market average → CAUTION

    Args:
        available_books: {book_key: (odds_a, odds_b)} for all books in a market.

    Returns:
        (selected_books, source_label, confidence)
    """
    # 1. Pinnacle
    for key in _PINNACLE_KEYS:
        if key in available_books:
            odds_a, odds_b = available_books[key]
            return (
                [BookOdds(key, odds_a, odds_b, _SHARP_WEIGHTS.get(key, 1.0))],
                key,
                "HIGH",
            )

    # 2. Exchange consensus
    exchange_books = []
    for key in _EXCHANGE_KEYS:
        if key in available_books:
            odds_a, odds_b = available_books[key]
            exchange_books.append(
                BookOdds(key, odds_a, odds_b, _SHARP_WEIGHTS.get(key, 0.85))
            )
    if exchange_books:
        source = "exchange:" + ",".join(bo.key for bo in exchange_books)
        return exchange_books, source, "MEDIUM"

    # 3. Sharp book weighted average
    sharp_books = []
    for key in _SHARP_KEYS:
        if key in available_books:
            odds_a, odds_b = available_books[key]
            sharp_books.append(
                BookOdds(key, odds_a, odds_b, _SHARP_WEIGHTS.get(key, 0.7))
            )
    if sharp_books:
        source = "sharp:" + ",".join(bo.key for bo in sharp_books)
        return sharp_books, source, "LOW"

    # 4. Market average — all books
    all_books = []
    for key, (odds_a, odds_b) in available_books.items():
        all_books.append(BookOdds(key, odds_a, odds_b, 0.3))
    if all_books:
        source = f"market_avg:{len(all_books)}_books"
        return all_books, source, "CAUTION"

    return [], "none", "CAUTION"


def devig_market(
    available_books: dict[str, tuple[int, int]],
    method: str = "multiplicative",
) -> DevigResult | None:
    """Devig a two-way market using hierarchical source selection.

    This is the main entry point for devigging. It:
    1. Selects the best available source (Pinnacle → exchanges → sharps → market)
    2. Devigs using the specified method
    3. Returns a DevigResult with probabilities, method, source, and confidence

    Args:
        available_books: {book_key: (odds_a, odds_b)} for all books.
        method: Devig method to use (default: multiplicative).

    Returns:
        DevigResult or None if no books available.
    """
    selected, source, confidence = select_devig_source(available_books)
    if not selected:
        return None

    if len(selected) == 1:
        # Single source — devig directly.
        bo = selected[0]
        true_a, true_b = devig_pair(bo.odds_a, bo.odds_b, method)
        imp_a = american_to_implied_prob(bo.odds_a)
        imp_b = american_to_implied_prob(bo.odds_b)
        overround = imp_a + imp_b
    else:
        # Multiple sources — weighted average.
        true_a, true_b = _weighted_devig(selected, method)
        # Compute average overround across sources.
        overrounds = []
        for bo in selected:
            ia = american_to_implied_prob(bo.odds_a)
            ib = american_to_implied_prob(bo.odds_b)
            overrounds.append(ia + ib)
        overround = sum(overrounds) / len(overrounds)

    return DevigResult(
        true_prob_a=round(true_a, 6),
        true_prob_b=round(true_b, 6),
        method=method,
        source=source,
        confidence=confidence,
        overround=round(overround, 4),
    )
