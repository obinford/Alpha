"""Shared configuration constants for the RTM Picks Platform."""

import os

# All sports we track, mapped to The Odds API sport keys.
# The Odds API uses specific string keys for each league/sport.
ODDS_API_SPORT_KEYS: dict[str, str] = {
    # Core US sports
    "MLB": "baseball_mlb",
    "NBA": "basketball_nba",
    "NFL": "americanfootball_nfl",
    "NHL": "icehockey_nhl",
    "CFB": "americanfootball_ncaaf",
    "CBB": "basketball_ncaab",
    "WNBA": "basketball_wnba",
    # Major tennis (Grand Slam level)
    "ATP_AUS_OPEN": "tennis_atp_aus_open",
    "ATP_FRENCH_OPEN": "tennis_atp_french_open",
    "ATP_WIMBLEDON": "tennis_atp_wimbledon",
    "ATP_US_OPEN": "tennis_atp_us_open",
    "WTA_AUS_OPEN": "tennis_wta_aus_open",
    "WTA_FRENCH_OPEN": "tennis_wta_french_open",
    "WTA_WIMBLEDON": "tennis_wta_wimbledon",
    "WTA_US_OPEN": "tennis_wta_us_open",
}

SUPPORTED_SPORTS = list(ODDS_API_SPORT_KEYS.keys())

# Human-readable display names for console output.
SPORT_DISPLAY_NAMES: dict[str, str] = {
    "baseball_mlb": "MLB",
    "basketball_nba": "NBA",
    "americanfootball_nfl": "NFL",
    "icehockey_nhl": "NHL",
    "americanfootball_ncaaf": "CFB",
    "basketball_ncaab": "CBB",
    "basketball_wnba": "WNBA",
    "tennis_atp_aus_open": "ATP Australian Open",
    "tennis_atp_french_open": "ATP French Open",
    "tennis_atp_wimbledon": "ATP Wimbledon",
    "tennis_atp_us_open": "ATP US Open",
    "tennis_wta_aus_open": "WTA Australian Open",
    "tennis_wta_french_open": "WTA French Open",
    "tennis_wta_wimbledon": "WTA Wimbledon",
    "tennis_wta_us_open": "WTA US Open",
}

# Sharp books in preference order — first available is used as the "true" line.
# Full book registry with tiers/weights is in shared/books.py.
SHARP_BOOKS = ["pinnacle", "circa", "betonlineag"]

# --- Odds API regions ---
# Each region includes different sportsbooks.  More regions = more price
# disagreement = more +EV edges.  Cost: each region in the request is free
# (single API call can include multiple comma-separated regions).
#
# Available regions:
#   us    — BetOnline, BetMGM, BetRivers, BetUS, Bovada, Caesars,
#           DraftKings, Fanatics, FanDuel, LowVig, MyBookie
#   us2   — BallyBet, BetAnySports, BetParx, ESPN Bet, Fliff, Hard Rock, ReBet
#   eu    — Pinnacle, 1xBet, 888sport, Betfair Exchange, BetVictor, Betway,
#           Matchbook, Marathon Bet  (requires $59+ plan)
#   us_ex — Novig, Kalshi, Polymarket, BetOpenly, ProphetX
#   uk    — Betfair Exchange, Paddy Power, William Hill, Sky Bet, Smarkets
#
# Credit cost per API call = 1 request regardless of how many regions.
# The regions parameter is a comma-separated string.
ACTIVE_REGIONS = ["us", "us2", "eu", "us_ex"]
# Drop "uk" by default to limit response size.  Add if needed.
# Set via env var to override: ODDS_API_REGIONS="us,us2,eu,us_ex,uk"
ODDS_API_REGIONS = os.environ.get(
    "ODDS_API_REGIONS",
    ",".join(ACTIVE_REGIONS),
)

MARKETS = ["h2h", "spreads", "totals"]

# Player prop markets supported by The Odds API (all types).
PROP_MARKETS = [
    "player_points", "player_rebounds", "player_assists", "player_threes",
    "player_blocks", "player_steals", "player_points_rebounds_assists",
    "player_pass_tds", "player_pass_yds", "player_rush_yds",
    "player_receptions", "player_reception_yds", "player_anytime_td",
]

