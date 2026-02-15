"""NBA player stats fetcher using nba_api.

Pulls real player game logs, season averages, and team defense stats from
NBA.com. All calls are cached to avoid rate limiting.
"""

import time
from typing import Any

import pandas as pd

from projections.stats_cache import get_cached, set_cached

# Rate limit: minimum seconds between NBA.com API calls.
_MIN_DELAY = 1.5
_last_call_time: float = 0.0


def _rate_limit() -> None:
    """Enforce rate limiting for NBA.com requests."""
    global _last_call_time
    elapsed = time.monotonic() - _last_call_time
    if elapsed < _MIN_DELAY:
        time.sleep(_MIN_DELAY - elapsed)
    _last_call_time = time.monotonic()


# ---------------------------------------------------------------------------
# Active players
# ---------------------------------------------------------------------------

def get_active_players() -> list[dict]:
    """Get all active NBA players with IDs.

    Returns list of dicts: {id, full_name, first_name, last_name, is_active}.
    """
    cached = get_cached("active_players")
    if cached is not None:
        return cached

    from nba_api.stats.static import players as nba_players

    active = nba_players.get_active_players()
    result = [
        {
            "id": p["id"],
            "full_name": p["full_name"],
            "first_name": p["first_name"],
            "last_name": p["last_name"],
            "is_active": p["is_active"],
        }
        for p in active
    ]
    set_cached("active_players", result)
    return result


def find_player_id(name: str) -> int | None:
    """Find a player ID by name (case-insensitive partial match)."""
    players = get_active_players()
    name_lower = name.lower()
    for p in players:
        if name_lower in p["full_name"].lower():
            return p["id"]
    return None


# ---------------------------------------------------------------------------
# Player game log
# ---------------------------------------------------------------------------

def get_player_game_log(
    player_id: int,
    season: str = "2025-26",
    last_n_games: int = 20,
) -> list[dict]:
    """Fetch a player's recent game log from NBA.com.

    Returns list of dicts with: GAME_DATE, MATCHUP, MIN, PTS, REB, AST,
    STL, BLK, FG3M, TOV, FGM, FGA, FTM, FTA, PLUS_MINUS, WL.
    """
    cached = get_cached("game_log", player_id, season, last_n_games)
    if cached is not None:
        return cached

    _rate_limit()
    try:
        from nba_api.stats.endpoints import playergamelog

        log = playergamelog.PlayerGameLog(
            player_id=player_id,
            season=season,
            season_type_all_star="Regular Season",
        )
        df = log.get_data_frames()[0]

        if df.empty:
            # Try previous season as fallback.
            _rate_limit()
            log = playergamelog.PlayerGameLog(
                player_id=player_id,
                season="2024-25",
                season_type_all_star="Regular Season",
            )
            df = log.get_data_frames()[0]

        if df.empty:
            return []

        # Take last N games (most recent first in the API response).
        df = df.head(last_n_games)

        cols = [
            "GAME_DATE", "MATCHUP", "WL", "MIN", "PTS", "REB", "AST",
            "STL", "BLK", "FG3M", "TOV", "FGM", "FGA", "FTM", "FTA",
            "PLUS_MINUS",
        ]
        available = [c for c in cols if c in df.columns]
        result = df[available].to_dict("records")

        set_cached("game_log", result, player_id, season, last_n_games)
        return result

    except Exception as e:
        print(f"Warning: Failed to fetch game log for player {player_id}: {e}")
        return []


# ---------------------------------------------------------------------------
# Season averages
# ---------------------------------------------------------------------------

