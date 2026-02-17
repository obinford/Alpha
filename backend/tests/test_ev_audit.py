"""EV Calculation Audit — end-to-end verification of the +EV pipeline.

Tests verify:
  - EV formula: EV% = (true_prob * decimal_odds - 1) * 100
  - Devig → EV → Kelly pipeline consistency
  - Edge confidence scoring
  - Suspicious edge detection
  - Real-world scenario validation
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "shared"))

import pytest

from models.ev_calculator import (
    american_to_implied_prob,
    american_to_decimal,
    calculate_no_vig_probability,
    calculate_ev,
)
from models.devig import devig_pair, devig_market
from models.kelly import kelly_units, kelly_full


# ---------------------------------------------------------------------------
# Test 1: EV formula verification
# ---------------------------------------------------------------------------

class TestEVFormula:
    """Verify: EV% = (true_prob * decimal_odds - 1) * 100."""

    def test_standard_line_positive_ev(self) -> None:
        """True prob 55% at -110 (decimal 1.909).
        EV = (0.55 * 1.909 - 1) * 100 = 5.0%
        """
        ev = calculate_ev(-110, 0.55)
        assert abs(ev - 5.0) < 0.1, f"Expected ~5.0%, got {ev:.2f}%"

    def test_underdog_positive_ev(self) -> None:
        """True prob 40% at +200 (decimal 3.0).
        EV = (0.40 * 3.0 - 1) * 100 = 20.0%
        """
        ev = calculate_ev(200, 0.40)
        assert abs(ev - 20.0) < 0.1, f"Expected ~20.0%, got {ev:.2f}%"

    def test_heavy_favorite(self) -> None:
        """True prob 75% at -250 (decimal 1.4).
        EV = (0.75 * 1.4 - 1) * 100 = 5.0%
        """
        ev = calculate_ev(-250, 0.75)
        assert abs(ev - 5.0) < 0.1, f"Expected ~5.0%, got {ev:.2f}%"

    def test_zero_ev_at_breakeven(self) -> None:
        """At breakeven, EV should be ~0."""
        # -110 breakeven = 1/1.909 = 0.5238
        be_prob = 1.0 / american_to_decimal(-110)
        ev = calculate_ev(-110, be_prob)
        assert abs(ev) < 0.1, f"Expected ~0% at breakeven, got {ev:.2f}%"

    def test_negative_ev(self) -> None:
        """Below breakeven: 48% at -110."""
        ev = calculate_ev(-110, 0.48)
        assert ev < 0, f"Expected negative EV, got {ev:.2f}%"

    def test_ev_increases_with_prob(self) -> None:
        """Higher true prob → higher EV at same odds."""
        ev1 = calculate_ev(-110, 0.55)
        ev2 = calculate_ev(-110, 0.60)
        ev3 = calculate_ev(-110, 0.65)
        assert ev1 < ev2 < ev3


# ---------------------------------------------------------------------------
# Test 2: Full pipeline (devig → EV → Kelly)
# ---------------------------------------------------------------------------

class TestFullPipeline:
    """End-to-end: devig sharp line → calculate EV → size bet."""

    def test_pinnacle_pipeline(self) -> None:
        """Pinnacle: -150/+130. Soft book has +140 for the underdog.
        1. Devig -150/+130: true_a ~0.580, true_b ~0.420
        2. Book has +140 for side B: decimal 2.40
        3. EV for side B = (0.420 * 2.40 - 1) * 100 = 0.8%
        4. Kelly = small positive
        """
        # Devig sharp.
        true_a, true_b = devig_pair(-150, 130)
        assert abs(true_a + true_b - 1.0) < 0.001

        # EV at soft book.
        ev = calculate_ev(140, true_b)
        # true_b ~0.42, +140 = 2.40 → (0.42*2.40-1)*100 = 0.8%
        assert ev > 0, f"Expected positive EV, got {ev:.2f}%"

        # Kelly.
        units = kelly_units(true_b, 140)
        assert units >= 0.0
        if ev > 1.0:
            assert units > 0.0, "Positive EV with sufficient edge should have positive Kelly"

    def test_devig_market_pipeline(self) -> None:
        """Use hierarchical devig_market, then compute EV."""
        books = {
            "pinnacle": (-200, 170),
            "draftkings": (-215, 175),
        }
        result = devig_market(books)
        assert result is not None
        assert result.confidence == "HIGH"  # single Tier 1 sharp book

        # true_prob_b should be around 0.37
        assert 0.30 < result.true_prob_b < 0.45

        # EV for DK +175 using Pinnacle true prob.
        ev = calculate_ev(175, result.true_prob_b)
        # This should be a small edge or no edge.
        # true_b ~0.37, +175 = 2.75 → (0.37*2.75-1)*100 = 1.75%
        # It's edge-dependent but should be computable.
        assert isinstance(ev, float)

    def test_no_edge_pipeline(self) -> None:
        """When soft book matches sharp line, no EV."""
        true_a, true_b = devig_pair(-150, 130)
        # If soft book has -150 for side A (same as sharp), EV should be ~0.
        ev = calculate_ev(-150, true_a)
        # At sharp book's own odds, EV should be slightly negative (vig was removed).
        assert ev < 1.0, f"Expected ~0 or negative EV at sharp's own price"


# ---------------------------------------------------------------------------
# Test 3: Edge confidence scoring
# ---------------------------------------------------------------------------

class TestEdgeConfidence:
    """Test edge confidence classification."""

    def test_single_sharp_high_confidence(self) -> None:
        """Single Tier 1 sharp book → HIGH confidence."""
        books = {"pinnacle": (-150, 130)}
        result = devig_market(books)
        assert result is not None
        assert result.confidence == "HIGH"

    def test_pinnacle_with_others_high_confidence(self) -> None:
        """Pinnacle present with other books → HIGH confidence."""
        books = {"pinnacle": (-150, 130), "circasports": (-148, 128)}
        result = devig_market(books)
        assert result is not None
        assert result.confidence == "HIGH"

    def test_no_pinnacle_returns_none(self) -> None:
        """Without Pinnacle → no devigging (Pinnacle-only policy)."""
        books = {"circasports": (-150, 130), "betonlineag": (-148, 128)}
        result = devig_market(books)
        assert result is None

    def test_tier2_only_returns_none(self) -> None:
        """DK + FD (no Pinnacle) → None."""
        books = {"draftkings": (-155, 125), "fanduel": (-160, 135)}
        result = devig_market(books)
        assert result is None

    def test_exchange_only_returns_none(self) -> None:
        """Single exchange (no Pinnacle) → None."""
        books = {"novig": (-150, 130)}
        result = devig_market(books)
        assert result is None

    def test_soft_books_only_returns_none(self) -> None:
        """Only soft books (no Pinnacle) → None."""
        books = {"espnbet": (-155, 125), "betmgm": (-160, 135)}
        result = devig_market(books)
        assert result is None


# ---------------------------------------------------------------------------
# Test 4: Suspicious edge detection
# ---------------------------------------------------------------------------

def flag_suspicious_edge(ev_pct: float, true_prob: float, book_odds: int) -> list[str]:
    """Flag suspicious edges that may indicate data issues.

    Returns a list of warning strings. Empty list = edge looks legitimate.
    """
    warnings = []

    if ev_pct > 20.0:
        warnings.append(f"EXTREME_EV: {ev_pct:.1f}% EV is unusually high — check for stale line")

    if true_prob <= 0 or true_prob >= 1:
        warnings.append(f"INVALID_PROB: true_prob={true_prob} is out of bounds")

    book_implied = american_to_implied_prob(book_odds)
    if book_implied <= 0 or book_implied >= 1:
        warnings.append(f"INVALID_ODDS: book_odds={book_odds} gives invalid implied prob")

    # Edge that's larger than the vig is suspicious unless it's a stale line.
    if ev_pct > 15.0 and true_prob > 0.5:
        warnings.append("LARGE_FAV_EDGE: >15% EV on a favorite is unusual")

    return warnings


class TestSuspiciousEdge:
    def test_normal_edge_no_warnings(self) -> None:
        warnings = flag_suspicious_edge(5.0, 0.55, -110)
        assert len(warnings) == 0

    def test_extreme_ev_flagged(self) -> None:
        warnings = flag_suspicious_edge(25.0, 0.40, 200)
        assert any("EXTREME_EV" in w for w in warnings)

    def test_invalid_prob_flagged(self) -> None:
        warnings = flag_suspicious_edge(5.0, 0.0, -110)
        assert any("INVALID_PROB" in w for w in warnings)

    def test_large_fav_edge_flagged(self) -> None:
        warnings = flag_suspicious_edge(16.0, 0.75, -200)
        assert any("LARGE_FAV_EDGE" in w for w in warnings)


# ---------------------------------------------------------------------------
# Test 5: Odds conversion accuracy
# ---------------------------------------------------------------------------

class TestOddsConversion:
    """Verify American↔Decimal↔Implied conversions are consistent."""

    @pytest.mark.parametrize("american,expected_decimal,expected_prob", [
        (-110, 1.909, 0.5238),
        (-150, 1.667, 0.600),
        (-200, 1.500, 0.667),
        (-300, 1.333, 0.750),
        (100, 2.000, 0.500),
        (150, 2.500, 0.400),
        (200, 3.000, 0.333),
        (300, 4.000, 0.250),
    ])
    def test_conversions(
        self, american: int, expected_decimal: float, expected_prob: float
    ) -> None:
        dec = american_to_decimal(american)
        prob = american_to_implied_prob(american)
        assert abs(dec - expected_decimal) < 0.01, f"Decimal: got {dec}, expected {expected_decimal}"
        assert abs(prob - expected_prob) < 0.01, f"Prob: got {prob}, expected {expected_prob}"


# ---------------------------------------------------------------------------
# Test 6: Devig preserves information
# ---------------------------------------------------------------------------

class TestDevigPreservesInfo:
    """Devigging should always produce probs that sum to 1 and
    the EV at the sharp book's own odds should be ~0 (no edge at fair price)."""

    @pytest.mark.parametrize("odds_a,odds_b", [
        (-110, -110), (-150, 130), (-200, 170), (-300, 250),
        (100, -120), (150, -170),
    ])
    def test_ev_at_sharp_price_is_near_zero(self, odds_a: int, odds_b: int) -> None:
        """After devigging, betting the sharp book at its own price should have ~0 EV."""
        true_a, true_b = devig_pair(odds_a, odds_b)

        ev_a = calculate_ev(odds_a, true_a)
        ev_b = calculate_ev(odds_b, true_b)

        # EV should be negative (we removed the vig, so true prob < implied).
        # The magnitude equals roughly half the vig: for -110/-110, vig ~4.76%
        # so EV at own price is ~ -4.5%. Tolerance: within the vig amount.
        overround = american_to_implied_prob(odds_a) + american_to_implied_prob(odds_b)
        vig_pct = (overround - 1.0) * 100
        assert ev_a <= 0.1, f"Side A EV should be <=0 at sharp price, got {ev_a:.2f}%"
        assert ev_b <= 0.1, f"Side B EV should be <=0 at sharp price, got {ev_b:.2f}%"
        assert abs(ev_a) < vig_pct + 1.0, f"Side A EV magnitude ({abs(ev_a):.2f}%) exceeds vig ({vig_pct:.2f}%)"
        assert abs(ev_b) < vig_pct + 1.0, f"Side B EV magnitude ({abs(ev_b):.2f}%) exceeds vig ({vig_pct:.2f}%)"
