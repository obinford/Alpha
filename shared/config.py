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

# Sharp books in preference order - first available is used as the "true" line.
SHARP_BOOKS = ["pinnacle", "circa", "betonlineag"]

MARKETS = ["h2h", "spreads", "totals"]

# Player prop markets supported by The Odds API.
PROP_MARKETS = [
    "player_points", "player_rebounds", "player_assists", "player_threes",
    "player_blocks", "player_steals", "player_points_rebounds_assists",
    "player_pass_tds", "player_pass_yds", "player_rush_yds",
    "player_receptions", "player_reception_yds", "player_anytime_td",
]

# Combined list for API requests.
ALL_MARKETS = MARKETS + PROP_MARKETS

# Fractional Kelly multiplier (0.25 = quarter Kelly)
DEFAULT_KELLY_FRACTION = 0.25

# Minimum EV threshold to surface a pick (percentage)
MIN_EV_THRESHOLD = 1.0

# Minimum EV% to grade/track a bet as a "play" — anything below is noise
MIN_GRADE_EV_THRESHOLD = 3.0

# Discord notifications
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")
DISCORD_ENABLED = bool(DISCORD_WEBHOOK_URL)
MIN_ALERT_EV_THRESHOLD = 5.0