# Sport-specific prop markets — each sport only supports certain props.
# Sending unsupported markets to The Odds API returns 422.
_BASKETBALL_PROPS = [
    "player_points", "player_rebounds", "player_assists", "player_threes",
    "player_blocks", "player_steals", "player_points_rebounds_assists",
]

_FOOTBALL_PROPS = PROP_MARKETS  # football supports all prop markets

_HOCKEY_PROPS = [
    "player_points", "player_assists", "player_blocks", "player_steals",
]

SPORT_PROP_MARKETS: dict[str, list[str]] = {
    "basketball_nba": _BASKETBALL_PROPS,
    "basketball_ncaab": _BASKETBALL_PROPS,
    "basketball_wnba": _BASKETBALL_PROPS,
    "americanfootball_nfl": _FOOTBALL_PROPS,
    "americanfootball_ncaaf": _FOOTBALL_PROPS,
    "icehockey_nhl": _HOCKEY_PROPS,
    # MLB: add when player prop markets are confirmed
    # Tennis: no player props
}


def get_prop_markets_for_sport(sport_key: str) -> list[str]:
    """Return the prop markets available for a given sport key.

    Returns an empty list for sports without prop support (e.g. tennis, MLB).
    """
    return SPORT_PROP_MARKETS.get(sport_key, [])


# Combined list for API requests.
ALL_MARKETS = MARKETS + PROP_MARKETS

# Fractional Kelly multiplier (0.25 = quarter Kelly)
DEFAULT_KELLY_FRACTION = 0.25

# Default bankroll units multiplier for recommended-units sizing.
# kelly_fraction × 100 = units (1 unit = 1% of bankroll).
# e.g. quarter-Kelly fraction 0.0365 × 100 = 3.65u.
DEFAULT_BANKROLL_UNITS = 100.0

# Minimum unit sizing — below this there's no meaningful edge.
MIN_UNIT_SIZE = 0.1

# Minimum EV threshold to surface a pick (percentage)
MIN_EV_THRESHOLD = 1.0

# Minimum EV% to grade/track a bet as a "play" — anything below is noise
MIN_GRADE_EV_THRESHOLD = 3.0

# --- Scanner timing ---
SCAN_INTERVAL_MINUTES = 10
PROP_WINDOW_HOURS = 18.0

# --- Steam detection ---
STEAM_MIN_BOOKS = 3
STEAM_WINDOW_MINUTES = 30
STEAM_DEDUP_MINUTES = 60

# --- CLV tracking ---
CLV_EXPIRATION_HOURS = 48

# --- API ---
ODDS_API_BASE_URL = "https://api.the-odds-api.com/v4/sports"

# --- API credit budgeting ($59 plan = 100,000 credits/month) ---
MONTHLY_API_CREDITS = 100_000
DAILY_CREDIT_BUDGET = MONTHLY_API_CREDITS // 30    # ~3,333 per day
CREDIT_WARNING_THRESHOLD = 0.8                     # warn at 80% daily usage

# Discord notifications
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")
DISCORD_ENABLED = bool(DISCORD_WEBHOOK_URL)
MIN_ALERT_EV_THRESHOLD = 5.0

# --- Intelligence Layers ---
# Stale line detection: minimum EV% to qualify as stale.
STALE_LINE_EV_THRESHOLD = 2.0
# Minimum sharp books that must agree for stale consensus.
STALE_MIN_SHARP_AGREEMENT = 2
# Stale line Discord alert threshold (high-edge stale lines).
STALE_DISCORD_ALERT_EV = 5.0

# Book profiler: books considered sharp (not profiled).
# (Uses SHARP_BOOKS from above.)

# Intelligence score weights in signal engine.
INTEL_STALE_LINE_BONUS = 30
INTEL_SLOW_BOOK_BONUS = 15
INTEL_OPTIMAL_WINDOW_BONUS = 10
INTEL_CORRELATION_BONUS = 15
INTEL_PEAK_TIMING_BONUS = 10
