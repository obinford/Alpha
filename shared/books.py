"""Comprehensive sportsbook registry with tiered classification.

Every book the platform can encounter from The Odds API is catalogued here
with its tier, region, display name, and weight for devig calculations.

Tiers:
  sharp      — Set the market. Used as primary devig source.
  exchange   — Near-zero vig. Discover true prices.
  market_maker — Large US books. Moderate sharpness.
  soft       — Slow to adjust. Where +EV edges are found and bet.

Weights (0.0–1.0):
  Used in weighted sharp-book consensus when Pinnacle is unavailable.
  Higher weight = more trusted for true-line estimation.
"""

from typing import TypedDict


class BookInfo(TypedDict):
    name: str
    tier: str       # sharp | exchange | market_maker | soft
    region: str     # us | us2 | eu | us_ex | uk
    weight: float   # 0.0–1.0 for devig weighting


BOOK_REGISTRY: dict[str, BookInfo] = {
    # ---------------------------------------------------------------
    # SHARP BOOKS — set the market.  Primary devig sources.
    # ---------------------------------------------------------------
    "pinnacle": {"name": "Pinnacle", "tier": "sharp", "region": "eu", "weight": 1.0},
    "betonlineag": {"name": "BetOnline", "tier": "sharp", "region": "us", "weight": 0.8},
    "bovada": {"name": "Bovada", "tier": "sharp", "region": "us", "weight": 0.7},
    "lowvig": {"name": "LowVig", "tier": "sharp", "region": "us", "weight": 0.7},
    "circa": {"name": "Circa", "tier": "sharp", "region": "us", "weight": 0.75},

    # ---------------------------------------------------------------
    # EXCHANGES — near-zero vig, discover true prices.
    # ---------------------------------------------------------------
    "novig": {"name": "Novig", "tier": "exchange", "region": "us_ex", "weight": 0.9},
    "betfair_ex_uk": {"name": "Betfair Exchange", "tier": "exchange", "region": "uk", "weight": 0.9},
    "betfair_ex_eu": {"name": "Betfair Exchange EU", "tier": "exchange", "region": "eu", "weight": 0.9},
    "smarkets": {"name": "Smarkets", "tier": "exchange", "region": "uk", "weight": 0.85},
    "matchbook": {"name": "Matchbook", "tier": "exchange", "region": "eu", "weight": 0.85},
    "betopenly": {"name": "BetOpenly", "tier": "exchange", "region": "us_ex", "weight": 0.7},
    "prophetx": {"name": "ProphetX", "tier": "exchange", "region": "us_ex", "weight": 0.6},
    "kalshi": {"name": "Kalshi", "tier": "exchange", "region": "us_ex", "weight": 0.5},
    "polymarket": {"name": "Polymarket", "tier": "exchange", "region": "us_ex", "weight": 0.4},

    # ---------------------------------------------------------------
    # MARKET MAKERS — large US books, moderate sharpness.
    # ---------------------------------------------------------------
    "draftkings": {"name": "DraftKings", "tier": "market_maker", "region": "us", "weight": 0.5},
    "fanduel": {"name": "FanDuel", "tier": "market_maker", "region": "us", "weight": 0.5},
    "betmgm": {"name": "BetMGM", "tier": "market_maker", "region": "us", "weight": 0.5},
    "williamhill_us": {"name": "Caesars", "tier": "market_maker", "region": "us", "weight": 0.5},
    "fanatics": {"name": "Fanatics", "tier": "market_maker", "region": "us", "weight": 0.4},

    # ---------------------------------------------------------------
    # SOFT BOOKS — slow to adjust.  This is where edges are FOUND.
    # ---------------------------------------------------------------
    "espnbet": {"name": "ESPN Bet", "tier": "soft", "region": "us2", "weight": 0.3},
    "hardrockbet": {"name": "Hard Rock Bet", "tier": "soft", "region": "us2", "weight": 0.3},
    "betrivers": {"name": "BetRivers", "tier": "soft", "region": "us", "weight": 0.3},
    "ballybet": {"name": "Bally Bet", "tier": "soft", "region": "us2", "weight": 0.3},
    "betparx": {"name": "BetParx", "tier": "soft", "region": "us2", "weight": 0.3},
    "fliff": {"name": "Fliff", "tier": "soft", "region": "us2", "weight": 0.2},
    "rebet": {"name": "ReBet", "tier": "soft", "region": "us2", "weight": 0.2},
    "betus": {"name": "BetUS", "tier": "soft", "region": "us", "weight": 0.2},
    "mybookieag": {"name": "MyBookie", "tier": "soft", "region": "us", "weight": 0.2},
    "betanysports": {"name": "BetAnySports", "tier": "soft", "region": "us2", "weight": 0.2},

    # --- EU soft books (if eu region enabled) ---
    "onexbet": {"name": "1xBet", "tier": "soft", "region": "eu", "weight": 0.2},
    "sport888": {"name": "888sport", "tier": "soft", "region": "eu", "weight": 0.25},
    "betvictor": {"name": "BetVictor", "tier": "soft", "region": "eu", "weight": 0.25},
    "betway": {"name": "Betway", "tier": "soft", "region": "eu", "weight": 0.25},
    "marathonbet": {"name": "Marathon Bet", "tier": "soft", "region": "eu", "weight": 0.2},
    "unibet_eu": {"name": "Unibet EU", "tier": "soft", "region": "eu", "weight": 0.25},

    # --- UK soft books (if uk region enabled) ---
    "betfair_sb_uk": {"name": "Betfair Sportsbook", "tier": "soft", "region": "uk", "weight": 0.3},
    "paddypower": {"name": "Paddy Power", "tier": "soft", "region": "uk", "weight": 0.25},
    "williamhill": {"name": "William Hill UK", "tier": "soft", "region": "uk", "weight": 0.25},
    "skybet": {"name": "Sky Bet", "tier": "soft", "region": "uk", "weight": 0.2},
    "unibet_uk": {"name": "Unibet UK", "tier": "soft", "region": "uk", "weight": 0.25},
}


def get_book_info(book_key: str) -> BookInfo:
    """Look up a book by its API key.  Returns a default if unknown."""
    return BOOK_REGISTRY.get(book_key, {
        "name": book_key,
        "tier": "unknown",
        "region": "unknown",
        "weight": 0.3,
    })


def get_book_name(book_key: str) -> str:
    """Human-readable display name for a book key."""
    return BOOK_REGISTRY.get(book_key, {}).get("name", book_key)


def get_book_tier(book_key: str) -> str:
    """Return tier classification: sharp, exchange, market_maker, soft, unknown."""
    return BOOK_REGISTRY.get(book_key, {}).get("tier", "unknown")


def get_books_by_tier(tier: str) -> list[str]:
    """Return all book keys matching a tier."""
    return [k for k, v in BOOK_REGISTRY.items() if v["tier"] == tier]


def get_sharp_books() -> list[str]:
    """Return book keys classified as sharp, sorted by weight descending."""
    sharps = [(k, v["weight"]) for k, v in BOOK_REGISTRY.items() if v["tier"] == "sharp"]
    return [k for k, _ in sorted(sharps, key=lambda x: x[1], reverse=True)]


def get_exchange_books() -> list[str]:
    """Return book keys classified as exchange, sorted by weight descending."""
    exchanges = [(k, v["weight"]) for k, v in BOOK_REGISTRY.items() if v["tier"] == "exchange"]
    return [k for k, _ in sorted(exchanges, key=lambda x: x[1], reverse=True)]
