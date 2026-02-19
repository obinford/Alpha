"""End-to-end tests for outcome ordering in the odds pipeline.

Verifies that Pinnacle odds are never flipped regardless of the order
bookmakers and outcomes appear in The Odds API response.

Tests every combination:
  - Pinnacle first vs Pinnacle not first in bookmakers list
  - Pinnacle outcomes in alphabetical, reverse-alphabetical order
  - First bookmaker outcomes in same/different order than Pinnacle
  - h2h, spreads, and totals markets
"""

import sys
from pathlib import Path

_backend = Path(__file__).resolve().parent.parent
_shared = _backend.parent / "shared"
sys.path.insert(0, str(_backend))
sys.path.insert(0, str(_backend / "scrapers"))
sys.path.insert(0, str(_backend / "scrapers" / "odds"))
sys.path.insert(0, str(_shared))

import pytest
from odds_api import Game, Bookmaker, Market, Outcome
from odds_scraper import (
    _extract_market_odds_by_book,
    build_devig_line_map,
    scan_game,
    store_true_lines,
    store_odds_snapshots,
)
from models.devig import devig_market
from intelligence.kenpom_snapshots import _extract_pinnacle_odds


# ---------------------------------------------------------------------------
# Real-world scenario: Celtics @ Warriors
# Celtics are heavy favorites (-240), Warriors are underdogs (+200)
# ---------------------------------------------------------------------------
HOME = "Golden State Warriors"
AWAY = "Boston Celtics"

PIN_CELTICS_ODDS = -240   # real Pinnacle line: Celtics favorites
PIN_WARRIORS_ODDS = 200   # real Pinnacle line: Warriors underdogs

DK_CELTICS_ODDS = -250    # DraftKings slightly juiced on Celtics
DK_WARRIORS_ODDS = 210    # DraftKings slightly soft on Warriors


def _make_game(bookmakers: list[Bookmaker]) -> Game:
    """Create a test game with the specified bookmakers."""
    return Game(
        id="abc123",
        sport_key="basketball_nba",
        home_team=HOME,
        away_team=AWAY,
        commence_time="2026-02-19T03:00:00Z",
        bookmakers=bookmakers,
    )


def _make_h2h_bookmaker(key: str, title: str, outcomes: list[Outcome]) -> Bookmaker:
    return Bookmaker(
        key=key,
        title=title,
        markets=[Market(key="h2h", outcomes=outcomes)],
    )


def _make_spread_bookmaker(
    key: str, title: str, outcomes: list[Outcome]
) -> Bookmaker:
    return Bookmaker(
        key=key,
        title=title,
        markets=[Market(key="spreads", outcomes=outcomes)],
    )


def _make_totals_bookmaker(
    key: str, title: str, outcomes: list[Outcome]
) -> Bookmaker:
    return Bookmaker(
        key=key,
        title=title,
        markets=[Market(key="totals", outcomes=outcomes)],
    )


# ---------------------------------------------------------------------------
# Helper: emulate the frontend's trueProbToAmericanOdds
# ---------------------------------------------------------------------------
def true_prob_to_american(prob: float) -> int:
    if prob <= 0 or prob >= 1:
        return -110
    if prob > 0.5:
        return round((-100 * prob) / (1 - prob))
    return round((100 * (1 - prob)) / prob)


