"""Exhaustive tests for the Kelly Criterion module.

Tests verify:
  - Full Kelly formula correctness
  - Quarter Kelly = full * 0.25
  - Units = quarter Kelly * 100
  - No edge → 0 units
  - No caps on output
  - Edge cases (extreme odds, boundary probabilities)
  - Consistency with hand-calculated examples
  - kelly_from_ev roundtrip
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "shared"))

import pytest

from models.kelly import kelly_full, kelly_fraction, kelly_units, kelly_from_ev
from models.ev_calculator import american_to_decimal


# ---------------------------------------------------------------------------
# Test 1: Hand-calculated examples from the user spec
# ---------------------------------------------------------------------------

class TestHandCalculatedExamples:
    """User provided 5 verification examples. Each must match."""

    def test_example_1_standard_line(self) -> None:
        """Standard -110 line, 55% true prob.
        b = 1.909 - 1 = 0.909
        full_kelly = (0.909*0.55 - 0.45) / 0.909 = 0.055
        quarter = 0.055 * 0.25 = 0.01375
        units = 0.01375 * 100 = 1.375u → ~1.37u
        """
        units = kelly_units(0.55, -110)
        assert abs(units - 1.37) < 0.1, f"Expected ~1.37u, got {units:.2f}u"

    def test_example_2_moderate_favorite(self) -> None:
        """Moderate favorite -150, 65% true prob.
        b = 1.667 - 1 = 0.667
        full_kelly = (0.667*0.65 - 0.35) / 0.667 = 0.125
        quarter = 0.125 * 0.25 = 0.03125
        units = 3.125u → ~3.13u
        """
        units = kelly_units(0.65, -150)
        assert abs(units - 3.13) < 0.2, f"Expected ~3.13u, got {units:.2f}u"

    def test_example_3_underdog(self) -> None:
        """Underdog +200, 40% true prob.
        b = 3.0 - 1 = 2.0
        full_kelly = (2.0*0.40 - 0.60) / 2.0 = 0.10
        quarter = 0.10 * 0.25 = 0.025
        units = 2.5u
        """
        units = kelly_units(0.40, 200)
        assert abs(units - 2.5) < 0.1, f"Expected ~2.5u, got {units:.2f}u"

    def test_example_4_big_underdog(self) -> None:
        """Big underdog +440, 19.6% true prob (from Drake at +440 example).
        b = 5.40 - 1 = 4.40
        full_kelly = (4.40*0.196 - 0.804) / 4.40 = 0.01345...
        quarter = 0.01345 * 0.25 = 0.003363
        units = 0.3363 → ~0.34u
        """
        units = kelly_units(0.196, 440)
        # Small edge = small bet. Should be well under 1u.
        assert units < 1.0, f"Expected <1u for small edge, got {units:.2f}u"
        assert units > 0.0, f"Expected positive units, got {units:.2f}u"

    def test_example_5_no_edge(self) -> None:
        """No edge: true prob below breakeven.
        -110 breakeven = 52.38%. If true_prob = 50%, no edge.
        """
        units = kelly_units(0.50, -110)
        assert units == 0.0, f"Expected 0u for no edge, got {units:.2f}u"


# ---------------------------------------------------------------------------
# Test 2: Formula relationships
# ---------------------------------------------------------------------------

class TestFormulaRelationships:
    """Verify that kelly_full, kelly_fraction, kelly_units are consistent."""

    @pytest.mark.parametrize("prob,odds", [
        (0.55, -110), (0.65, -150), (0.40, 200), (0.75, -250),
    ])
    def test_fraction_is_full_times_025(self, prob: float, odds: int) -> None:
        full = kelly_full(prob, odds)
        frac = kelly_fraction(prob, odds)
        assert abs(frac - full * 0.25) < 1e-10

    @pytest.mark.parametrize("prob,odds", [
        (0.55, -110), (0.65, -150), (0.40, 200), (0.75, -250),
    ])
    def test_units_is_fraction_times_100(self, prob: float, odds: int) -> None:
        frac = kelly_fraction(prob, odds)
        units = kelly_units(prob, odds)
        assert abs(units - frac * 100) < 1e-8

    @pytest.mark.parametrize("prob,odds", [
        (0.55, -110), (0.65, -150), (0.40, 200), (0.75, -250),
    ])
    def test_units_is_full_times_025_times_100(self, prob: float, odds: int) -> None:
        full = kelly_full(prob, odds)
        units = kelly_units(prob, odds)
        assert abs(units - full * 0.25 * 100) < 1e-8


# ---------------------------------------------------------------------------
# Test 3: No edge → 0
# ---------------------------------------------------------------------------

class TestNoEdge:
    """When true probability is at or below breakeven, Kelly = 0."""

    def test_exact_breakeven_minus_110(self) -> None:
        """Breakeven at -110 is 52.38%."""
        breakeven = american_to_decimal(-110)
        be_prob = 1.0 / breakeven
        units = kelly_units(be_prob, -110)
        assert abs(units) < 0.01, f"Expected ~0 at breakeven, got {units}"

    def test_below_breakeven(self) -> None:
        units = kelly_units(0.45, -110)
        assert units == 0.0

    def test_coin_flip_even_money(self) -> None:
        """50% at +100 is breakeven."""
        units = kelly_units(0.50, 100)
        assert abs(units) < 0.01

    def test_zero_prob(self) -> None:
        units = kelly_units(0.0, -110)
        assert units == 0.0

    def test_negative_prob(self) -> None:
        units = kelly_units(-0.5, -110)
        assert units == 0.0

    def test_100_pct_prob(self) -> None:
        """Edge case: probability = 1.0 (degenerate)."""
        units = kelly_units(1.0, -110)
        assert units == 0.0


# ---------------------------------------------------------------------------
# Test 4: No caps
# ---------------------------------------------------------------------------

class TestNoCaps:
    """Verify there is NO maximum cap on Kelly output."""

    def test_huge_edge_produces_large_units(self) -> None:
        """95% true prob at +300 → massive edge, should be uncapped."""
        units = kelly_units(0.95, 300)
        assert units > 10.0, f"Expected >10u for massive edge, got {units:.2f}u"

    def test_no_3u_cap(self) -> None:
        """The old bug: everything capped at 3.0u."""
        units = kelly_units(0.70, -110)
        assert units > 3.0, f"Expected >3u (no cap), got {units:.2f}u"


# ---------------------------------------------------------------------------
# Test 5: Custom fractions
# ---------------------------------------------------------------------------

class TestCustomFractions:
    def test_half_kelly(self) -> None:
        full = kelly_full(0.55, -110)
        units = kelly_units(0.55, -110, fraction=0.50)
        assert abs(units - full * 0.50 * 100) < 1e-8

    def test_tenth_kelly(self) -> None:
        full = kelly_full(0.55, -110)
        units = kelly_units(0.55, -110, fraction=0.10)
        assert abs(units - full * 0.10 * 100) < 1e-8

    def test_full_kelly(self) -> None:
        full = kelly_full(0.55, -110)
        units = kelly_units(0.55, -110, fraction=1.0)
        assert abs(units - full * 100) < 1e-8


# ---------------------------------------------------------------------------
# Test 6: Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_extreme_favorite_minus_5000(self) -> None:
        units = kelly_units(0.99, -5000)
        assert units >= 0.0

    def test_extreme_underdog_plus_5000(self) -> None:
        units = kelly_units(0.03, 5000)
        assert units >= 0.0

    def test_very_small_edge(self) -> None:
        """Just barely above breakeven."""
        units = kelly_units(0.5239, -110)
        assert units > 0.0
        assert units < 0.5  # very small edge

    def test_pick_em(self) -> None:
        """Even money (+100) with 55% true prob."""
        units = kelly_units(0.55, 100)
        assert units > 0.0


# ---------------------------------------------------------------------------
# Test 7: kelly_from_ev roundtrip
# ---------------------------------------------------------------------------

class TestKellyFromEV:
    def test_from_ev_positive(self) -> None:
        """5% EV at -110 should give positive units."""
        units = kelly_from_ev(5.0, -110)
        assert units > 0.0

    def test_from_ev_zero(self) -> None:
        """0% EV → 0 units."""
        units = kelly_from_ev(0.0, -110)
        assert abs(units) < 0.01

    def test_from_ev_negative(self) -> None:
        """Negative EV → 0 units."""
        units = kelly_from_ev(-5.0, -110)
        assert units == 0.0

    def test_roundtrip_consistency(self) -> None:
        """kelly_from_ev should agree with kelly_units for same scenario."""
        # true_prob=0.55, odds=-110 → EV = (0.55 * 1.909 - 1) * 100 = 5.0%
        from models.ev_calculator import calculate_ev
        true_prob = 0.55
        odds = -110
        ev_pct = calculate_ev(odds, true_prob)
        units_from_prob = kelly_units(true_prob, odds)
        units_from_ev = kelly_from_ev(ev_pct, odds)
        assert abs(units_from_prob - units_from_ev) < 0.1, \
            f"Mismatch: from_prob={units_from_prob:.4f}, from_ev={units_from_ev:.4f}"


# ---------------------------------------------------------------------------
# Test 8: Parametric consistency
# ---------------------------------------------------------------------------

class TestParametricConsistency:
    """As edge increases, Kelly units should increase monotonically."""

    @pytest.mark.parametrize("odds", [-110, -150, 200, 300])
    def test_monotonic_with_prob(self, odds: int) -> None:
        """Higher true prob (above breakeven) → more units."""
        probs = [0.51, 0.55, 0.60, 0.65, 0.70, 0.80, 0.90]
        prev = -1.0
        for p in probs:
            u = kelly_units(p, odds)
            assert u >= prev, f"Not monotonic at p={p}: {u} < {prev}"
            prev = u
