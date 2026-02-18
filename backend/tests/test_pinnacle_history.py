"""Tests for intelligence.pinnacle_history module."""

import sys
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from intelligence.pinnacle_history import (
    _build_pinnacle_rows,
    _game_has_started,
    get_pinnacle_opening_closing,
)


# --- Minimal dataclass stubs matching odds_api.Game ---

@dataclass
class Outcome:
    name: str
    price: int
    point: float | None = None
    description: str | None = None


@dataclass
class Market:
    key: str
    outcomes: list[Outcome] = field(default_factory=list)


@dataclass
class Bookmaker:
    key: str
    title: str
    markets: list[Market] = field(default_factory=list)


@dataclass
class Game:
    id: str
    sport_key: str
    home_team: str
    away_team: str
    commence_time: str
    bookmakers: list[Bookmaker] = field(default_factory=list)


def _make_game_with_pinnacle() -> Game:
    """Create a game with full Pinnacle h2h, spreads, and totals."""
    return Game(
        id="game1",
        sport_key="basketball_ncaab",
        home_team="Kansas Jayhawks",
        away_team="Duke Blue Devils",
        commence_time="2026-02-20T00:00:00Z",
        bookmakers=[
            Bookmaker(
                key="pinnacle",
                title="Pinnacle",
                markets=[
                    Market(
                        key="h2h",
                        outcomes=[
                            Outcome(name="Kansas Jayhawks", price=-150),
                            Outcome(name="Duke Blue Devils", price=130),
                        ],
                    ),
                    Market(
                        key="spreads",
                        outcomes=[
                            Outcome(name="Kansas Jayhawks", price=-110, point=-5.5),
                            Outcome(name="Duke Blue Devils", price=-110, point=5.5),
                        ],
                    ),
                    Market(
                        key="totals",
                        outcomes=[
                            Outcome(name="Over", price=-108, point=150.5),
                            Outcome(name="Under", price=-112, point=150.5),
                        ],
                    ),
                ],
            ),
        ],
    )


class TestBuildPinnacleRows:
    def test_h2h_rows(self):
        game = _make_game_with_pinnacle()
        rows = _build_pinnacle_rows([game], "opening", "2026-02-18", "2026-02-18T12:00:00Z")
        h2h = [r for r in rows if r["market_type"] == "h2h"]
        assert len(h2h) == 1
        r = h2h[0]
        assert r["game_id"] == "game1"
        assert r["home_odds"] == -150
        assert r["away_odds"] == 130
        assert r["line_value"] is None
        assert r["over_odds"] is None
        assert r["snapshot_type"] == "opening"
        # Devigged probs should sum close to 1.
        assert r["home_prob"] is not None
        assert r["away_prob"] is not None
        assert abs(r["home_prob"] + r["away_prob"] - 1.0) < 0.01

    def test_spreads_rows(self):
        game = _make_game_with_pinnacle()
        rows = _build_pinnacle_rows([game], "closing", "2026-02-18", "2026-02-18T12:00:00Z")
        spreads = [r for r in rows if r["market_type"] == "spreads"]
        assert len(spreads) == 1
        r = spreads[0]
        assert r["line_value"] == -5.5  # home spread
        assert r["home_odds"] == -110
        assert r["away_odds"] == -110
        assert r["snapshot_type"] == "closing"

    def test_totals_rows(self):
        game = _make_game_with_pinnacle()
        rows = _build_pinnacle_rows([game], "current", "2026-02-18", "2026-02-18T12:00:00Z")
        totals = [r for r in rows if r["market_type"] == "totals"]
        assert len(totals) == 1
        r = totals[0]
        assert r["line_value"] == 150.5
        assert r["over_odds"] == -108
        assert r["under_odds"] == -112
        assert r["home_odds"] is None  # not used for totals
        assert r["away_odds"] is None

    def test_three_markets_per_game(self):
        game = _make_game_with_pinnacle()
        rows = _build_pinnacle_rows([game], "opening", "2026-02-18", "2026-02-18T12:00:00Z")
        assert len(rows) == 3  # h2h + spreads + totals

    def test_no_pinnacle_returns_empty(self):
        game = Game(
            id="game2",
            sport_key="basketball_ncaab",
            home_team="A", away_team="B",
            commence_time="2026-02-20T00:00:00Z",
            bookmakers=[
                Bookmaker(key="draftkings", title="DraftKings", markets=[]),
            ],
        )
        rows = _build_pinnacle_rows([game], "opening", "2026-02-18", "2026-02-18T12:00:00Z")
        assert rows == []

    def test_h2h_away_first_in_outcomes(self):
        """When away team is listed first in outcomes, still correctly identifies home/away."""
        game = Game(
            id="game3",
            sport_key="basketball_ncaab",
            home_team="Kansas Jayhawks",
            away_team="Duke Blue Devils",
            commence_time="2026-02-20T00:00:00Z",
            bookmakers=[
                Bookmaker(
                    key="pinnacle",
                    title="Pinnacle",
                    markets=[
                        Market(
                            key="h2h",
                            outcomes=[
                                Outcome(name="Duke Blue Devils", price=130),
                                Outcome(name="Kansas Jayhawks", price=-150),
                            ],
                        ),
                    ],
                ),
            ],
        )
        rows = _build_pinnacle_rows([game], "opening", "2026-02-18", "2026-02-18T12:00:00Z")
        assert len(rows) == 1
        # home_odds should be Kansas's odds (-150) regardless of outcome order.
        assert rows[0]["home_odds"] == -150
        assert rows[0]["away_odds"] == 130


