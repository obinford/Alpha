"""Tests for grading and unit-based profit/loss calculations."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scrapers.grader import _calculate_profit, grade_opportunity


class TestCalculateProfit:
    """Verify _calculate_profit uses unit-based math."""

    def test_win_underdog_plus_150(self):
        # WIN at +150: risk 1u to win 1.5u
        assert _calculate_profit("win", 150, 1.0) == 1.5

    def test_win_favorite_minus_150(self):
        # WIN at -150: risk 1u to win 0.667u
        profit = _calculate_profit("win", -150, 1.0)
        assert abs(profit - (100 / 150)) < 0.001

    def test_win_even_money_plus_100(self):
        assert _calculate_profit("win", 100, 1.0) == 1.0

    def test_win_heavy_favorite_minus_200(self):
        assert _calculate_profit("win", -200, 1.0) == 0.5

    def test_win_heavy_underdog_plus_300(self):
        assert _calculate_profit("win", 300, 1.0) == 3.0

    def test_loss_always_minus_one_unit(self):
        assert _calculate_profit("loss", 150, 1.0) == -1.0
        assert _calculate_profit("loss", -150, 1.0) == -1.0
        assert _calculate_profit("loss", 300, 1.0) == -1.0
        assert _calculate_profit("loss", -300, 1.0) == -1.0

    def test_push_always_zero(self):
        assert _calculate_profit("push", 150, 1.0) == 0.0
        assert _calculate_profit("push", -150, 1.0) == 0.0

    def test_old_100_unit_bug_would_give_wrong_values(self):
        # Verify the old bet_amount=100 would produce 100x-inflated values.
        assert _calculate_profit("loss", 150, 100) == -100
        assert _calculate_profit("win", 150, 100) == 150


class TestGradeOpportunity:
    """Verify grading logic correctly determines WIN/LOSS/PUSH."""

    def _game(self, home="Team A", away="Team B", h_score=100, a_score=95):
        return {
            "home_team": home, "away_team": away,
            "home_score": h_score, "away_score": a_score,
        }

    def test_h2h_home_wins(self):
        g = self._game(h_score=100, a_score=95)
        assert grade_opportunity({"market_type": "h2h", "side": "Team A"}, g) == "win"
        assert grade_opportunity({"market_type": "h2h", "side": "Team B"}, g) == "loss"

    def test_h2h_away_wins(self):
        g = self._game(h_score=90, a_score=100)
        assert grade_opportunity({"market_type": "h2h", "side": "Team B"}, g) == "win"
        assert grade_opportunity({"market_type": "h2h", "side": "Team A"}, g) == "loss"

    def test_h2h_push(self):
        g = self._game(h_score=100, a_score=100)
        assert grade_opportunity({"market_type": "h2h", "side": "Team A"}, g) == "push"

    def test_h2h_wrong_team_returns_none(self):
        g = self._game()
        assert grade_opportunity({"market_type": "h2h", "side": "Wrong Team"}, g) is None

    def test_spread_home_covers(self):
        g = self._game(h_score=100, a_score=95)
        # Home -3.5: 100 + (-3.5) = 96.5 > 95 -> win
        assert grade_opportunity({"market_type": "spreads", "side": "Team A -3.5"}, g) == "win"

    def test_spread_home_doesnt_cover(self):
        g = self._game(h_score=100, a_score=98)
        # Home -3.5: 100 + (-3.5) = 96.5 < 98 -> loss
        assert grade_opportunity({"market_type": "spreads", "side": "Team A -3.5"}, g) == "loss"

    def test_spread_push(self):
        g = self._game(h_score=100, a_score=97)
        # Home -3: 100 + (-3) = 97 = 97 -> push
        assert grade_opportunity({"market_type": "spreads", "side": "Team A -3"}, g) == "push"

    def test_total_over_wins(self):
        g = self._game(h_score=110, a_score=105)  # total=215
        assert grade_opportunity({"market_type": "totals", "side": "Over 210.5"}, g) == "win"
        assert grade_opportunity({"market_type": "totals", "side": "Under 210.5"}, g) == "loss"

    def test_total_under_wins(self):
        g = self._game(h_score=100, a_score=95)  # total=195
        assert grade_opportunity({"market_type": "totals", "side": "Under 200.5"}, g) == "win"
        assert grade_opportunity({"market_type": "totals", "side": "Over 200.5"}, g) == "loss"

    def test_player_prop_returns_none(self):
        g = self._game()
        assert grade_opportunity({"market_type": "player_points", "side": "Over 25.5"}, g) is None
