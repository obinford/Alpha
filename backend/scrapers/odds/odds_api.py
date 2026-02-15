"""Scraper for The Odds API - fetches live odds from multiple sportsbooks."""

import os
from dataclasses import dataclass, field

import httpx


API_BASE = "https://api.the-odds-api.com/v4/sports"


@dataclass
class SportInfo:
    key: str
    group: str
    title: str
    active: bool


@dataclass
class Outcome:
    name: str
    price: int  # American odds
    point: float | None = None  # spread/total line
    description: str | None = None  # player name for prop markets


@dataclass
class Market:
    key: str  # h2h, spreads, totals
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


def get_api_key() -> str:
    """Read API key from environment."""
    key = os.environ.get("THE_ODDS_API_KEY", "")
    if not key:
        raise RuntimeError(
            "THE_ODDS_API_KEY environment variable is not set. "
            "Add it to .env in the project root."
        )
    return key


def fetch_sports() -> list[SportInfo]:
    """Fetch all sports currently available on The Odds API.

    Returns only active (in-season) sports.
    """
    api_key = get_api_key()
    resp = httpx.get(
        API_BASE,
        params={"apiKey": api_key},
        timeout=15,
    )
    resp.raise_for_status()
    return [
        SportInfo(
            key=s["key"],
            group=s.get("group", ""),
            title=s.get("title", s["key"]),
            active=s.get("active", False),
        )
        for s in resp.json()
        if s.get("active", False)
    ]


def fetch_odds(
    sport: str,
    markets: list[str] | None = None,
    regions: str = "us,us2,eu",
) -> list[Game]:
    """Fetch current odds for a given sport from The Odds API.

    Args:
        sport: Sport key (e.g. 'basketball_nba').
        markets: Market types to fetch (default: h2h, spreads, totals).
        regions: Comma-separated regions (default: 'us,us2,eu').
            Includes us2 for BetOnline/Bovada and eu for Pinnacle.

    Returns:
        List of Game objects with bookmaker odds attached.
    """
    if markets is None:
        markets = ["h2h", "spreads", "totals"]

    api_key = get_api_key()

    resp = httpx.get(
        f"{API_BASE}/{sport}/odds",
        params={
            "apiKey": api_key,
            "regions": regions,
            "markets": ",".join(markets),
            "oddsFormat": "american",
        },
        timeout=30,
    )
    resp.raise_for_status()

    games: list[Game] = []
    for g in resp.json():
        bookmakers: list[Bookmaker] = []
        for bk in g.get("bookmakers", []):
            bk_markets: list[Market] = []
            for mkt in bk.get("markets", []):
                outcomes = [
                    Outcome(
                        name=o["name"],
                        price=int(o["price"]),
                        point=o.get("point"),
                        description=o.get("description"),
                    )
                    for o in mkt.get("outcomes", [])
                ]
                bk_markets.append(Market(key=mkt["key"], outcomes=outcomes))
            bookmakers.append(
                Bookmaker(key=bk["key"], title=bk["title"], markets=bk_markets)
            )
        games.append(
            Game(
                id=g["id"],
                sport_key=g["sport_key"],
                home_team=g["home_team"],
                away_team=g["away_team"],
                commence_time=g["commence_time"],
                bookmakers=bookmakers,
            )
        )
    return games
