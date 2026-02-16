"""Exhaustive tests for the devig engine.

Tests cover:
  - All four devig methods (multiplicative, additive, power, shin)
  - Balanced and asymmetric markets
  - Source hierarchy selection
  - Weighted consensus
  - Edge cases (extreme odds, pick-em, zero vig)
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "shared"))

import pytest

from models.devig import (
    devig_multiplicative,
    devig_additive,
    devig_power,
    devig_shin,
    devig_pair,
    devig_best,
    devig_market,
    select_devig_source,
    BookOdds,
    DevigResult,
)
from models.ev_calculator import american_to_implied_prob


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def assert_sums_to_one(a: float, b: float, tol: float = 0.001) -> None:
    assert abs(a + b - 1.0) < tol, f"{a} + {b} = {a + b}, expected ~1.0"


def assert_between(val: float, lo: float, hi: float) -> None:
    assert lo <= val <= hi, f"{val} not in [{lo}, {hi}]"


# ---------------------------------------------------------------------------
# Test 1: Balanced market (-110 / -110)
# ---------------------------------------------------------------------------

class TestBalancedMarket:
    """All methods should return ~50/50 for -110/-110."""

    def test_multiplicative(self) -> None:
        imp_a = american_to_implied_prob(-110)
        imp_b = american_to_implied_prob(-110)
        a, b = devig_multiplicative(imp_a, imp_b)
        assert abs(a - 0.5) < 0.001
        assert abs(b - 0.5) < 0.001
        assert_sums_to_one(a, b)

    def test_additive(self) -> None:
        imp_a = american_to_implied_prob(-110)
        imp_b = american_to_implied_prob(-110)
        a, b = devig_additive(imp_a, imp_b)
        assert abs(a - 0.5) < 0.001
        assert abs(b - 0.5) < 0.001
        assert_sums_to_one(a, b)

    def test_power(self) -> None:
        imp_a = american_to_implied_prob(-110)
        imp_b = american_to_implied_prob(-110)
        a, b = devig_power(imp_a, imp_b)
        assert abs(a - 0.5) < 0.001
        assert abs(b - 0.5) < 0.001
        assert_sums_to_one(a, b)

    def test_shin(self) -> None:
        imp_a = american_to_implied_prob(-110)
        imp_b = american_to_implied_prob(-110)
        a, b = devig_shin(imp_a, imp_b)
        assert abs(a - 0.5) < 0.001
        assert abs(b - 0.5) < 0.001
        assert_sums_to_one(a, b)


# ---------------------------------------------------------------------------
# Test 2: Asymmetric market (-300 / +250)
# ---------------------------------------------------------------------------

class TestAsymmetricMarket:
    """Heavy favorite — methods should diverge but all sum to 1."""

    @pytest.fixture()
    def implied(self) -> tuple[float, float]:
        return american_to_implied_prob(-300), american_to_implied_prob(250)

    def test_multiplicative(self, implied: tuple[float, float]) -> None:
        a, b = devig_multiplicative(*implied)
        assert_sums_to_one(a, b)
        assert_between(a, 0.70, 0.76)  # favorite
        assert_between(b, 0.24, 0.30)  # underdog

    def test_additive(self, implied: tuple[float, float]) -> None:
        a, b = devig_additive(*implied)
        assert_sums_to_one(a, b)
        assert_between(a, 0.70, 0.76)

    def test_power(self, implied: tuple[float, float]) -> None:
        a, b = devig_power(*implied)
        assert_sums_to_one(a, b)
        assert_between(a, 0.70, 0.76)

    def test_shin(self, implied: tuple[float, float]) -> None:
        a, b = devig_shin(*implied)
        assert_sums_to_one(a, b)
        assert_between(a, 0.70, 0.76)


# ---------------------------------------------------------------------------
# Test 3: devig_pair with method selection
# ---------------------------------------------------------------------------

class TestDevigPair:
    def test_default_is_multiplicative(self) -> None:
        a1, b1 = devig_pair(-150, 130)
        imp_a = american_to_implied_prob(-150)
        imp_b = american_to_implied_prob(130)
        a2, b2 = devig_multiplicative(imp_a, imp_b)
        assert abs(a1 - a2) < 0.0001
        assert abs(b1 - b2) < 0.0001

    def test_additive_method(self) -> None:
        a, b = devig_pair(-150, 130, method="additive")
        assert_sums_to_one(a, b)

    def test_unknown_method_falls_back_to_multiplicative(self) -> None:
        a1, b1 = devig_pair(-150, 130, method="nonexistent")
        a2, b2 = devig_pair(-150, 130, method="multiplicative")
        assert abs(a1 - a2) < 0.0001


# ---------------------------------------------------------------------------
# Test 4: Conservative devig (devig_best)
# ---------------------------------------------------------------------------

class TestDevigBest:
    def test_conservative_for_favorite(self) -> None:
        """Most conservative = lowest prob for the target side."""
        pa, pb, method = devig_best(-150, 130, target_side=0)
        assert_sums_to_one(pa, pb)
        # Multiplicative typically gives the lowest prob for the favorite.
        assert method == "multiplicative"

    def test_conservative_for_underdog(self) -> None:
        pa, pb, method = devig_best(-150, 130, target_side=1)
        assert_sums_to_one(pa, pb)
        # Power/shin typically give the lowest prob for the underdog.
        assert method in ("power", "shin", "additive")


# ---------------------------------------------------------------------------
# Test 5: Source hierarchy
# ---------------------------------------------------------------------------

class TestSourceHierarchy:
    def test_three_sharps_avg(self) -> None:
        """All three sharp books → sharp_avg (3), HIGH confidence."""
        books = {
            "pinnacle": (-150, 130),
            "circa": (-152, 128),
            "bookmaker": (-148, 126),
            "draftkings": (-155, 125),
        }
        selected, source, confidence = select_devig_source(books)
        assert source == "sharp_avg (3)"
        assert confidence == "HIGH"
        assert len(selected) == 3

    def test_two_sharps_avg(self) -> None:
        """Two sharp books → sharp_avg (2), HIGH confidence."""
        books = {
            "pinnacle": (-150, 130),
            "circa": (-152, 128),
            "draftkings": (-155, 125),
        }
        selected, source, confidence = select_devig_source(books)
        assert source == "sharp_avg (2)"
        assert confidence == "HIGH"
        assert len(selected) == 2

    def test_single_sharp_pinnacle(self) -> None:
        """Only Pinnacle → source='pinnacle', MEDIUM confidence."""
        books = {
            "pinnacle": (-150, 130),
            "novig": (-152, 128),
            "draftkings": (-155, 125),
        }
        selected, source, confidence = select_devig_source(books)
        assert source == "pinnacle"
        assert confidence == "MEDIUM"
        assert len(selected) == 1

    def test_single_sharp_circa(self) -> None:
        """Only Circa → source='circa', MEDIUM confidence."""
        books = {
            "circa": (-153, 129),
            "novig": (-152, 128),
            "draftkings": (-155, 125),
        }
        selected, source, confidence = select_devig_source(books)
        assert source == "circa"
        assert confidence == "MEDIUM"
        assert len(selected) == 1

    def test_exchanges_when_no_sharps_3_books(self) -> None:
        """3+ exchange books → exchange consensus, LOW confidence."""
        books = {
            "novig": (-152, 128),
            "betfair_ex_eu": (-148, 126),
            "smarkets": (-150, 128),
            "draftkings": (-155, 125),
        }
        selected, source, confidence = select_devig_source(books)
        assert confidence == "LOW"
        assert source.startswith("exchange:")
        assert len(selected) >= 3

    def test_exchanges_below_minimum_falls_through(self) -> None:
        """Fewer than 3 exchange books → skip to market_avg."""
        books = {
            "novig": (-152, 128),
            "betfair_ex_eu": (-148, 126),
            "draftkings": (-155, 125),
        }
        selected, source, confidence = select_devig_source(books)
        assert confidence == "LOW"
        assert source.startswith("market_avg:")

    def test_market_avg_last_resort(self) -> None:
        books = {
            "draftkings": (-155, 125),
            "fanduel": (-160, 135),
            "espnbet": (-158, 130),
        }
        selected, source, confidence = select_devig_source(books)
        assert confidence == "LOW"
        assert source.startswith("market_avg:")

    def test_empty_books(self) -> None:
        selected, source, confidence = select_devig_source({})
        assert selected == []
        assert confidence == "LOW"


# ---------------------------------------------------------------------------
# Test 6: Full devig_market integration
# ---------------------------------------------------------------------------

class TestDevigMarket:
    def test_sharp_avg_result(self) -> None:
        books = {
            "pinnacle": (-150, 130),
            "circa": (-152, 128),
            "draftkings": (-155, 125),
        }
        result = devig_market(books)
        assert result is not None
        assert result.confidence == "HIGH"
        assert result.source == "sharp_avg (2)"
        assert_sums_to_one(result.true_prob_a, result.true_prob_b)
        assert result.overround > 1.0

    def test_single_sharp_result(self) -> None:
        books = {"pinnacle": (-150, 130), "draftkings": (-155, 125)}
        result = devig_market(books)
        assert result is not None
        assert result.confidence == "MEDIUM"
        assert result.source == "pinnacle"
        assert_sums_to_one(result.true_prob_a, result.true_prob_b)
        assert result.overround > 1.0

    def test_market_avg_result(self) -> None:
        books = {
            "draftkings": (-155, 125),
            "fanduel": (-160, 135),
        }
        result = devig_market(books)
        assert result is not None
        assert result.confidence == "LOW"
        assert_sums_to_one(result.true_prob_a, result.true_prob_b)

    def test_empty_returns_none(self) -> None:
        result = devig_market({})
        assert result is None


# ---------------------------------------------------------------------------
# Test 7: Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_pick_em_100_minus_100(self) -> None:
        """Even odds with no vig (theoretical)."""
        a, b = devig_pair(100, -100)
        assert_sums_to_one(a, b)

    def test_extreme_favorite_minus_1000(self) -> None:
        a, b = devig_pair(-1000, 700)
        assert_sums_to_one(a, b)
        assert a > 0.85

    def test_extreme_underdog_plus_2000(self) -> None:
        a, b = devig_pair(-2500, 2000)
        assert_sums_to_one(a, b)
        assert b < 0.10

    def test_zero_vig_market(self) -> None:
        """When implied probs already sum to 1.0 (no vig)."""
        # -200 = 0.6667, +200 = 0.3333, sum = 1.0
        a, b = devig_pair(-200, 200)
        assert_sums_to_one(a, b)
        assert abs(a - 0.6667) < 0.01


# ---------------------------------------------------------------------------
# Test 8: Method consistency
# ---------------------------------------------------------------------------

class TestMethodConsistency:
    """All methods must always sum to 1 and preserve ordering."""

    @pytest.mark.parametrize("odds_a,odds_b", [
        (-110, -110),
        (-150, 130),
        (-300, 250),
        (-500, 400),
        (150, -170),
        (-200, 170),
    ])
    @pytest.mark.parametrize("method", [
        "multiplicative", "additive", "power", "shin",
    ])
    def test_sums_to_one(self, odds_a: int, odds_b: int, method: str) -> None:
        a, b = devig_pair(odds_a, odds_b, method)
        assert_sums_to_one(a, b)

    @pytest.mark.parametrize("odds_a,odds_b", [
        (-150, 130),
        (-300, 250),
        (150, -170),
    ])
    @pytest.mark.parametrize("method", [
        "multiplicative", "additive", "power", "shin",
    ])
    def test_preserves_favorite(self, odds_a: int, odds_b: int, method: str) -> None:
        """The side with higher implied prob should remain the favorite after devigging."""
        imp_a = american_to_implied_prob(odds_a)
        imp_b = american_to_implied_prob(odds_b)
        a, b = devig_pair(odds_a, odds_b, method)
        if imp_a > imp_b:
            assert a > b
        elif imp_b > imp_a:
            assert b > a
