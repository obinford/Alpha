"""Shared configuration constants for the RTM Picks Platform."""

SUPPORTED_SPORTS = [
    "MLB",
    "NBA",
    "NFL",
    "NHL",
    "CFB",
    "CBB",
]

ODDS_API_SPORT_KEYS = {
    "MLB": "baseball_mlb",
    "NBA": "basketball_nba",
    "NFL": "americanfootball_nfl",
    "NHL": "icehockey_nhl",
    "CFB": "americanfootball_ncaaf",
    "CBB": "basketball_ncaab",
}

SHARP_BOOKS = ["pinnacle", "circa"]

MARKETS = ["h2h", "spreads", "totals"]

# Fractional Kelly multiplier (0.25 = quarter Kelly)
DEFAULT_KELLY_FRACTION = 0.25

# Minimum EV threshold to surface a pick (percentage)
MIN_EV_THRESHOLD = 2.0
