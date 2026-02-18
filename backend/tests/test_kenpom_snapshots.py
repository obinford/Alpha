"""Tests for KenPom snapshot edge calculation and grading logic.

Verifies:
- Edge sign conventions are correct
- spread_edge = kp_spread + pin_spread (opposite sign conventions combined)
- Grading logic matches expected outcomes
- Edge cases: ties, pushes, zero edges
"""

import pytest


# ---------------------------------------------------------------------------
# Edge calculation tests
#
# kp_projected_spread: positive = home projects to win (margin convention)
# pinnacle_spread_home: negative = home favored (betting convention)
# spread_edge = kp_projected_spread + pinnacle_spread_home
#   (added, not subtracted, because conventions use OPPOSITE signs)
# ---------------------------------------------------------------------------

def test_spread_edge_positive_means_kp_favors_home():
    """spread_edge > 0 means KP sees more home advantage than Pinnacle.

    KP: home by 8 (kp_spread=+8), PIN: home -5.5 (pin_spread=-5.5)
    edge = 8 + (-5.5) = +2.5 — KP thinks home is 2.5 pts more favored.
    """
    kp_spread = 8.0
    pin_spread_home = -5.5
    edge = kp_spread + pin_spread_home
    assert edge == pytest.approx(2.5)
    assert edge > 0, "KP more bullish on home should yield positive edge"


def test_spread_edge_negative_means_kp_favors_away():
    """spread_edge < 0 means KP sees less home advantage than Pinnacle.

    KP: away by 3 (kp_spread=-3), PIN: home -1.5 (pin_spread=-1.5)
    edge = -3 + (-1.5) = -4.5 — KP thinks home is 4.5 pts less favored.
    """
    kp_spread = -3.0
    pin_spread_home = -1.5
    edge = kp_spread + pin_spread_home
    assert edge == pytest.approx(-4.5)
    assert edge < 0, "KP favoring away more should yield negative edge"


def test_spread_edge_near_zero_when_agree():
    """When KP and Pinnacle agree, edge should be near zero.

    KP: home by 6 (kp_spread=+6), PIN: home -5.5 (pin_spread=-5.5)
    edge = 6 + (-5.5) = +0.5 — minimal disagreement.
    """
    kp_spread = 6.0
    pin_spread_home = -5.5
    edge = kp_spread + pin_spread_home
    assert edge == pytest.approx(0.5)
    assert abs(edge) < 1.0, "When both agree home is favored ~6, edge should be small"


def test_spread_edge_home_dog_kp_agrees():
    """Both see home as underdog — small positive edge.

    KP: away by 2 (kp_spread=-2), PIN: home +3.5 (pin_spread=+3.5)
    edge = -2 + 3.5 = +1.5 — KP thinks home is slightly better than PIN does.
    """
    kp_spread = -2.0
    pin_spread_home = 3.5
    edge = kp_spread + pin_spread_home
    assert edge == pytest.approx(1.5)
    assert edge > 0


def test_total_edge_positive_means_kp_higher():
    """total_edge > 0 means KP projects higher scoring than Pinnacle."""
    kp_total = 157.0
    pin_total = 150.5
    edge = kp_total - pin_total
    assert edge == pytest.approx(6.5)
    assert edge > 0


def test_total_edge_negative_means_kp_lower():
    """total_edge < 0 means KP projects lower scoring than Pinnacle."""
    kp_total = 143.0
    pin_total = 148.5
    edge = kp_total - pin_total
    assert edge == pytest.approx(-5.5)
    assert edge < 0


def test_ml_edge_positive_means_kp_bullish_home():
    """ml_edge > 0 means KP more bullish on home than Pinnacle."""
    kp_wp = 0.75
    pin_ip = 0.65
    edge = kp_wp - pin_ip
    assert edge == pytest.approx(0.10)
    assert edge > 0


# ---------------------------------------------------------------------------
# Grading logic tests — mirrors grade_kenpom_snapshots() in kenpom_snapshots.py
# ---------------------------------------------------------------------------

def _grade_spread(spread_edge: float, actual_spread: float, pin_spread: float) -> bool | None:
    """Replicate corrected ATS grading logic from kenpom_snapshots.py.

    ATS margin = actual_spread + pin_spread.  Positive → home covers.
    """
    if spread_edge == 0:
        return None
    ats_margin = actual_spread + pin_spread
    if ats_margin == 0:
        return None  # push
    if spread_edge > 0:
        return ats_margin > 0
    return ats_margin < 0