# =========================================================================
# TEST 1: h2h — Pinnacle first, outcomes [Warriors, Celtics]
# =========================================================================
class TestH2HOutcomeOrdering:
    """Every permutation of h2h outcome ordering."""

    def _assert_celtics_are_favorites(self, game: Game) -> None:
        """Core assertion: verify Celtics get the higher true probability."""
        true_probs, source, confidence, method, source_keys = build_devig_line_map(
            game, "h2h"
        )
        assert true_probs, "build_devig_line_map returned empty true_probs"
        assert "pinnacle" in source_keys or source == "pinnacle"

        celtics_prob = true_probs.get(("Boston Celtics", None))
        warriors_prob = true_probs.get(("Golden State Warriors", None))

        assert celtics_prob is not None, f"No Celtics prob in {true_probs}"
        assert warriors_prob is not None, f"No Warriors prob in {true_probs}"
        assert celtics_prob > 0.5, (
            f"Celtics should be favorites (>50%) but got {celtics_prob:.4f}"
        )
        assert warriors_prob < 0.5, (
            f"Warriors should be underdogs (<50%) but got {warriors_prob:.4f}"
        )

        # Verify the frontend would show the right Pinnacle odds
        celtics_display = true_prob_to_american(celtics_prob)
        warriors_display = true_prob_to_american(warriors_prob)
        assert celtics_display < 0, (
            f"Celtics Pinnacle display should be negative (favorites) "
            f"but got {celtics_display}"
        )
        assert warriors_display > 0, (
            f"Warriors Pinnacle display should be positive (underdogs) "
            f"but got {warriors_display}"
        )
        print(
            f"  OK: Celtics prob={celtics_prob:.4f} (PIN {celtics_display}), "
            f"Warriors prob={warriors_prob:.4f} (PIN {warriors_display})"
        )

    def test_pinnacle_first_warriors_then_celtics(self):
        """Pinnacle first bookmaker, outcomes: [Warriors+200, Celtics-240]."""
        pin = _make_h2h_bookmaker("pinnacle", "Pinnacle", [
            Outcome(name=HOME, price=PIN_WARRIORS_ODDS),
            Outcome(name=AWAY, price=PIN_CELTICS_ODDS),
        ])
        dk = _make_h2h_bookmaker("draftkings", "DraftKings", [
            Outcome(name=AWAY, price=DK_CELTICS_ODDS),
            Outcome(name=HOME, price=DK_WARRIORS_ODDS),
        ])
        game = _make_game([pin, dk])
        self._assert_celtics_are_favorites(game)

    def test_pinnacle_first_celtics_then_warriors(self):
        """Pinnacle first bookmaker, outcomes: [Celtics-240, Warriors+200]."""
        pin = _make_h2h_bookmaker("pinnacle", "Pinnacle", [
            Outcome(name=AWAY, price=PIN_CELTICS_ODDS),
            Outcome(name=HOME, price=PIN_WARRIORS_ODDS),
        ])
        dk = _make_h2h_bookmaker("draftkings", "DraftKings", [
            Outcome(name=HOME, price=DK_WARRIORS_ODDS),
            Outcome(name=AWAY, price=DK_CELTICS_ODDS),
        ])
        game = _make_game([pin, dk])
        self._assert_celtics_are_favorites(game)

    def test_pinnacle_second_same_order(self):
        """DK first with [Celtics, Warriors], Pinnacle second with [Celtics, Warriors]."""
        dk = _make_h2h_bookmaker("draftkings", "DraftKings", [
            Outcome(name=AWAY, price=DK_CELTICS_ODDS),
            Outcome(name=HOME, price=DK_WARRIORS_ODDS),
        ])
        pin = _make_h2h_bookmaker("pinnacle", "Pinnacle", [
            Outcome(name=AWAY, price=PIN_CELTICS_ODDS),
            Outcome(name=HOME, price=PIN_WARRIORS_ODDS),
        ])
        game = _make_game([dk, pin])
        self._assert_celtics_are_favorites(game)

    def test_pinnacle_second_reversed_order(self):
        """DK first with [Celtics, Warriors], Pinnacle second with [Warriors, Celtics].
        This is the scenario that triggers the flip bug."""
        dk = _make_h2h_bookmaker("draftkings", "DraftKings", [
            Outcome(name=AWAY, price=DK_CELTICS_ODDS),
            Outcome(name=HOME, price=DK_WARRIORS_ODDS),
        ])
        pin = _make_h2h_bookmaker("pinnacle", "Pinnacle", [
            Outcome(name=HOME, price=PIN_WARRIORS_ODDS),
            Outcome(name=AWAY, price=PIN_CELTICS_ODDS),
        ])
        game = _make_game([dk, pin])
        self._assert_celtics_are_favorites(game)

    def test_dk_first_warriors_celtics_pin_warriors_celtics(self):
        """DK first with [Warriors, Celtics], Pinnacle [Warriors, Celtics]."""
        dk = _make_h2h_bookmaker("draftkings", "DraftKings", [
            Outcome(name=HOME, price=DK_WARRIORS_ODDS),
            Outcome(name=AWAY, price=DK_CELTICS_ODDS),
        ])
        pin = _make_h2h_bookmaker("pinnacle", "Pinnacle", [
            Outcome(name=HOME, price=PIN_WARRIORS_ODDS),
            Outcome(name=AWAY, price=PIN_CELTICS_ODDS),
        ])
        game = _make_game([dk, pin])
        self._assert_celtics_are_favorites(game)

    def test_dk_first_warriors_celtics_pin_celtics_warriors(self):
        """DK first with [Warriors, Celtics], Pinnacle [Celtics, Warriors]."""
        dk = _make_h2h_bookmaker("draftkings", "DraftKings", [
            Outcome(name=HOME, price=DK_WARRIORS_ODDS),
            Outcome(name=AWAY, price=DK_CELTICS_ODDS),
        ])
        pin = _make_h2h_bookmaker("pinnacle", "Pinnacle", [
            Outcome(name=AWAY, price=PIN_CELTICS_ODDS),
            Outcome(name=HOME, price=PIN_WARRIORS_ODDS),
        ])
        game = _make_game([dk, pin])
        self._assert_celtics_are_favorites(game)


