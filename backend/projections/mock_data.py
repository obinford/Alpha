"""Realistic mock player stats for development and testing.

Used when NBA.com (stats.nba.com) is unreachable. Stats are based on
real 2024-25 season averages for top NBA players. These provide realistic
projections for UI development and system testing.
"""

import random

# Top NBA players with realistic 2024-25 season stats.
MOCK_PLAYERS: dict[int, dict] = {
    2544: {
        "player_id": 2544, "name": "LeBron James", "team": "LAL", "position": "F",
        "ppg": 23.5, "rpg": 7.3, "apg": 9.0, "spg": 1.3, "bpg": 0.5, "fg3pg": 2.2, "topg": 3.5, "mpg": 35.2,
        "pts_std": 7.2, "reb_std": 3.1, "ast_std": 2.8, "stl_std": 0.9, "blk_std": 0.6, "fg3m_std": 1.5, "tov_std": 1.8,
        "games_played": 55,
    },
    203999: {
        "player_id": 203999, "name": "Nikola Jokic", "team": "DEN", "position": "C",
        "ppg": 26.4, "rpg": 12.4, "apg": 9.8, "spg": 1.4, "bpg": 0.9, "fg3pg": 1.1, "topg": 3.0, "mpg": 36.5,
        "pts_std": 8.1, "reb_std": 3.8, "ast_std": 3.2, "stl_std": 1.0, "blk_std": 0.7, "fg3m_std": 1.0, "tov_std": 1.5,
        "games_played": 65,
    },
    1629029: {
        "player_id": 1629029, "name": "Luka Doncic", "team": "DAL", "position": "G",
        "ppg": 28.1, "rpg": 8.3, "apg": 8.1, "spg": 1.5, "bpg": 0.4, "fg3pg": 3.1, "topg": 3.8, "mpg": 36.8,
        "pts_std": 8.5, "reb_std": 3.0, "ast_std": 2.9, "stl_std": 1.1, "blk_std": 0.5, "fg3m_std": 1.7, "tov_std": 1.6,
        "games_played": 50,
    },
    201142: {
        "player_id": 201142, "name": "Kevin Durant", "team": "PHX", "position": "F",
        "ppg": 27.2, "rpg": 6.4, "apg": 5.0, "spg": 0.9, "bpg": 1.2, "fg3pg": 2.0, "topg": 3.1, "mpg": 36.0,
        "pts_std": 6.8, "reb_std": 2.5, "ast_std": 2.1, "stl_std": 0.8, "blk_std": 0.9, "fg3m_std": 1.3, "tov_std": 1.4,
        "games_played": 58,
    },
    203507: {
        "player_id": 203507, "name": "Giannis Antetokounmpo", "team": "MIL", "position": "F",
        "ppg": 31.5, "rpg": 11.9, "apg": 6.5, "spg": 1.2, "bpg": 1.1, "fg3pg": 0.8, "topg": 3.6, "mpg": 35.5,
        "pts_std": 7.8, "reb_std": 3.5, "ast_std": 2.5, "stl_std": 0.9, "blk_std": 0.8, "fg3m_std": 0.9, "tov_std": 1.7,
        "games_played": 60,
    },
    1628369: {
        "player_id": 1628369, "name": "Jayson Tatum", "team": "BOS", "position": "F",
        "ppg": 26.9, "rpg": 8.1, "apg": 4.9, "spg": 1.0, "bpg": 0.6, "fg3pg": 3.0, "topg": 2.5, "mpg": 35.8,
        "pts_std": 7.5, "reb_std": 3.2, "ast_std": 2.3, "stl_std": 0.8, "blk_std": 0.6, "fg3m_std": 1.6, "tov_std": 1.4,
        "games_played": 62,
    },
    203954: {
        "player_id": 203954, "name": "Joel Embiid", "team": "PHI", "position": "C",
        "ppg": 33.0, "rpg": 11.0, "apg": 5.7, "spg": 1.0, "bpg": 1.7, "fg3pg": 1.5, "topg": 3.8, "mpg": 33.8,
        "pts_std": 9.0, "reb_std": 3.6, "ast_std": 2.4, "stl_std": 0.8, "blk_std": 1.0, "fg3m_std": 1.2, "tov_std": 1.6,
        "games_played": 39,
    },
    1629630: {
        "player_id": 1629630, "name": "Ja Morant", "team": "MEM", "position": "G",
        "ppg": 21.2, "rpg": 4.5, "apg": 8.1, "spg": 0.8, "bpg": 0.3, "fg3pg": 1.8, "topg": 3.0, "mpg": 31.5,
        "pts_std": 6.5, "reb_std": 2.2, "ast_std": 2.7, "stl_std": 0.7, "blk_std": 0.4, "fg3m_std": 1.3, "tov_std": 1.5,
        "games_played": 48,
    },
    1629627: {
        "player_id": 1629627, "name": "Zion Williamson", "team": "NOP", "position": "F",
        "ppg": 22.9, "rpg": 5.8, "apg": 5.0, "spg": 1.1, "bpg": 0.7, "fg3pg": 0.5, "topg": 2.8, "mpg": 30.0,
        "pts_std": 7.0, "reb_std": 2.5, "ast_std": 2.3, "stl_std": 0.8, "blk_std": 0.6, "fg3m_std": 0.6, "tov_std": 1.3,
        "games_played": 45,
    },
    1630162: {
        "player_id": 1630162, "name": "Anthony Edwards", "team": "MIN", "position": "G",
        "ppg": 25.9, "rpg": 5.4, "apg": 5.1, "spg": 1.3, "bpg": 0.5, "fg3pg": 3.0, "topg": 2.9, "mpg": 35.0,
        "pts_std": 7.8, "reb_std": 2.6, "ast_std": 2.4, "stl_std": 1.0, "blk_std": 0.5, "fg3m_std": 1.7, "tov_std": 1.5,
        "games_played": 60,
    },
    1628378: {
        "player_id": 1628378, "name": "Donovan Mitchell", "team": "CLE", "position": "G",
        "ppg": 23.2, "rpg": 4.0, "apg": 4.5, "spg": 1.8, "bpg": 0.3, "fg3pg": 2.8, "topg": 2.5, "mpg": 33.5,
        "pts_std": 7.0, "reb_std": 2.0, "ast_std": 2.1, "stl_std": 1.1, "blk_std": 0.4, "fg3m_std": 1.5, "tov_std": 1.3,
        "games_played": 55,
    },
    203081: {
        "player_id": 203081, "name": "Damian Lillard", "team": "MIL", "position": "G",
        "ppg": 24.3, "rpg": 4.4, "apg": 7.0, "spg": 0.9, "bpg": 0.3, "fg3pg": 3.2, "topg": 2.7, "mpg": 35.0,
        "pts_std": 7.5, "reb_std": 2.1, "ast_std": 2.6, "stl_std": 0.7, "blk_std": 0.4, "fg3m_std": 1.8, "tov_std": 1.4,
        "games_played": 58,
    },
    1629636: {
        "player_id": 1629636, "name": "Tyler Herro", "team": "MIA", "position": "G",
        "ppg": 23.8, "rpg": 5.3, "apg": 5.4, "spg": 0.8, "bpg": 0.3, "fg3pg": 3.0, "topg": 2.3, "mpg": 33.5,
        "pts_std": 6.8, "reb_std": 2.4, "ast_std": 2.2, "stl_std": 0.7, "blk_std": 0.4, "fg3m_std": 1.6, "tov_std": 1.2,
        "games_played": 60,
    },
    1628983: {
        "player_id": 1628983, "name": "Shai Gilgeous-Alexander", "team": "OKC", "position": "G",
        "ppg": 30.1, "rpg": 5.5, "apg": 6.2, "spg": 2.0, "bpg": 0.9, "fg3pg": 2.0, "topg": 2.8, "mpg": 34.0,
        "pts_std": 8.0, "reb_std": 2.5, "ast_std": 2.6, "stl_std": 1.2, "blk_std": 0.7, "fg3m_std": 1.4, "tov_std": 1.5,
        "games_played": 68,
    },
    203110: {
        "player_id": 203110, "name": "Darius Garland", "team": "CLE", "position": "G",
        "ppg": 21.5, "rpg": 2.7, "apg": 6.8, "spg": 1.3, "bpg": 0.1, "fg3pg": 2.3, "topg": 2.8, "mpg": 32.0,
        "pts_std": 6.5, "reb_std": 1.8, "ast_std": 2.5, "stl_std": 0.9, "blk_std": 0.3, "fg3m_std": 1.4, "tov_std": 1.4,
        "games_played": 57,
    },
}