def _grade_total(total_edge: float, actual_total: float, pin_total: float) -> bool | None:
    """Replicate grading logic from kenpom_snapshots.py."""
    if total_edge == 0:
        return None
    if actual_total == pin_total:
        return None  # push
    if total_edge > 0:
        return actual_total > pin_total
    return actual_total < pin_total


def _grade_ml(kp_wp: float, actual_spread: float) -> bool | None:
    """Replicate grading logic from kenpom_snapshots.py."""
    if kp_wp == 0.5:
        return None
    if actual_spread == 0:
        return None  # tie
    if kp_wp > 0.5:
        return actual_spread > 0  # home won
    return actual_spread < 0  # away won


def test_grading_full_example():
    """Full example: home covers, over hits, home wins.

    KP: Home 80, Away 72 (spread=8, total=152, home WP=75%)
    Pinnacle: Home -5.5, total 148.5, home implied 65%
    Edges: spread = 8 + (-5.5) = +2.5, total = +3.5, ml = +10%

    Actual: Home 78, Away 71 (actual_spread=7, actual_total=149)
    """
    kp_spread = 8.0
    pin_spread_home = -5.5
    spread_edge = kp_spread + pin_spread_home  # +2.5

    kp_total = 152.0
    pin_total = 148.5
    total_edge = kp_total - pin_total  # +3.5

    kp_wp = 0.75

    actual_home = 78
    actual_away = 71
    actual_spread = actual_home - actual_away  # 7
    actual_total = actual_home + actual_away  # 149

    assert spread_edge == pytest.approx(2.5)

    # Spread: edge > 0 (take home), ats_margin = 7 + (-5.5) = 1.5 > 0 → TRUE (home covers)
    assert _grade_spread(spread_edge, actual_spread, pin_spread_home) is True

    # Total: edge > 0 (take over), 149 > 148.5 → TRUE
    assert _grade_total(total_edge, actual_total, pin_total) is True

    # ML: kp_wp > 0.5, home won (spread > 0) → TRUE
    assert _grade_ml(kp_wp, actual_spread) is True


def test_grading_home_loses():
    """Test when the home team loses and away covers.

    KP: Home 70, Away 75 → kp_spread = -5
    PIN: Home -2.5 → pin_spread = -2.5
    Edge = -5 + (-2.5) = -7.5 (KP favors away much more)
    """
    kp_spread = -5.0
    pin_spread = -2.5
    spread_edge = kp_spread + pin_spread  # -7.5
    actual_spread = -6

    assert spread_edge == pytest.approx(-7.5)
    # edge < 0 → take away ATS
    # ats_margin = -6 + (-2.5) = -8.5 < 0 → away covered → TRUE
    assert _grade_spread(spread_edge, actual_spread, pin_spread) is True


def test_grading_spread_loss_home_fav():
    """Home fav -5.5, KP says take home, but home only wins by 3 → LOSS.

    KP spread = +8, PIN spread = -5.5
    spread_edge = 8 + (-5.5) = +2.5 (take home)
    Actual: home wins by 3 → ats_margin = 3 + (-5.5) = -2.5 < 0 → LOSS.
    """
    kp_spread = 8.0
    pin_spread = -5.5
    spread_edge = kp_spread + pin_spread  # +2.5
    actual_spread = 3

    assert spread_edge == pytest.approx(2.5)
    # Home is -5.5 favorite, wins by only 3. Doesn't cover.
    # ats_margin = 3 + (-5.5) = -2.5 < 0 → home didn't cover → False
    assert _grade_spread(spread_edge, actual_spread, pin_spread) is False


def test_grading_spread_home_dog_covers():
    """Home underdog +3.5, loses by 2 → covers the spread."""
    kp_spread = 2.0  # KP still thinks home is slightly better
    pin_spread = 3.5  # home is +3.5 underdog
    spread_edge = kp_spread + pin_spread  # +5.5

    actual_spread = -2  # home lost by 2

    assert spread_edge == pytest.approx(5.5)
    # ats_margin = -2 + 3.5 = 1.5 > 0 → home covers → True
    assert _grade_spread(spread_edge, actual_spread, pin_spread) is True


def test_grading_spread_home_dog_doesnt_cover():
    """Home underdog +3.5, loses by 5 → doesn't cover."""
    kp_spread = 2.0
    pin_spread = 3.5
    spread_edge = kp_spread + pin_spread  # +5.5

    actual_spread = -5

    # ats_margin = -5 + 3.5 = -1.5 < 0 → home doesn't cover → False
    assert _grade_spread(spread_edge, actual_spread, pin_spread) is False