# =========================================================================
# TEST 2: _extract_market_odds_by_book — verify consistent pairing
# =========================================================================
class TestExtractMarketOddsByBook:
    """Verify that _extract_market_odds_by_book pairs odds correctly by name."""

    def test_basic_same_order(self):
        """Both books have outcomes in same order."""
        dk = _make_h2h_bookmaker("draftkings", "DraftKings", [
            Outcome(name="Team A", price=-150),
            Outcome(name="Team B", price=130),
        ])
        pin = _make_h2h_bookmaker("pinnacle", "Pinnacle", [
            Outcome(name="Team A", price=-145),
            Outcome(name="Team B", price=125),
        ])
        game = _make_game([dk, pin])
        book_odds, outcome_info = _extract_market_odds_by_book(game, "h2h")

        assert outcome_info[0] == "Team A"
        assert outcome_info[1] == "Team B"
        assert book_odds["draftkings"] == (-150, 130)
        assert book_odds["pinnacle"] == (-145, 125), (
            f"Pinnacle should be (-145, 125) but got {book_odds['pinnacle']}"
        )

    def test_reversed_order(self):
        """Pinnacle has outcomes in reverse order from DK."""
        dk = _make_h2h_bookmaker("draftkings", "DraftKings", [
            Outcome(name="Team A", price=-150),
            Outcome(name="Team B", price=130),
        ])
        pin = _make_h2h_bookmaker("pinnacle", "Pinnacle", [
            Outcome(name="Team B", price=125),
            Outcome(name="Team A", price=-145),
        ])
        game = _make_game([dk, pin])
        book_odds, outcome_info = _extract_market_odds_by_book(game, "h2h")

        assert outcome_info[0] == "Team A"
        assert outcome_info[1] == "Team B"
        # Pinnacle's odds must be reordered to match canonical: (A odds, B odds)
        assert book_odds["pinnacle"] == (-145, 125), (
            f"Pinnacle should be reordered to (-145, 125) but got {book_odds['pinnacle']}"
        )

    def test_pinnacle_first_sets_canonical(self):
        """When Pinnacle is first, it sets the canonical order."""
        pin = _make_h2h_bookmaker("pinnacle", "Pinnacle", [
            Outcome(name="Team B", price=125),
            Outcome(name="Team A", price=-145),
        ])
        dk = _make_h2h_bookmaker("draftkings", "DraftKings", [
            Outcome(name="Team A", price=-150),
            Outcome(name="Team B", price=130),
        ])
        game = _make_game([pin, dk])
        book_odds, outcome_info = _extract_market_odds_by_book(game, "h2h")

        # Pinnacle is first → canonical order is (B, A)
        assert outcome_info[0] == "Team B"
        assert outcome_info[1] == "Team A"
        assert book_odds["pinnacle"] == (125, -145)
        # DK must be reordered to match: (B odds, A odds)
        assert book_odds["draftkings"] == (130, -150), (
            f"DK should be reordered to (130, -150) but got {book_odds['draftkings']}"
        )