# Mock team defense stats (opponent per-game averages).
MOCK_TEAM_DEFENSE: dict[str, dict] = {
    "BOS": {"team": "BOS", "opp_ppg": 108.5, "opp_rpg": 42.0, "opp_apg": 24.5, "opp_fg3pg": 11.8, "opp_topg": 14.5, "opp_stlpg": 7.0, "opp_blkpg": 4.8, "games_played": 70},
    "CLE": {"team": "CLE", "opp_ppg": 107.8, "opp_rpg": 41.5, "opp_apg": 24.0, "opp_fg3pg": 11.5, "opp_topg": 15.0, "opp_stlpg": 7.5, "opp_blkpg": 5.0, "games_played": 70},
    "OKC": {"team": "OKC", "opp_ppg": 106.2, "opp_rpg": 41.0, "opp_apg": 23.8, "opp_fg3pg": 11.2, "opp_topg": 15.5, "opp_stlpg": 8.0, "opp_blkpg": 5.2, "games_played": 70},
    "DEN": {"team": "DEN", "opp_ppg": 112.5, "opp_rpg": 43.5, "opp_apg": 26.0, "opp_fg3pg": 12.8, "opp_topg": 13.5, "opp_stlpg": 6.8, "opp_blkpg": 4.5, "games_played": 70},
    "MIN": {"team": "MIN", "opp_ppg": 109.0, "opp_rpg": 42.5, "opp_apg": 25.0, "opp_fg3pg": 12.0, "opp_topg": 14.0, "opp_stlpg": 7.2, "opp_blkpg": 5.5, "games_played": 70},
    "MIL": {"team": "MIL", "opp_ppg": 114.0, "opp_rpg": 44.0, "opp_apg": 26.5, "opp_fg3pg": 13.0, "opp_topg": 13.0, "opp_stlpg": 6.5, "opp_blkpg": 4.2, "games_played": 70},
    "PHX": {"team": "PHX", "opp_ppg": 113.5, "opp_rpg": 43.5, "opp_apg": 26.2, "opp_fg3pg": 12.5, "opp_topg": 13.5, "opp_stlpg": 6.8, "opp_blkpg": 4.5, "games_played": 70},
    "LAL": {"team": "LAL", "opp_ppg": 111.5, "opp_rpg": 43.0, "opp_apg": 25.5, "opp_fg3pg": 12.2, "opp_topg": 13.8, "opp_stlpg": 7.0, "opp_blkpg": 4.8, "games_played": 70},
    "DAL": {"team": "DAL", "opp_ppg": 113.0, "opp_rpg": 43.8, "opp_apg": 26.0, "opp_fg3pg": 12.8, "opp_topg": 13.2, "opp_stlpg": 6.5, "opp_blkpg": 4.0, "games_played": 70},
    "PHI": {"team": "PHI", "opp_ppg": 112.0, "opp_rpg": 43.0, "opp_apg": 25.8, "opp_fg3pg": 12.5, "opp_topg": 14.0, "opp_stlpg": 7.2, "opp_blkpg": 4.8, "games_played": 70},
    "MIA": {"team": "MIA", "opp_ppg": 110.5, "opp_rpg": 42.5, "opp_apg": 25.0, "opp_fg3pg": 12.0, "opp_topg": 14.5, "opp_stlpg": 7.5, "opp_blkpg": 4.5, "games_played": 70},
    "NYK": {"team": "NYK", "opp_ppg": 109.5, "opp_rpg": 42.0, "opp_apg": 24.5, "opp_fg3pg": 11.8, "opp_topg": 14.5, "opp_stlpg": 7.8, "opp_blkpg": 5.0, "games_played": 70},
    "IND": {"team": "IND", "opp_ppg": 117.0, "opp_rpg": 45.0, "opp_apg": 27.5, "opp_fg3pg": 13.5, "opp_topg": 12.5, "opp_stlpg": 6.0, "opp_blkpg": 3.8, "games_played": 70},
    "SAC": {"team": "SAC", "opp_ppg": 115.5, "opp_rpg": 44.5, "opp_apg": 27.0, "opp_fg3pg": 13.2, "opp_topg": 13.0, "opp_stlpg": 6.5, "opp_blkpg": 4.0, "games_played": 70},
    "MEM": {"team": "MEM", "opp_ppg": 110.0, "opp_rpg": 42.5, "opp_apg": 25.0, "opp_fg3pg": 12.0, "opp_topg": 14.5, "opp_stlpg": 7.5, "opp_blkpg": 5.0, "games_played": 70},
    "NOP": {"team": "NOP", "opp_ppg": 116.0, "opp_rpg": 44.5, "opp_apg": 27.0, "opp_fg3pg": 13.5, "opp_topg": 12.8, "opp_stlpg": 6.2, "opp_blkpg": 3.5, "games_played": 70},
    "ATL": {"team": "ATL", "opp_ppg": 118.0, "opp_rpg": 45.5, "opp_apg": 28.0, "opp_fg3pg": 14.0, "opp_topg": 12.0, "opp_stlpg": 6.0, "opp_blkpg": 3.5, "games_played": 70},
    "GSW": {"team": "GSW", "opp_ppg": 111.0, "opp_rpg": 43.0, "opp_apg": 25.5, "opp_fg3pg": 12.5, "opp_topg": 14.0, "opp_stlpg": 7.0, "opp_blkpg": 4.5, "games_played": 70},
    "HOU": {"team": "HOU", "opp_ppg": 108.0, "opp_rpg": 41.5, "opp_apg": 24.0, "opp_fg3pg": 11.5, "opp_topg": 15.5, "opp_stlpg": 8.0, "opp_blkpg": 5.5, "games_played": 70},
    "CHI": {"team": "CHI", "opp_ppg": 114.5, "opp_rpg": 44.0, "opp_apg": 26.5, "opp_fg3pg": 13.0, "opp_topg": 13.0, "opp_stlpg": 6.5, "opp_blkpg": 4.2, "games_played": 70},
    "TOR": {"team": "TOR", "opp_ppg": 116.5, "opp_rpg": 44.8, "opp_apg": 27.5, "opp_fg3pg": 13.5, "opp_topg": 12.5, "opp_stlpg": 6.2, "opp_blkpg": 3.8, "games_played": 70},
    "CHA": {"team": "CHA", "opp_ppg": 117.5, "opp_rpg": 45.0, "opp_apg": 27.5, "opp_fg3pg": 14.0, "opp_topg": 12.5, "opp_stlpg": 6.0, "opp_blkpg": 3.5, "games_played": 70},
    "BKN": {"team": "BKN", "opp_ppg": 115.0, "opp_rpg": 44.0, "opp_apg": 27.0, "opp_fg3pg": 13.5, "opp_topg": 13.0, "opp_stlpg": 6.5, "opp_blkpg": 4.0, "games_played": 70},
    "ORL": {"team": "ORL", "opp_ppg": 105.5, "opp_rpg": 40.5, "opp_apg": 23.0, "opp_fg3pg": 11.0, "opp_topg": 16.0, "opp_stlpg": 8.5, "opp_blkpg": 5.8, "games_played": 70},
    "LAC": {"team": "LAC", "opp_ppg": 112.5, "opp_rpg": 43.5, "opp_apg": 26.0, "opp_fg3pg": 12.8, "opp_topg": 13.5, "opp_stlpg": 6.8, "opp_blkpg": 4.5, "games_played": 70},
    "DET": {"team": "DET", "opp_ppg": 115.5, "opp_rpg": 44.5, "opp_apg": 27.0, "opp_fg3pg": 13.5, "opp_topg": 13.0, "opp_stlpg": 6.5, "opp_blkpg": 4.0, "games_played": 70},
    "SAS": {"team": "SAS", "opp_ppg": 116.0, "opp_rpg": 44.5, "opp_apg": 27.0, "opp_fg3pg": 13.5, "opp_topg": 13.0, "opp_stlpg": 6.5, "opp_blkpg": 4.0, "games_played": 70},
    "POR": {"team": "POR", "opp_ppg": 117.0, "opp_rpg": 45.0, "opp_apg": 27.5, "opp_fg3pg": 14.0, "opp_topg": 12.5, "opp_stlpg": 6.0, "opp_blkpg": 3.5, "games_played": 70},
    "UTA": {"team": "UTA", "opp_ppg": 116.0, "opp_rpg": 44.5, "opp_apg": 27.0, "opp_fg3pg": 13.5, "opp_topg": 13.0, "opp_stlpg": 6.5, "opp_blkpg": 4.0, "games_played": 70},
    "WAS": {"team": "WAS", "opp_ppg": 119.0, "opp_rpg": 46.0, "opp_apg": 28.5, "opp_fg3pg": 14.5, "opp_topg": 12.0, "opp_stlpg": 5.5, "opp_blkpg": 3.2, "games_played": 70},
}