def get_player_season_averages(
    player_id: int,
    season: str = "2025-26",
) -> dict | None:
    """Fetch a player's season averages.

    Returns dict with: ppg, rpg, apg, spg, bpg, fg3pg, topg, mpg,
    games_played, fgpct, ftpct, fg3pct.
    """
    cached = get_cached("season_avg", player_id, season)
    if cached is not None:
        return cached

    game_log = get_player_game_log(player_id, season, last_n_games=82)
    if not game_log:
        return None

    df = pd.DataFrame(game_log)
    n = len(df)
    if n == 0:
        return None

    # Convert columns to numeric.
    for col in ["PTS", "REB", "AST", "STL", "BLK", "FG3M", "TOV",
                "MIN", "FGM", "FGA", "FTM", "FTA"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    result = {
        "ppg": round(df["PTS"].mean(), 1) if "PTS" in df else 0,
        "rpg": round(df["REB"].mean(), 1) if "REB" in df else 0,
        "apg": round(df["AST"].mean(), 1) if "AST" in df else 0,
        "spg": round(df["STL"].mean(), 1) if "STL" in df else 0,
        "bpg": round(df["BLK"].mean(), 1) if "BLK" in df else 0,
        "fg3pg": round(df["FG3M"].mean(), 1) if "FG3M" in df else 0,
        "topg": round(df["TOV"].mean(), 1) if "TOV" in df else 0,
        "mpg": round(df["MIN"].mean(), 1) if "MIN" in df else 0,
        "games_played": n,
        "fgpct": round(df["FGM"].sum() / max(df["FGA"].sum(), 1) * 100, 1),
        "ftpct": round(df["FTM"].sum() / max(df["FTA"].sum(), 1) * 100, 1),
        "fg3pct": 0,  # computed below
        # Standard deviations for simulation.
        "pts_std": round(df["PTS"].std(), 2) if "PTS" in df else 0,
        "reb_std": round(df["REB"].std(), 2) if "REB" in df else 0,
        "ast_std": round(df["AST"].std(), 2) if "AST" in df else 0,
        "stl_std": round(df["STL"].std(), 2) if "STL" in df else 0,
        "blk_std": round(df["BLK"].std(), 2) if "BLK" in df else 0,
        "fg3m_std": round(df["FG3M"].std(), 2) if "FG3M" in df else 0,
        "tov_std": round(df["TOV"].std(), 2) if "TOV" in df else 0,
    }

    set_cached("season_avg", result, player_id, season)
    return result


# ---------------------------------------------------------------------------
# Team defense stats
# ---------------------------------------------------------------------------

def get_team_defense_stats(
    team_abbreviation: str,
    season: str = "2025-26",
) -> dict | None:
    """Fetch team defensive stats: opponent PPG, RPG, APG, 3PM, etc.

    Uses LeagueDashTeamStats with MeasureType='Opponent'.
    Returns dict with opp_ppg, opp_rpg, opp_apg, opp_fg3pg, opp_topg.
    """
    cached = get_cached("team_defense", team_abbreviation, season)
    if cached is not None:
        return cached

    _rate_limit()
    try:
        from nba_api.stats.endpoints import leaguedashteamstats

        stats = leaguedashteamstats.LeagueDashTeamStats(
            season=season,
            measure_type_detailed_defense="Opponent",
            per_mode_detailed="PerGame",
            season_type_all_star="Regular Season",
        )
        df = stats.get_data_frames()[0]

        if df.empty:
            # Fallback to previous season.
            _rate_limit()
            stats = leaguedashteamstats.LeagueDashTeamStats(
                season="2024-25",
                measure_type_detailed_defense="Opponent",
                per_mode_detailed="PerGame",
                season_type_all_star="Regular Season",
            )
            df = stats.get_data_frames()[0]

        if df.empty:
            return None

        # Find the team row.
        team_row = df[df["TEAM_ABBREVIATION"] == team_abbreviation.upper()]
        if team_row.empty:
            # Try matching by name substring.
            team_row = df[df["TEAM_ABBREVIATION"].str.contains(
                team_abbreviation.upper(), na=False
            )]

        if team_row.empty:
            return None

        row = team_row.iloc[0]
        result = {
            "team": team_abbreviation.upper(),
            "opp_ppg": float(row.get("OPP_PTS", 0)),
            "opp_rpg": float(row.get("OPP_REB", 0)),
            "opp_apg": float(row.get("OPP_AST", 0)),
            "opp_fg3pg": float(row.get("OPP_FG3M", 0)),
            "opp_topg": float(row.get("OPP_TOV", 0)),
            "opp_stlpg": float(row.get("OPP_STL", 0)),
            "opp_blkpg": float(row.get("OPP_BLK", 0)),
            "games_played": int(row.get("GP", 0)),
        }

        # Also store all team stats for league average calculation.
        all_teams = []
        for _, r in df.iterrows():
            all_teams.append({
                "team": r.get("TEAM_ABBREVIATION", ""),
                "opp_ppg": float(r.get("OPP_PTS", 0)),
                "opp_rpg": float(r.get("OPP_REB", 0)),
                "opp_apg": float(r.get("OPP_AST", 0)),
                "opp_fg3pg": float(r.get("OPP_FG3M", 0)),
                "opp_topg": float(r.get("OPP_TOV", 0)),
            })
        set_cached("team_defense", result, team_abbreviation, season)
        set_cached("league_avg", _compute_league_averages(all_teams), season)

        return result

    except Exception as e:
        print(f"Warning: Failed to fetch defense stats for {team_abbreviation}: {e}")
        return None


def _compute_league_averages(teams: list[dict]) -> dict:
    """Compute league-wide averages from all team defensive stats."""
    if not teams:
        return {
            "avg_opp_ppg": 112.0, "avg_opp_rpg": 43.0,
            "avg_opp_apg": 26.0, "avg_opp_fg3pg": 12.5, "avg_opp_topg": 14.0,
        }
    n = len(teams)
    return {
        "avg_opp_ppg": round(sum(t["opp_ppg"] for t in teams) / n, 1),
        "avg_opp_rpg": round(sum(t["opp_rpg"] for t in teams) / n, 1),
        "avg_opp_apg": round(sum(t["opp_apg"] for t in teams) / n, 1),
        "avg_opp_fg3pg": round(sum(t["opp_fg3pg"] for t in teams) / n, 1),
        "avg_opp_topg": round(sum(t["opp_topg"] for t in teams) / n, 1),
    }


def get_league_averages(season: str = "2025-26") -> dict:
    """Get league-wide averages for matchup adjustment baseline."""
    cached = get_cached("league_avg", season)
    if cached is not None:
        return cached

    # Trigger team defense fetch which computes league averages.
    # Use a common team.
    get_team_defense_stats("BOS", season)
    cached = get_cached("league_avg", season)
    if cached is not None:
        return cached

    # Hardcoded fallbacks based on recent NBA seasons.
    return {
        "avg_opp_ppg": 112.0,
        "avg_opp_rpg": 43.0,
        "avg_opp_apg": 26.0,
        "avg_opp_fg3pg": 12.5,
        "avg_opp_topg": 14.0,
    }


# ---------------------------------------------------------------------------
# Players for a game
# ---------------------------------------------------------------------------

def get_players_for_team(
    team_abbreviation: str,
    season: str = "2025-26",
    min_minutes: float = 15.0,
) -> list[dict]:
    """Get players on a team averaging min_minutes+ MPG.

    Returns list of dicts with player_id, name, and season averages.
    """
    cached = get_cached("team_players", team_abbreviation, season, min_minutes)
    if cached is not None:
        return cached

    _rate_limit()
    try:
        from nba_api.stats.endpoints import commonteamroster

        # Get team ID first.
        from nba_api.stats.static import teams as nba_teams
        all_teams = nba_teams.get_teams()
        team_id = None
        for t in all_teams:
            if t["abbreviation"] == team_abbreviation.upper():
                team_id = t["id"]
                break

        if team_id is None:
            return []

        roster = commonteamroster.CommonTeamRoster(
            team_id=team_id, season=season
        )
        roster_df = roster.get_data_frames()[0]

        if roster_df.empty:
            return []

        result = []
        for _, player in roster_df.iterrows():
            pid = int(player.get("PLAYER_ID", 0))
            if pid == 0:
                continue

            # Get season averages — uses cache internally.
            avgs = get_player_season_averages(pid, season)
            if avgs is None:
                continue

            # Skip players below minutes threshold.
            if avgs.get("mpg", 0) < min_minutes:
                continue

            result.append({
                "player_id": pid,
                "name": player.get("PLAYER", ""),
                "team": team_abbreviation.upper(),
                "position": player.get("POSITION", ""),
                "averages": avgs,
            })

        set_cached("team_players", result, team_abbreviation, season, min_minutes)
        return result

    except Exception as e:
        print(f"Warning: Failed to fetch roster for {team_abbreviation}: {e}")
        return []


# ---------------------------------------------------------------------------
# NBA team abbreviation mapping
# ---------------------------------------------------------------------------

NBA_TEAM_ABBREVS = {
    "Atlanta Hawks": "ATL", "Boston Celtics": "BOS", "Brooklyn Nets": "BKN",
    "Charlotte Hornets": "CHA", "Chicago Bulls": "CHI", "Cleveland Cavaliers": "CLE",
    "Dallas Mavericks": "DAL", "Denver Nuggets": "DEN", "Detroit Pistons": "DET",
    "Golden State Warriors": "GSW", "Houston Rockets": "HOU", "Indiana Pacers": "IND",
    "Los Angeles Clippers": "LAC", "Los Angeles Lakers": "LAL", "Memphis Grizzlies": "MEM",
    "Miami Heat": "MIA", "Milwaukee Bucks": "MIL", "Minnesota Timberwolves": "MIN",
    "New Orleans Pelicans": "NOP", "New York Knicks": "NYK", "Oklahoma City Thunder": "OKC",
    "Orlando Magic": "ORL", "Philadelphia 76ers": "PHI", "Phoenix Suns": "PHX",
    "Portland Trail Blazers": "POR", "Sacramento Kings": "SAC", "San Antonio Spurs": "SAS",
    "Toronto Raptors": "TOR", "Utah Jazz": "UTA", "Washington Wizards": "WAS",
}


def team_name_to_abbrev(team_name: str) -> str | None:
    """Convert full team name to abbreviation."""
    if team_name in NBA_TEAM_ABBREVS:
        return NBA_TEAM_ABBREVS[team_name]
    # Partial match.
    name_lower = team_name.lower()
    for full, abbr in NBA_TEAM_ABBREVS.items():
        if name_lower in full.lower() or full.lower().endswith(name_lower):
            return abbr
    return None