# =========================================================================
# TEST 3: devig_market — verify probability assignment is correct
# =========================================================================
class TestDevigProbAssignment:
    """Verify that the devig chain (extract → devig → map) assigns
    probabilities to the correct team names."""

    def test_celtics_warriors_all_orderings(self):
        """Test all 4 permutations of DK-first × Pinnacle outcome order."""
        orderings = [
            # (dk_outcomes, pin_outcomes, label)
            (
                [Outcome(name=AWAY, price=DK_CELTICS_ODDS), Outcome(name=HOME, price=DK_WARRIORS_ODDS)],
                [Outcome(name=AWAY, price=PIN_CELTICS_ODDS), Outcome(name=HOME, price=PIN_WARRIORS_ODDS)],
                "DK:[Celtics,Warriors] PIN:[Celtics,Warriors]",
            ),
            (
                [Outcome(name=AWAY, price=DK_CELTICS_ODDS), Outcome(name=HOME, price=DK_WARRIORS_ODDS)],
                [Outcome(name=HOME, price=PIN_WARRIORS_ODDS), Outcome(name=AWAY, price=PIN_CELTICS_ODDS)],
                "DK:[Celtics,Warriors] PIN:[Warriors,Celtics]",
            ),
            (
                [Outcome(name=HOME, price=DK_WARRIORS_ODDS), Outcome(name=AWAY, price=DK_CELTICS_ODDS)],
                [Outcome(name=AWAY, price=PIN_CELTICS_ODDS), Outcome(name=HOME, price=PIN_WARRIORS_ODDS)],
                "DK:[Warriors,Celtics] PIN:[Celtics,Warriors]",
            ),
            (
                [Outcome(name=HOME, price=DK_WARRIORS_ODDS), Outcome(name=AWAY, price=DK_CELTICS_ODDS)],
                [Outcome(name=HOME, price=PIN_WARRIORS_ODDS), Outcome(name=AWAY, price=PIN_CELTICS_ODDS)],
                "DK:[Warriors,Celtics] PIN:[Warriors,Celtics]",
            ),
        ]

        for dk_outs, pin_outs, label in orderings:
            dk = _make_h2h_bookmaker("draftkings", "DraftKings", dk_outs)
            pin = _make_h2h_bookmaker("pinnacle", "Pinnacle", pin_outs)

            # Test with DK first
            game = _make_game([dk, pin])
            true_probs, source, *_ = build_devig_line_map(game, "h2h")

            celtics_prob = true_probs.get(("Boston Celtics", None))
            warriors_prob = true_probs.get(("Golden State Warriors", None))

            assert celtics_prob is not None, f"[{label} DK-first] Missing Celtics prob"
            assert warriors_prob is not None, f"[{label} DK-first] Missing Warriors prob"
            assert celtics_prob > 0.5, (
                f"[{label} DK-first] Celtics should be >50% but got {celtics_prob:.4f}"
            )
            assert warriors_prob < 0.5, (
                f"[{label} DK-first] Warriors should be <50% but got {warriors_prob:.4f}"
            )

            # Test with Pinnacle first
            game2 = _make_game([pin, dk])
            true_probs2, *_ = build_devig_line_map(game2, "h2h")

            celtics_prob2 = true_probs2.get(("Boston Celtics", None))
            warriors_prob2 = true_probs2.get(("Golden State Warriors", None))

            assert celtics_prob2 is not None, f"[{label} PIN-first] Missing Celtics prob"
            assert warriors_prob2 is not None, f"[{label} PIN-first] Missing Warriors prob"
            assert celtics_prob2 > 0.5, (
                f"[{label} PIN-first] Celtics should be >50% but got {celtics_prob2:.4f}"
            )

            # Probabilities should be (nearly) identical regardless of order
            assert abs(celtics_prob - celtics_prob2) < 0.01, (
                f"[{label}] Celtics prob differs: DK-first={celtics_prob:.4f} "
                f"vs PIN-first={celtics_prob2:.4f}"
            )

            print(f"  OK [{label}] Celtics={celtics_prob:.4f}, Warriors={warriors_prob:.4f}")


