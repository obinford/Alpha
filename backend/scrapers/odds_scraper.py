#!/usr/bin/env python3
"""NBA odds pipeline - fetches odds, calculates no-vig lines, finds +EV bets.

Stores every pull (games, odds_snapshots, true_lines, ev_opportunities) in
Supabase and prints results to the console.

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

# Default bankroll units for recommended-units sizing.
DEFAULT_BANKROLL_UNITS = 100.0


@dataclass
class EVOpportunity:
    game_id: str
    game: str
    commence_time: str
    market: str
    selection: str
    point: float | None
    book: str
    book_key: str
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
                        game_id=game.id,
                        game=game_label,
                        commence_time=game.commence_time,
                        market=market_key,
                        selection=outcome.name,
                        point=outcome.point,
                        book=bk.title,
                        book_key=bk.key,
                        book_odds=outcome.price,
                        book_implied_prob=american_to_implied_prob(outcome.price),
                        true_prob=true_prob,
                        ev_pct=ev_pct,
                        kelly_pct=kelly_pct,
                    )
                )

    return opportunities


# ---------------------------------------------------------------------------
# Database persistence
# ---------------------------------------------------------------------------

def store_games(db_client: object, games: list[Game]) -> None:
    """Upsert all games into the database."""
    from db import upsert_game

    for game in games:
        upsert_game(
            db_client,
            game_id=game.id,
            sport=game.sport_key,
            home_team=game.home_team,
            away_team=game.away_team,
            start_time=game.commence_time,
        )


def store_odds_snapshots(db_client: object, games: list[Game]) -> None:
    """Store raw odds from every sportsbook/market combination."""
    from db import insert_odds_snapshot

    for game in games:
        for bk in game.bookmakers:
            for mkt in bk.markets:
                if len(mkt.outcomes) != 2:
                    continue
                home_out = mkt.outcomes[0]
                away_out = mkt.outcomes[1]
                insert_odds_snapshot(
                    db_client,
                    game_id=game.id,
                    sportsbook=bk.key,
                    market_type=mkt.key,
                    home_odds=home_out.price,
                    away_odds=away_out.price,
                    spread_value=home_out.point if mkt.key == "spreads" else None,
                    total_value=home_out.point if mkt.key == "totals" else None,
                )


def store_true_lines(db_client: object, games: list[Game]) -> None:
    """Devig sharp lines and store true probabilities."""
    from db import insert_true_line

    for game in games:
        sharp_key = find_sharp_book(game)
        if sharp_key is None:
            continue
        sharp_bk = next(bk for bk in game.bookmakers if bk.key == sharp_key)

        for market_key in ("h2h", "spreads", "totals"):
            sharp_market = get_market(sharp_bk.markets, market_key)
            if sharp_market is None or len(sharp_market.outcomes) != 2:
                continue
            true_home, true_away = calculate_no_vig_probability(
                sharp_market.outcomes[0].price,
                sharp_market.outcomes[1].price,
            )
            no_vig_line = sharp_market.outcomes[0].point
            insert_true_line(
                db_client,
                game_id=game.id,
                market_type=market_key,
                true_home_prob=round(true_home, 6),
                true_away_prob=round(true_away, 6),
                sharp_book=sharp_key,
                no_vig_line=no_vig_line,
            )


def store_ev_opportunities(
    db_client: object, opportunities: list[EVOpportunity]
) -> None:
    """Store +EV opportunities in the database."""
    from db import insert_ev_opportunity

    for opp in opportunities:
        recommended_units = round(opp.kelly_pct * DEFAULT_BANKROLL_UNITS, 2)
        insert_ev_opportunity(
            db_client,
            game_id=opp.game_id,
            sportsbook=opp.book_key,
            market_type=opp.market,
            side=opp.selection + (
                f" {opp.point}" if opp.point is not None else ""
            ),
            book_odds=opp.book_odds,
            book_implied_prob=round(opp.book_implied_prob, 6),
            true_prob=round(opp.true_prob, 6),
            ev_percentage=round(opp.ev_pct, 2),
            kelly_frac=round(opp.kelly_pct, 6),
            recommended_units=recommended_units,
        )


# ---------------------------------------------------------------------------
# Console output
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

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

    # --- Persist to Supabase ---
    try:
        from db import get_supabase

        db = get_supabase()
        print("Storing games...")
        store_games(db, games)
        print("Storing odds snapshots...")
        store_odds_snapshots(db, games)
        print("Storing true lines...")
        store_true_lines(db, games)
    except Exception as e:
        print(f"Warning: DB write failed ({e}). Continuing with console output.")
        db = None

    # --- Scan for +EV ---
    all_opportunities: list[EVOpportunity] = []
    for game in games:
        all_opportunities.extend(scan_game(game))

    if db is not None:
        try:
            print(f"Storing {len(all_opportunities)} EV opportunities...")
            store_ev_opportunities(db, all_opportunities)
            print("All data persisted to Supabase.")
        except Exception as e:
            print(f"Warning: EV opportunity DB write failed ({e}).")

    # --- Console output ---
    print_results(all_opportunities)


if __name__ == "__main__":
    main()
