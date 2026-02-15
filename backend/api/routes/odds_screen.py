"""Odds comparison screen API — live odds across all sportsbooks for a sport."""

from dataclasses import asdict

from fastapi import APIRouter, Query

from shared.config import ODDS_API_SPORT_KEYS, SHARP_BOOKS

router = APIRouter()


@router.get("/{sport}")
def get_odds_comparison(
    sport: str,
    market: str = Query("h2h", description="Market type: h2h, spreads, totals"),
) -> dict:
    """Fetch live odds for a sport and format for comparison display.

    Returns games with odds from all available sportsbooks side by side.
    """
    from scrapers.odds.odds_api import fetch_odds

    # Map short sport names to API keys.
    sport_key = ODDS_API_SPORT_KEYS.get(sport.upper(), sport)

    try:
        games = fetch_odds(sport_key, markets=[market])
    except Exception as e:
        return {"error": str(e), "games": [], "books": []}

    # Collect all unique bookmakers across all games.
    all_books: dict[str, str] = {}  # key -> title
    for game in games:
        for bk in game.bookmakers:
            all_books[bk.key] = bk.title

    # Sort: sharp books first, then alphabetical.
    sharp_set = set(SHARP_BOOKS)
    sorted_books = sorted(
        all_books.items(),
        key=lambda x: (0 if x[0] in sharp_set else 1, x[1]),
    )

    result_games = []
    for game in games:
        # Build a dict of bookmaker -> odds for this game.
        book_odds: dict[str, dict] = {}
        for bk in game.bookmakers:
            for mkt in bk.markets:
                if mkt.key != market:
                    continue
                odds_data = {}
                for outcome in mkt.outcomes:
                    key = outcome.name  # Home team, Away team, Over, Under, Draw
                    odds_data[key] = {
                        "odds": outcome.price,
                        "point": outcome.point,
                    }
                book_odds[bk.key] = odds_data

        # Find the best odds for each side.
        sides: dict[str, dict] = {}  # side_name -> {best_odds, best_book}
        for bk_key, odds_map in book_odds.items():
            for side_name, data in odds_map.items():
                if side_name not in sides:
                    sides[side_name] = {"best_odds": data["odds"], "best_book": bk_key}
                elif data["odds"] > sides[side_name]["best_odds"]:
                    sides[side_name] = {"best_odds": data["odds"], "best_book": bk_key}

        result_games.append({
            "id": game.id,
            "home_team": game.home_team,
            "away_team": game.away_team,
            "commence_time": game.commence_time,
            "book_odds": book_odds,
            "best_odds": sides,
        })

    return {
        "sport": sport_key,
        "market": market,
        "books": [{"key": k, "title": v, "is_sharp": k in sharp_set} for k, v in sorted_books],
        "games": result_games,
    }


@router.get("/")
def list_sports() -> dict:
    """List available sports for odds comparison."""
    return {
        "sports": [
            {"key": v, "label": k}
            for k, v in ODDS_API_SPORT_KEYS.items()
        ]
    }