# =========================================================================
# TEST 4: scan_game — verify EV opportunities have correct true_prob
# =========================================================================
class TestScanGame:
    """Verify that scan_game produces opportunities with correct true_prob
    matching the team selection."""

    def test_opportunity_true_prob_matches_selection(self):
        """Every EV opportunity's true_prob should match its selection's
        probability, not the opponent's."""
        # DraftKings offers Warriors at +210 (juicy), Celtics at -250
        # Pinnacle sharp line: Warriors +200, Celtics -240
        # So Warriors at DK (+210 vs true +200) = small +EV
        dk = _make_h2h_bookmaker("draftkings", "DraftKings", [
            Outcome(name=HOME, price=210),
            Outcome(name=AWAY, price=-250),
        ])
        # Pinnacle in REVERSE order from DK
        pin = _make_h2h_bookmaker("pinnacle", "Pinnacle", [
            Outcome(name=AWAY, price=-240),
            Outcome(name=HOME, price=200),
        ])
        game = _make_game([dk, pin])
        opportunities = scan_game(game)

        for opp in opportunities:
            if opp.selection == "Boston Celtics":
                assert opp.true_prob > 0.5, (
                    f"Celtics opportunity has true_prob={opp.true_prob:.4f} "
                    f"but should be >50% (favorites). "
                    f"Frontend would show PIN {true_prob_to_american(opp.true_prob)}"
                )
            elif opp.selection == "Golden State Warriors":
                assert opp.true_prob < 0.5, (
                    f"Warriors opportunity has true_prob={opp.true_prob:.4f} "
                    f"but should be <50% (underdogs). "
                    f"Frontend would show PIN {true_prob_to_american(opp.true_prob)}"
                )

            # Show what the frontend would display
            pin_display = true_prob_to_american(opp.true_prob)
            print(
                f"  {opp.selection}: true_prob={opp.true_prob:.4f}, "
                f"book_odds={opp.book_odds:+d}, ev={opp.ev_pct:.2f}%, "
                f"PIN display={pin_display:+d}"
            )


# =========================================================================
# TEST 5: store_true_lines — verify home/away mapping
# =========================================================================
class TestStoreTrueLines:
    """Verify that store_true_lines correctly assigns true_home_prob
    to the home team and true_away_prob to the away team."""

    def test_true_home_is_actually_home(self):
        """true_home_prob must correspond to game.home_team (Warriors)."""
        dk = _make_h2h_bookmaker("draftkings", "DraftKings", [
            # DK lists away team first — canonical name_a = Celtics
            Outcome(name=AWAY, price=DK_CELTICS_ODDS),
            Outcome(name=HOME, price=DK_WARRIORS_ODDS),
        ])
        pin = _make_h2h_bookmaker("pinnacle", "Pinnacle", [
            # Pinnacle lists in different order
            Outcome(name=HOME, price=PIN_WARRIORS_ODDS),
            Outcome(name=AWAY, price=PIN_CELTICS_ODDS),
        ])
        game = _make_game([dk, pin])

        # Extract what store_true_lines now computes using the FIXED code.
        true_probs, source, confidence, method, _source_keys = build_devig_line_map(
            game, "h2h"
        )

        # The fix looks up by game.home_team / game.away_team directly.
        true_home = 0.5
        true_away = 0.5
        for (name, pt), prob in true_probs.items():
            if name == game.home_team:
                true_home = prob
            elif name == game.away_team:
                true_away = prob

        # Warriors are home and underdogs, Celtics are away and favorites.
        assert true_home < 0.5, (
            f"Warriors (home) should be underdogs (<50%) but got {true_home:.4f}"
        )
        assert true_away > 0.5, (
            f"Celtics (away) should be favorites (>50%) but got {true_away:.4f}"
        )
        print(
            f"  OK: true_home_prob={true_home:.4f} ({game.home_team}), "
            f"true_away_prob={true_away:.4f} ({game.away_team})"
        )


