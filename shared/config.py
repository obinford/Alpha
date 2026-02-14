"""Shared configuration constants for the RTM Picks Platform."""

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
    # Tennis
    "ATP": "tennis_atp_aus_open",
    "WTA": "tennis_wta_aus_open",
    # Soccer
    "EPL": "soccer_epl",
    "MLS": "soccer_usa_mls",
    # Other
    "CFL": "americanfootball_cfl",
    "WNBA": "basketball_wnba",
    "KBO": "baseball_kbo",
    "NPB": "baseball_npb",
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
    "tennis_atp_aus_open": "ATP Tennis",
    "tennis_wta_aus_open": "WTA Tennis",
    "soccer_epl": "EPL",
    "soccer_usa_mls": "MLS",
    "americanfootball_cfl": "CFL",
    "basketball_wnba": "WNBA",
    "baseball_kbo": "KBO",
    "baseball_npb": "NPB",
}

# Sharp books in preference order - first available is used as the "true" line.
SHARP_BOOKS = ["pinnacle", "circa", "betonlineag"]

MARKETS = ["h2h", "spreads", "totals"]

# Fractional Kelly multiplier (0.25 = quarter Kelly)
DEFAULT_KELLY_FRACTION = 0.25

# Minimum EV threshold to surface a pick (percentage)
MIN_EV_THRESHOLD = 1.0