# League averages (2024-25).
MOCK_LEAGUE_AVERAGES = {
    "avg_opp_ppg": 112.5,
    "avg_opp_rpg": 43.2,
    "avg_opp_apg": 25.8,
    "avg_opp_fg3pg": 12.6,
    "avg_opp_topg": 13.5,
}

# Default team rosters mapping team -> list of player_ids.
MOCK_TEAM_ROSTERS: dict[str, list[int]] = {
    "LAL": [2544],
    "DEN": [203999],
    "DAL": [1629029],
    "PHX": [201142],
    "MIL": [203507, 203081],
    "BOS": [1628369],
    "PHI": [203954],
    "MEM": [1629630],
    "NOP": [1629627],
    "MIN": [1630162],
    "CLE": [1628378, 203110],
    "MIA": [1629636],
    "OKC": [1628983],
}


def generate_mock_game_log(player: dict, n_games: int = 20) -> list[dict]:
    """Generate a realistic game log for a player."""
    logs = []
    teams = list(MOCK_TEAM_DEFENSE.keys())
    for i in range(n_games):
        opp = random.choice(teams)
        # Add noise around their averages.
        pts = max(0, round(random.gauss(player["ppg"], player["pts_std"])))
        reb = max(0, round(random.gauss(player["rpg"], player["reb_std"])))
        ast = max(0, round(random.gauss(player["apg"], player["ast_std"])))
        stl = max(0, round(random.gauss(player["spg"], player["stl_std"])))
        blk = max(0, round(random.gauss(player["bpg"], player["blk_std"])))
        fg3m = max(0, round(random.gauss(player["fg3pg"], player["fg3m_std"])))
        tov = max(0, round(random.gauss(player["topg"], player["tov_std"])))
        logs.append({
            "GAME_DATE": f"2025-{random.randint(10,12):02d}-{random.randint(1,28):02d}",
            "MATCHUP": f"{player['team']} vs. {opp}",
            "WL": random.choice(["W", "L"]),
            "MIN": round(player["mpg"] + random.gauss(0, 3), 1),
            "PTS": pts, "REB": reb, "AST": ast,
            "STL": stl, "BLK": blk, "FG3M": fg3m, "TOV": tov,
            "FGM": max(0, round(pts * 0.38 + random.gauss(0, 2))),
            "FGA": max(1, round(pts * 0.38 / 0.47 + random.gauss(0, 3))),
            "FTM": max(0, round(pts * 0.2 + random.gauss(0, 1))),
            "FTA": max(0, round(pts * 0.25 + random.gauss(0, 1))),
            "PLUS_MINUS": random.randint(-15, 20),
        })
    return logs


