"""RTM proprietary projection engine for NBA player props.

Generates weighted projections using:
  - Recent form (40%): last 5 games
  - Season average (30%): full season baseline
  - Matchup adjustment (20%): opponent defense quality
  - Home/away (10%): home court advantage

Each projection includes mean and standard deviation for use in
Monte Carlo simulation.
"""

from __future__ import annotations

import pandas as pd

from projections.league_averages import (
    get_league_averages,
    get_matchup_factor,
    HOME_BOOST,
)
from projections.stats_cache import get_cached, set_cached

# Weights for the projection model.
WEIGHT_RECENT = 0.40
WEIGHT_SEASON = 0.30
WEIGHT_MATCHUP = 0.20
WEIGHT_HOME_AWAY = 0.10

# Stat categories mapped to their column names and prop types.
STAT_CATEGORIES = {
    "points": {"col": "PTS", "avg_key": "ppg", "std_key": "pts_std", "opp_key": "opp_ppg", "league_key": "avg_opp_ppg"},
    "rebounds": {"col": "REB", "avg_key": "rpg", "std_key": "reb_std", "opp_key": "opp_rpg", "league_key": "avg_opp_rpg"},
    "assists": {"col": "AST", "avg_key": "apg", "std_key": "ast_std", "opp_key": "opp_apg", "league_key": "avg_opp_apg"},
    "threes": {"col": "FG3M", "avg_key": "fg3pg", "std_key": "fg3m_std", "opp_key": "opp_fg3pg", "league_key": "avg_opp_fg3pg"},
    "steals": {"col": "STL", "avg_key": "spg", "std_key": "stl_std", "opp_key": "opp_stlpg", "league_key": "avg_opp_stlpg"},
    "blocks": {"col": "BLK", "avg_key": "bpg", "std_key": "blk_std", "opp_key": "opp_blkpg", "league_key": "avg_opp_blkpg"},
}


