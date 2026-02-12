"""Scraper for The Odds API - fetches live odds from multiple sportsbooks."""


def fetch_odds(sport: str, markets: list[str] | None = None) -> list[dict]:
    """Fetch current odds for a given sport from The Odds API.

    Args:
        sport: Sport key (e.g. 'baseball_mlb', 'basketball_nba').
        markets: List of market types (e.g. ['h2h', 'spreads', 'totals']).

    Returns:
        List of odds data dicts.
    """
    raise NotImplementedError