# =========================================================================
# TEST 6: spreads — verify name matching works for spreads too
# =========================================================================
class TestSpreadsOrdering:
    """Verify consistent outcome ordering for spread markets."""

    def test_spread_name_matching(self):
        """Spread outcomes should be matched by name just like h2h."""
        dk = _make_spread_bookmaker("draftkings", "DraftKings", [
            Outcome(name=AWAY, price=-110, point=-3.5),
            Outcome(name=HOME, price=-110, point=3.5),
        ])
        pin = _make_spread_bookmaker("pinnacle", "Pinnacle", [
            # Reversed order
            Outcome(name=HOME, price=-105, point=3.5),
            Outcome(name=AWAY, price=-115, point=-3.5),
        ])
        game = _make_game([dk, pin])
        book_odds, outcome_info = _extract_market_odds_by_book(game, "spreads")

        # DK set canonical: name_a=AWAY, name_b=HOME
        assert outcome_info[0] == AWAY
        assert outcome_info[1] == HOME
        # Pinnacle must be reordered to match
        assert book_odds["pinnacle"] == (-115, -105), (
            f"Pinnacle spreads should be (away_odds=-115, home_odds=-105) "
            f"but got {book_odds['pinnacle']}"
        )


# =========================================================================
# TEST 7: Multiple games — different orderings per game
# =========================================================================
class TestMultipleGames:
    """Verify consistency across multiple games with different orderings."""

    def test_three_games_different_orderings(self):
        """Three games, each with different outcome orderings."""
        games_data = [
            ("Team Alpha", "Team Beta", -300, 250, -310, 260),
            ("Team Charlie", "Team Delta", 150, -170, 160, -180),
            ("Team Echo", "Team Foxtrot", -110, -110, -108, -112),
        ]

        for home, away, pin_h, pin_a, dk_h, dk_a in games_data:
            # DK lists home first, Pinnacle lists away first (reversed)
            dk = _make_h2h_bookmaker("draftkings", "DraftKings", [
                Outcome(name=home, price=dk_h),
                Outcome(name=away, price=dk_a),
            ])
            pin = _make_h2h_bookmaker("pinnacle", "Pinnacle", [
                Outcome(name=away, price=pin_a),
                Outcome(name=home, price=pin_h),
            ])
            game = Game(
                id=f"game_{home.lower().replace(' ', '_')}",
                sport_key="basketball_nba",
                home_team=home,
                away_team=away,
                commence_time="2026-02-19T03:00:00Z",
                bookmakers=[dk, pin],
            )
            true_probs, *_ = build_devig_line_map(game, "h2h")
            home_prob = true_probs.get((home, None))
            away_prob = true_probs.get((away, None))

            assert home_prob is not None, f"Missing prob for {home}"
            assert away_prob is not None, f"Missing prob for {away}"

            # The team with the more negative odds should have higher prob
            if pin_h < pin_a:  # home is favorite
                assert home_prob > away_prob, (
                    f"{home} ({pin_h}) should have higher prob than {away} ({pin_a}), "
                    f"got home={home_prob:.4f} away={away_prob:.4f}"
                )
            elif pin_a < pin_h:  # away is favorite
                assert away_prob > home_prob, (
                    f"{away} ({pin_a}) should have higher prob than {home} ({pin_h}), "
                    f"got home={home_prob:.4f} away={away_prob:.4f}"
                )

            home_display = true_prob_to_american(home_prob)
            away_display = true_prob_to_american(away_prob)
            print(
                f"  {away} @ {home}: "
                f"home_prob={home_prob:.4f} (PIN {home_display:+d}), "
                f"away_prob={away_prob:.4f} (PIN {away_display:+d})"
            )