def test_grading_push_spread():
    """Push on spread should return None.

    Push = ats_margin is exactly 0 (actual_spread == -pin_spread).
    Example: home -3, actual_spread = 3 → ats = 3 + (-3) = 0 → push.
    """
    assert _grade_spread(5.0, 3, -3) is None  # home fav -3, wins by exactly 3
    assert _grade_spread(-2.0, -3, 3) is None  # home dog +3, loses by exactly 3


def test_grading_push_total():
    """Push on total should return None."""
    assert _grade_total(3.0, 148.5, 148.5) is None


def test_grading_push_ml():
    """kp_wp == 0.5 → no pick direction → None."""
    assert _grade_ml(0.5, 5) is None


def test_grading_tie_game():
    """Tied game (actual_spread = 0) for ML should return None."""
    assert _grade_ml(0.75, 0) is None


def test_grading_zero_edge():
    """Zero edge should return None (no pick direction)."""
    assert _grade_spread(0.0, 10, -3.5) is None
    assert _grade_total(0.0, 150, 148) is None


def test_ats_coverage_formula():
    """Verify the ATS formula: actual_spread + pin_spread > 0 means home covers.

    This is the unified formula that works for both favorites and underdogs.
    """
    # Home fav -5.5, wins by 3 → doesn't cover
    assert (3 + (-5.5) > 0) is False  # -2.5 < 0

    # Home fav -5.5, wins by 7 → covers
    assert (7 + (-5.5) > 0) is True  # 1.5 > 0

    # Home dog +3.5, wins by 1 → covers
    assert (1 + 3.5 > 0) is True  # 4.5 > 0

    # Home dog +3.5, loses by 5 → doesn't cover
    assert (-5 + 3.5 > 0) is False  # -1.5 < 0

    # Home fav -3, wins by exactly 3 → push (margin = 0)
    assert (3 + (-3)) == 0


def test_grading_take_away_wins():
    """spread_edge < 0 → take away ATS. Away covers when ats_margin < 0."""
    # KP: home by 2 (kp_spread=+2), PIN: home -7.5 (pin_spread=-7.5)
    # edge = 2 + (-7.5) = -5.5 (take away)
    spread_edge = -5.5
    pin_spread = -7.5
    actual_spread = 2  # home wins by only 2

    # ats_margin = 2 + (-7.5) = -5.5 < 0 → away covered → True
    assert _grade_spread(spread_edge, actual_spread, pin_spread) is True


def test_grading_take_away_loses():
    """spread_edge < 0 → take away ATS. Away doesn't cover."""
    # KP: home by 1 (kp_spread=+1), PIN: home -1.5 (pin_spread=-1.5)
    # edge = 1 + (-1.5) = -0.5 (take away)
    spread_edge = -0.5
    pin_spread = -1.5
    actual_spread = 5  # home wins big

    # ats_margin = 5 + (-1.5) = 3.5 > 0 → home covered, away didn't → False
    assert _grade_spread(spread_edge, actual_spread, pin_spread) is False


# ---------------------------------------------------------------------------
# Unit P/L calculation tests
# ---------------------------------------------------------------------------

def _calc_unit_result(odds: int | None, correct: bool | None) -> float | None:
    """Replicate _calc_unit_result from kenpom_snapshots.py."""
    if correct is None or odds is None:
        return None
    if correct:
        if odds > 0:
            return round(odds / 100.0, 4)
        elif odds < 0:
            return round(100.0 / abs(odds), 4)
        return 0.0
    return -1.0


def test_unit_win_minus_110():
    """Win at -110 → profit = 100/110 = +0.9091."""
    result = _calc_unit_result(-110, True)
    assert result is not None
    assert result == pytest.approx(0.9091, abs=0.001)


def test_unit_win_plus_150():
    """Win at +150 → profit = 150/100 = +1.50."""
    result = _calc_unit_result(150, True)
    assert result is not None
    assert result == pytest.approx(1.50)


def test_unit_loss():
    """Loss at any odds → -1.0."""
    assert _calc_unit_result(-110, False) == -1.0
    assert _calc_unit_result(200, False) == -1.0


def test_unit_push():
    """Push (correct=None) → None."""
    assert _calc_unit_result(-110, None) is None


def test_unit_no_odds():
    """No odds → None."""
    assert _calc_unit_result(None, True) is None
    assert _calc_unit_result(None, False) is None