def get_mock_player_averages(player_id: int) -> dict | None:
    """Get mock season averages for a player."""
    p = MOCK_PLAYERS.get(player_id)
    if p is None:
        return None
    return {
        "ppg": p["ppg"], "rpg": p["rpg"], "apg": p["apg"],
        "spg": p["spg"], "bpg": p["bpg"], "fg3pg": p["fg3pg"],
        "topg": p["topg"], "mpg": p["mpg"],
        "games_played": p["games_played"],
        "pts_std": p["pts_std"], "reb_std": p["reb_std"],
        "ast_std": p["ast_std"], "stl_std": p["stl_std"],
        "blk_std": p["blk_std"], "fg3m_std": p["fg3m_std"],
        "tov_std": p["tov_std"],
        "fgpct": 47.5, "ftpct": 78.0, "fg3pct": 36.0,
    }


def get_mock_team_defense(team: str) -> dict | None:
    """Get mock defense stats for a team."""
    return MOCK_TEAM_DEFENSE.get(team.upper())


def get_mock_players_for_team(team: str) -> list[dict]:
    """Get mock roster for a team (players with 15+ MPG)."""
    player_ids = MOCK_TEAM_ROSTERS.get(team.upper(), [])
    result = []
    for pid in player_ids:
        p = MOCK_PLAYERS.get(pid)
        if p:
            result.append({
                "player_id": pid,
                "name": p["name"],
                "team": p["team"],
                "position": p["position"],
                "averages": get_mock_player_averages(pid),
            })
    return result


def generate_mock_nba_games(n_games: int = 4) -> list[dict]:
    """Generate realistic mock NBA games for today."""
    teams = list(MOCK_TEAM_ROSTERS.keys())
    random.shuffle(teams)
    games = []
    for i in range(0, min(n_games * 2, len(teams)), 2):
        home = teams[i]
        away = teams[i + 1] if i + 1 < len(teams) else teams[0]
        games.append({
            "game_id": f"mock_nba_{home}_{away}",
            "sport": "basketball_nba",
            "home_team": home,
            "away_team": away,
            "start_time": f"2026-02-15T{19 + i // 2}:00:00Z",
        })
    return games