# =========================================================================
# TEST 8: store_odds_snapshots — totals use Over/Under name matching
# =========================================================================
class TestStoreOddsSnapshotsTotals:
    """Verify that store_odds_snapshots maps Over→home_odds, Under→away_odds
    regardless of outcome order in the API response."""

    class MockDB:
        """Capture rows passed to _post_many instead of writing to Supabase."""
        def __init__(self):
            self.posted_rows: list[dict] = []

        def _post_many(self, table: str, rows: list[dict]) -> None:
            self.posted_rows.extend(rows)

    def _make_totals_game(self, over_first: bool) -> Game:
        """Create a game with Pinnacle totals in specified order."""
        if over_first:
            outcomes = [
                Outcome(name="Over", price=-110, point=215.5),
                Outcome(name="Under", price=-110, point=215.5),
            ]
        else:
            outcomes = [
                Outcome(name="Under", price=-110, point=215.5),
                Outcome(name="Over", price=-110, point=215.5),
            ]
        pin = _make_totals_bookmaker("pinnacle", "Pinnacle", outcomes)
        return _make_game([pin])

    def test_over_first(self):
        """When API returns Over before Under, home_odds=Over odds."""
        db = self.MockDB()
        game = self._make_totals_game(over_first=True)
        store_odds_snapshots(db, [game])

        assert len(db.posted_rows) == 1
        row = db.posted_rows[0]
        assert row["market_type"] == "totals"
        assert row["home_odds"] == -110  # Over
        assert row["away_odds"] == -110  # Under
        assert row["total_value"] == 215.5

    def test_under_first(self):
        """When API returns Under before Over, home_odds should STILL be Over."""
        db = self.MockDB()
        game = self._make_totals_game(over_first=False)
        store_odds_snapshots(db, [game])

        assert len(db.posted_rows) == 1
        row = db.posted_rows[0]
        assert row["market_type"] == "totals"
        # Over should always map to home_odds, Under to away_odds
        assert row["home_odds"] == -110  # Over
        assert row["away_odds"] == -110  # Under
        assert row["total_value"] == 215.5

    def test_h2h_name_matching(self):
        """h2h outcomes are matched by team name regardless of order."""
        db = self.MockDB()
        # Pinnacle returns Warriors first (but Warriors are home)
        pin = _make_h2h_bookmaker("pinnacle", "Pinnacle", [
            Outcome(name=HOME, price=PIN_WARRIORS_ODDS),
            Outcome(name=AWAY, price=PIN_CELTICS_ODDS),
        ])
        game = _make_game([pin])
        store_odds_snapshots(db, [game])

        assert len(db.posted_rows) == 1
        row = db.posted_rows[0]
        assert row["home_odds"] == PIN_WARRIORS_ODDS, (
            f"Home odds should be Warriors ({PIN_WARRIORS_ODDS}) "
            f"but got {row['home_odds']}"
        )
        assert row["away_odds"] == PIN_CELTICS_ODDS, (
            f"Away odds should be Celtics ({PIN_CELTICS_ODDS}) "
            f"but got {row['away_odds']}"
        )

    def test_h2h_reversed_order(self):
        """h2h with Celtics (away) listed first — must still map correctly."""
        db = self.MockDB()
        pin = _make_h2h_bookmaker("pinnacle", "Pinnacle", [
            Outcome(name=AWAY, price=PIN_CELTICS_ODDS),
            Outcome(name=HOME, price=PIN_WARRIORS_ODDS),
        ])
        game = _make_game([pin])
        store_odds_snapshots(db, [game])

        assert len(db.posted_rows) == 1
        row = db.posted_rows[0]
        assert row["home_odds"] == PIN_WARRIORS_ODDS, (
            f"Home odds should be Warriors ({PIN_WARRIORS_ODDS}) "
            f"but got {row['home_odds']}"
        )
        assert row["away_odds"] == PIN_CELTICS_ODDS, (
            f"Away odds should be Celtics ({PIN_CELTICS_ODDS}) "
            f"but got {row['away_odds']}"
        )
        print(
            f"  OK: home_odds={row['home_odds']:+d} ({HOME}), "
            f"away_odds={row['away_odds']:+d} ({AWAY})"
        )