class TestGameHasStarted:
    def test_future_game(self):
        future = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        assert _game_has_started(future) is False

    def test_past_game(self):
        past = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        assert _game_has_started(past) is True


class TestGetOpeningClosing:
    def test_returns_opening_and_closing(self):
        db = MagicMock()
        db._get.return_value = [
            {
                "snapshot_type": "opening",
                "line_value": -5.5,
                "home_odds": -110,
                "away_odds": -110,
                "over_odds": None,
                "under_odds": None,
                "home_prob": 0.5,
                "away_prob": 0.5,
            },
            {
                "snapshot_type": "closing",
                "line_value": -7.5,
                "home_odds": -115,
                "away_odds": -105,
                "over_odds": None,
                "under_odds": None,
                "home_prob": 0.53,
                "away_prob": 0.47,
            },
        ]
        result = get_pinnacle_opening_closing(db, "game1", "spreads")
        assert result is not None
        assert result["opening_line"] == -5.5
        assert result["closing_line"] == -7.5
        assert result["line_movement"] == -2.0
        assert result["opening_home_odds"] == -110
        assert result["closing_home_odds"] == -115

    def test_no_data_returns_none(self):
        db = MagicMock()
        db._get.return_value = []
        result = get_pinnacle_opening_closing(db, "game1", "spreads")
        assert result is None

    def test_opening_only(self):
        db = MagicMock()
        db._get.return_value = [
            {
                "snapshot_type": "opening",
                "line_value": -3.5,
                "home_odds": -110,
                "away_odds": -110,
                "over_odds": None,
                "under_odds": None,
                "home_prob": 0.5,
                "away_prob": 0.5,
            },
        ]
        result = get_pinnacle_opening_closing(db, "game1", "spreads")
        assert result is not None
        assert result["opening_line"] == -3.5
        assert result["closing_line"] is None
        assert result["line_movement"] is None

    def test_totals_uses_over_under_odds(self):
        db = MagicMock()
        db._get.return_value = [
            {
                "snapshot_type": "opening",
                "line_value": 148.5,
                "home_odds": None,
                "away_odds": None,
                "over_odds": -110,
                "under_odds": -110,
                "home_prob": 0.5,
                "away_prob": 0.5,
            },
            {
                "snapshot_type": "closing",
                "line_value": 151.5,
                "home_odds": None,
                "away_odds": None,
                "over_odds": -108,
                "under_odds": -112,
                "home_prob": 0.51,
                "away_prob": 0.49,
            },
        ]
        result = get_pinnacle_opening_closing(db, "game1", "totals")
        assert result is not None
        assert result["opening_home_odds"] == -110  # falls back to over_odds
        assert result["closing_home_odds"] == -108
        assert result["line_movement"] == 3.0

    def test_db_error_returns_none(self):
        db = MagicMock()
        db._get.side_effect = Exception("connection failed")
        result = get_pinnacle_opening_closing(db, "game1", "h2h")
        assert result is None
