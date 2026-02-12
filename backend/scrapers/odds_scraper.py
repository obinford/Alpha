#!/usr/bin/env python3
"""NBA odds pipeline - fetches odds, calculates no-vig lines, finds +EV bets.

Usage:
    python backend/scrapers/odds_scraper.py
"""

import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone

# Allow running as a standalone script from the repo root.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv

from models.ev_calculator import (
    american_to_implied_prob,
    calculate_ev,
    calculate_no_vig_probability,
)
from models.kelly import kelly_fraction
from scrapers.odds.odds_api import Game, Market, fetch_odds

# Sharp books in preference order - first available is used as the "true" line.
SHARP_BOOKS = ["pinnacle", "circa", "betonlineag"]

# Only surface bets with EV above this threshold.
MIN_EV_THRESHOLD = 1.0

# Default Kelly fraction (quarter Kelly).
DEFAULT_KELLY_FRACTION = 0.25


@dataclass
class EVOpportunity:
    game: str
    commence_time: str
    market: str
    selection: str
    point: float | None
    book: str
    book_odds: int
    book_implied_prob: float
    true_prob: float
    ev_pct: float
    kelly_pct: float


def find_sharp_book(game: Game) -> str | None:
    """Return the key of the sharpest available bookmaker for a game."""
    book_keys = {bk.key for bk in game.bookmakers}
    for sharp in SHARP_BOOKS:
        if sharp in book_keys:
            return sharp
    return None


def get_market(bookmaker_markets: list[Market], market_key: str) -> Market | None:
    """Find a specific market from a bookmaker's market list."""
    for m in bookmaker_markets:
        if m.key == market_key:
            return m
    return None


def build_sharp_line_map(
    sharp_market: Market,
) -> dict[tuple[str, float | None], float]:
    """Build a map of (selection_name, point) -> true probability from sharp odds.

    For two-outcome markets the probabilities come from no-vig devigging.
    """
    outcomes = sharp_market.outcomes
    if len(outcomes) != 2:
        return {}

    true_a, true_b = calculate_no_vig_probability(
        outcomes[0].price, outcomes[1].price
    )
    return {
        (outcomes[0].name, outcomes[0].point): true_a,
        (outcomes[1].name, outcomes[1].point): true_b,
    }


def scan_game(game: Game) -> list[EVOpportunity]:
    """Scan a single game for +EV opportunities across all books and markets."""
    sharp_key = find_sharp_book(game)
    if sharp_key is None:
        return []

    sharp_bk = next(bk for bk in game.bookmakers if bk.key == sharp_key)
    game_label = f"{game.away_team} @ {game.home_team}"
    opportunities: list[EVOpportunity] = []

    for market_key in ("h2h", "spreads", "totals"):
        sharp_market = get_market(sharp_bk.markets, market_key)
        if sharp_market is None:
            continue

        true_probs = build_sharp_line_map(sharp_market)
        if not true_probs:
            continue

        for bk in game.bookmakers:
            if bk.key == sharp_key:
                continue

            book_market = get_market(bk.markets, market_key)
            if book_market is None:
                continue

            for outcome in book_market.outcomes:
                # For spreads/totals, only compare when the line matches.
                lookup_key = (outcome.name, outcome.point)
                true_prob = true_probs.get(lookup_key)
                if true_prob is None:
                    continue

                ev_pct = calculate_ev(outcome.price, true_prob)
                if ev_pct < MIN_EV_THRESHOLD:
                    continue

                kelly_pct = kelly_fraction(
                    true_prob, outcome.price, DEFAULT_KELLY_FRACTION
                )

                opportunities.append(
                    EVOpportunity(
                        game=game_label,
                        commence_time=game.commence_time,
                        market=market_key,
                        selection=outcome.name,
                        point=outcome.point,
                        book=bk.title,
                        book_odds=outcome.price,
                        book_implied_prob=american_to_implied_prob(outcome.price),
                        true_prob=true_prob,
                        ev_pct=ev_pct,
                        kelly_pct=kelly_pct,
                    )
                )

    return opportunities


def format_american(odds: int) -> str:
    """Format American odds with a leading + for positive values."""
    return f"+{odds}" if odds > 0 else str(odds)


def format_point(market: str, point: float | None) -> str:
    """Format a spread/total point value for display."""
    if point is None:
        return ""
    if market == "spreads":
        return f" ({'+' if point > 0 else ''}{point})"
    if market == "totals":
        return f" ({point})"
    return ""


def print_results(opportunities: list[EVOpportunity]) -> None:
    """Print +EV opportunities in a readable table."""
    if not opportunities:
        print("\nNo +EV opportunities found right now.")
        return

    # Sort by EV% descending.
    opportunities.sort(key=lambda o: o.ev_pct, reverse=True)

    header = (
        f"{'Game':<40} {'Market':<8} {'Selection':<25} "
        f"{'Book':<20} {'Odds':>7} {'True%':>7} {'Book%':>7} "
        f"{'EV%':>7} {'Kelly%':>7}"
    )
    print(f"\n{'=' * len(header)}")
    print(
        f"  NBA +EV Scanner  |  "
        f"{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}  |  "
        f"{len(opportunities)} opportunities"
    )
    print(f"{'=' * len(header)}")
    print(header)
    print("-" * len(header))

    for opp in opportunities:
        sel_display = opp.selection + format_point(opp.market, opp.point)
        print(
            f"{opp.game:<40} {opp.market:<8} {sel_display:<25} "
            f"{opp.book:<20} {format_american(opp.book_odds):>7} "
            f"{opp.true_prob * 100:>6.1f}% {opp.book_implied_prob * 100:>6.1f}% "
            f"{opp.ev_pct:>+6.1f}% {opp.kelly_pct * 100:>6.2f}%"
        )

    print("-" * len(header))
    best = opportunities[0]
    print(
        f"\nBest opportunity: {best.selection} "
        f"({best.game}) at {best.book} "
        f"[{format_american(best.book_odds)}] -> {best.ev_pct:+.1f}% EV"
    )


def main() -> None:
    """Run the NBA odds pipeline."""
    # Load .env from project root.
    dotenv_path = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
    load_dotenv(dotenv_path)

    print("Fetching NBA odds from The Odds API...")
    games = fetch_odds("basketball_nba")
    print(f"Found {len(games)} upcoming/live NBA games.")

    if not games:
        print("No NBA games available right now.")
        return

    all_opportunities: list[EVOpportunity] = []
    for game in games:
        all_opportunities.extend(scan_game(game))

    print_results(all_opportunities)


if __name__ == "__main__":
    main()