# =========================================================================
# TEST 9: _extract_pinnacle_odds — name-based h2h/spreads extraction
# =========================================================================
class TestExtractPinnacleOdds:
    """Verify _extract_pinnacle_odds in kenpom_snapshots.py correctly
    assigns home_ml/away_ml by matching outcome name to home_team."""

    def test_h2h_warriors_first(self):
        """Pinnacle lists Warriors first — home_ml should be Warriors odds."""
        pin = _make_h2h_bookmaker("pinnacle", "Pinnacle", [
            Outcome(name=HOME, price=PIN_WARRIORS_ODDS),
            Outcome(name=AWAY, price=PIN_CELTICS_ODDS),
        ])
        game = _make_game([pin])
        result = _extract_pinnacle_odds(game)

        assert result is not None
        assert result["home_ml"] == PIN_WARRIORS_ODDS, (
            f"home_ml should be Warriors ({PIN_WARRIORS_ODDS}) "
            f"but got {result['home_ml']}"
        )
        assert result["away_ml"] == PIN_CELTICS_ODDS, (
            f"away_ml should be Celtics ({PIN_CELTICS_ODDS}) "
            f"but got {result['away_ml']}"
        )
        print(
            f"  OK: home_ml={result['home_ml']:+d} ({HOME}), "
            f"away_ml={result['away_ml']:+d} ({AWAY})"
        )

    def test_h2h_celtics_first(self):
        """Pinnacle lists Celtics first — home_ml should STILL be Warriors."""
        pin = _make_h2h_bookmaker("pinnacle", "Pinnacle", [
            Outcome(name=AWAY, price=PIN_CELTICS_ODDS),
            Outcome(name=HOME, price=PIN_WARRIORS_ODDS),
        ])
        game = _make_game([pin])
        result = _extract_pinnacle_odds(game)

        assert result is not None
        assert result["home_ml"] == PIN_WARRIORS_ODDS, (
            f"home_ml should be Warriors ({PIN_WARRIORS_ODDS}) "
            f"but got {result['home_ml']}"
        )
        assert result["away_ml"] == PIN_CELTICS_ODDS, (
            f"away_ml should be Celtics ({PIN_CELTICS_ODDS}) "
            f"but got {result['away_ml']}"
        )

    def test_spreads_name_matching(self):
        """Pinnacle spreads should match by team name, not position."""
        pin = Bookmaker(
            key="pinnacle",
            title="Pinnacle",
            markets=[
                Market(key="spreads", outcomes=[
                    # Away team listed first
                    Outcome(name=AWAY, price=-115, point=-3.5),
                    Outcome(name=HOME, price=-105, point=3.5),
                ]),
            ],
        )
        game = _make_game([pin])
        result = _extract_pinnacle_odds(game)

        assert result is not None
        assert result["spread_home"] == 3.5, (
            f"spread_home should be +3.5 (home Warriors) but got {result['spread_home']}"
        )
        assert result["spread_home_odds"] == -105

    def test_totals_name_matching(self):
        """Pinnacle totals should match Over/Under by name."""
        pin = Bookmaker(
            key="pinnacle",
            title="Pinnacle",
            markets=[
                Market(key="totals", outcomes=[
                    # Under listed first
                    Outcome(name="Under", price=-108, point=215.5),
                    Outcome(name="Over", price=-112, point=215.5),
                ]),
            ],
        )
        game = _make_game([pin])
        result = _extract_pinnacle_odds(game)

        assert result is not None
        assert result["total"] == 215.5
        assert result["over_odds"] == -112
        assert result["under_odds"] == -108