class ProjectionEngine:
    """Generates RTM proprietary player projections."""

    def __init__(self, use_mock: bool = False):
        self._use_mock = use_mock

    def _get_player_data(self, player_id: int, season: str = "2025-26"):
        """Get game log and season averages — live or mock."""
        if self._use_mock:
            from projections.mock_data import (
                MOCK_PLAYERS, get_mock_player_averages, generate_mock_game_log,
            )
            p = MOCK_PLAYERS.get(player_id)
            if p is None:
                return None, None
            game_log = generate_mock_game_log(p, 20)
            averages = get_mock_player_averages(player_id)
            return game_log, averages

        from projections.stats_fetcher import (
            get_player_game_log, get_player_season_averages,
        )
        game_log = get_player_game_log(player_id, season, last_n_games=20)
        averages = get_player_season_averages(player_id, season)
        return game_log, averages

    def _get_defense_data(self, team: str, season: str = "2025-26"):
        """Get team defense stats — live or mock."""
        if self._use_mock:
            from projections.mock_data import get_mock_team_defense, MOCK_LEAGUE_AVERAGES
            defense = get_mock_team_defense(team)
            league = MOCK_LEAGUE_AVERAGES
            return defense, league

        from projections.stats_fetcher import get_team_defense_stats, get_league_averages
        defense = get_team_defense_stats(team, season)
        league = get_league_averages(season)
        return defense, league

    def project_player(
        self,
        player_id: int,
        opponent_team: str,
        home_away: str = "home",
        season: str = "2025-26",
    ) -> dict | None:
        """Generate projections for a player against a specific opponent.

        Returns a projection dict with mean and std_dev for each stat category,
        plus a combined PRA projection.
        """
        game_log, averages = self._get_player_data(player_id, season)
        if averages is None:
            return None

        defense, league_avgs = self._get_defense_data(opponent_team, season)

        # Compute game log DataFrame for recent form.
        if game_log:
            df = pd.DataFrame(game_log)
            for col in ["PTS", "REB", "AST", "STL", "BLK", "FG3M", "TOV"]:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
        else:
            df = pd.DataFrame()

        projections: dict[str, dict] = {}
        is_home = home_away.lower() == "home"

        for stat, cfg in STAT_CATEGORIES.items():
            # 1. Recent form (last 5 games).
            if not df.empty and cfg["col"] in df.columns and len(df) >= 3:
                recent = df.head(5)[cfg["col"]].mean()
            else:
                recent = averages.get(cfg["avg_key"], 0)

            # 2. Season average.
            season_avg = averages.get(cfg["avg_key"], 0)

            # 3. Matchup adjustment.
            if defense and league_avgs:
                opp_stat = defense.get(cfg["opp_key"], 0)
                lg_stat = league_avgs.get(cfg["league_key"], 0)
                matchup_factor = get_matchup_factor(opp_stat, lg_stat)
                matchup_projection = season_avg * matchup_factor
            else:
                matchup_projection = season_avg
                matchup_factor = 1.0

            # 4. Home/away boost.
            home_factor = HOME_BOOST.get(stat, 1.0) if is_home else 1.0 / HOME_BOOST.get(stat, 1.0)
            home_projection = season_avg * home_factor

            # Weighted combination.
            mean = (
                WEIGHT_RECENT * recent
                + WEIGHT_SEASON * season_avg
                + WEIGHT_MATCHUP * matchup_projection
                + WEIGHT_HOME_AWAY * home_projection
            )
            mean = max(0, round(mean, 1))

            # Standard deviation from the game log or stored value.
            std = averages.get(cfg["std_key"], mean * 0.3)
            if not df.empty and cfg["col"] in df.columns and len(df) >= 5:
                computed_std = df[cfg["col"]].std()
                if computed_std > 0:
                    std = round(computed_std, 2)

            # Adjust std for matchup variance.
            std = max(0.5, round(std * (1.0 + abs(matchup_factor - 1.0) * 0.2), 2))

            projections[stat] = {"mean": mean, "std_dev": std}

        # PRA (Points + Rebounds + Assists) — derived.
        pra_mean = (
            projections["points"]["mean"]
            + projections["rebounds"]["mean"]
            + projections["assists"]["mean"]
        )
        # PRA std uses sum variance assuming mild positive correlation.
        pra_std = round(
            (projections["points"]["std_dev"] ** 2
             + projections["rebounds"]["std_dev"] ** 2
             + projections["assists"]["std_dev"] ** 2) ** 0.5
            * 1.1,  # 10% correlation boost
            2,
        )
        projections["pts_reb_ast"] = {"mean": round(pra_mean, 1), "std_dev": pra_std}

        # Get player name.
        name = self._get_player_name(player_id)

        return {
            "player_id": player_id,
            "player_name": name,
            "team": averages.get("team", ""),
            "opponent": opponent_team,
            "home_away": home_away,
            "projections": projections,
            "games_played": averages.get("games_played", 0),
            "mpg": averages.get("mpg", 0),
        }

    def _get_player_name(self, player_id: int) -> str:
        """Look up player name by ID."""
        if self._use_mock:
            from projections.mock_data import MOCK_PLAYERS
            p = MOCK_PLAYERS.get(player_id)
            return p["name"] if p else f"Player {player_id}"

        from projections.stats_fetcher import get_active_players
        for p in get_active_players():
            if p["id"] == player_id:
                return p["full_name"]
        return f"Player {player_id}"

    def project_all_players_for_game(
        self,
        home_team: str,
        away_team: str,
        game_date: str | None = None,
        season: str = "2025-26",
    ) -> list[dict]:
        """Project all relevant players (15+ MPG) for a game."""
        projections = []

        # Home team players vs away defense.
        home_players = self._get_team_players(home_team, season)
        for player in home_players:
            proj = self.project_player(
                player["player_id"], away_team, "home", season
            )
            if proj:
                proj["team"] = home_team
                projections.append(proj)

        # Away team players vs home defense.
        away_players = self._get_team_players(away_team, season)
        for player in away_players:
            proj = self.project_player(
                player["player_id"], home_team, "away", season
            )
            if proj:
                proj["team"] = away_team
                projections.append(proj)

        return projections

    def _get_team_players(self, team: str, season: str):
        """Get team roster — live or mock."""
        if self._use_mock:
            from projections.mock_data import get_mock_players_for_team
            return get_mock_players_for_team(team)

        from projections.stats_fetcher import get_players_for_team
        return get_players_for_team(team, season)

    def project_todays_games(
        self,
        games: list[dict] | None = None,
        season: str = "2025-26",
    ) -> dict[str, list[dict]]:
        """Project all players for today's games.

        Args:
            games: List of game dicts with home_team, away_team keys.
                   If None, generates mock games.

        Returns dict of game_id -> list of player projections.
        """
        if games is None:
            if self._use_mock:
                from projections.mock_data import generate_mock_nba_games
                games = generate_mock_nba_games(4)
            else:
                return {}

        result = {}
        for game in games:
            home = game.get("home_team", "")
            away = game.get("away_team", "")
            game_id = game.get("game_id", f"{away}@{home}")

            projs = self.project_all_players_for_game(home, away, season=season)
            if projs:
                result[game_id] = projs

        return result
