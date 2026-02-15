"""League-wide averages for matchup adjustment baseline.

Provides the baseline numbers that determine whether an opponent defense
is above or below average, used to inflate/deflate player projections.
"""

from projections.stats_cache import get_cached, set_cached

# Hardcoded NBA league averages (updated for 2024-25 season).
# These are per-game averages per team, not per player.
DEFAULT_LEAGUE_AVERAGES = {
    "avg_opp_ppg": 112.5,   # Points per game allowed
    "avg_opp_rpg": 43.2,    # Rebounds allowed
    "avg_opp_apg": 25.8,    # Assists allowed
    "avg_opp_fg3pg": 12.6,  # Three-pointers allowed
    "avg_opp_topg": 13.5,   # Turnovers forced
    "avg_opp_stlpg": 7.5,   # Steals allowed
    "avg_opp_blkpg": 4.8,   # Blocks allowed
}

# Per-player league averages (for players averaging 15+ MPG).
PLAYER_LEAGUE_AVERAGES = {
    "ppg": 14.5,
    "rpg": 5.0,
    "apg": 3.2,
    "spg": 0.9,
    "bpg": 0.5,
    "fg3pg": 1.8,
    "topg": 1.8,
    "mpg": 28.0,
}

# Home court advantage factors (multipliers).
HOME_BOOST = {
    "points": 1.03,     # ~3% more points at home
    "rebounds": 1.02,    # ~2% more rebounds
    "assists": 1.02,
    "threes": 1.02,
    "steals": 1.01,
    "blocks": 1.01,
    "pts_reb_ast": 1.025,
}


def get_league_averages(season: str = "2025-26") -> dict:
    """Get league-wide averages, preferring cached live data."""
    cached = get_cached("league_avg", season)
    if cached is not None:
        return cached
    return DEFAULT_LEAGUE_AVERAGES.copy()


def get_matchup_factor(
    opponent_stat: float,
    league_average: float,
) -> float:
    """Calculate matchup adjustment factor.

    > 1.0 means opponent allows MORE than average (good for projections).
    < 1.0 means opponent allows LESS than average (bad for projections).

    Clamped to [0.80, 1.25] to prevent extreme adjustments.
    """
    if league_average <= 0:
        return 1.0
    factor = opponent_stat / league_average
    return max(0.80, min(1.25, factor))
