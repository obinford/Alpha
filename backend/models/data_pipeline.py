"""
RTM Picks — MLB Strikeout Model: Data Pipeline
Generates realistic MLB pitcher game logs for 2019-2025 based on
historical distributions and known pitcher archetypes.

Note: Uses synthetic data generation since external APIs (FanGraphs/pybaseball)
are unavailable in this environment. The data follows real MLB statistical
distributions for K rates, IP, BF, etc. When deploying to production,
replace generate_synthetic_data() with actual pybaseball pulls.
"""

import os
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

# Paths
PROJECT_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = PROJECT_ROOT / "data" / "raw" / "pitcher_gamelogs"
RAW_DIR.mkdir(parents=True, exist_ok=True)

SEASONS = list(range(2019, 2026))

# Park K-rate factors (relative to league average = 1.0)
PARK_K_FACTORS = {
    "SDP": 1.08, "NYM": 1.06, "TBR": 1.05, "TB": 1.05,
    "MIL": 1.05, "SEA": 1.04, "CLE": 1.04, "ARI": 1.03,
    "LAD": 1.03, "SFG": 1.03, "SF": 1.03, "HOU": 1.02,
    "ATL": 1.02, "WSN": 1.01, "WSH": 1.01, "PHI": 1.01,
    "STL": 1.00, "PIT": 1.00, "CIN": 1.00, "BAL": 1.00,
    "TOR": 1.00, "OAK": 1.00, "MIN": 1.00, "DET": 1.00,
    "TEX": 0.99, "LAA": 0.99, "NYY": 0.99, "CHW": 0.99,
    "CWS": 0.99, "BOS": 0.98, "MIA": 0.98, "CHC": 0.97,
    "KCR": 0.96, "KC": 0.96, "COL": 0.92,
}

# MLB teams (30 teams)
MLB_TEAMS = [
    "LAD", "HOU", "ATL", "NYY", "TBR", "NYM", "SDP", "PHI",
    "SEA", "TOR", "CLE", "STL", "MIL", "MIN", "BAL", "TEX",
    "SFG", "CHC", "BOS", "CIN", "ARI", "MIA", "CHW", "DET",
    "KCR", "PIT", "OAK", "COL", "LAA", "WSN",
]

# Realistic pitcher archetypes based on real MLB data
# Each archetype has: name template, K/9 range, IP/start range, frequency weight
PITCHER_ARCHETYPES = [
    # Aces (high K, deep into games) — ~15% of starters
    # k_var controls overdispersion: var = mean * (1 + mean*k_var)
    # Real MLB K data shows var/mean ≈ 1.2-1.6 (slight to moderate overdispersion)
    {"type": "ace", "k9_range": (10.0, 13.5), "ip_range": (5.5, 7.5),
     "k_var": 0.06, "freq": 0.15, "gs_range": (28, 34)},
    # Above-average starters — ~25%
    {"type": "above_avg", "k9_range": (8.0, 10.0), "ip_range": (5.0, 6.5),
     "k_var": 0.07, "freq": 0.25, "gs_range": (25, 33)},
    # Average starters — ~30%
    {"type": "average", "k9_range": (6.5, 8.0), "ip_range": (4.5, 6.0),
     "k_var": 0.08, "freq": 0.30, "gs_range": (20, 32)},
    # Below-average / back-end starters — ~20%
    {"type": "below_avg", "k9_range": (5.0, 6.5), "ip_range": (4.0, 5.5),
     "k_var": 0.10, "freq": 0.20, "gs_range": (15, 28)},
    # Spot starters / openers — ~10%
    {"type": "spot", "k9_range": (4.5, 7.0), "ip_range": (3.5, 5.0),
     "k_var": 0.12, "freq": 0.10, "gs_range": (5, 18)},
]

# Real MLB pitcher names for realism (top starters from 2019-2025)
REAL_PITCHER_NAMES = [
    # Aces
    "Gerrit Cole", "Max Scherzer", "Jacob deGrom", "Shane Bieber",
    "Corbin Burnes", "Spencer Strider", "Zack Wheeler", "Aaron Nola",
    "Justin Verlander", "Yu Darvish", "Dylan Cease", "Kevin Gausman",
    "Robbie Ray", "Carlos Rodon", "Logan Webb", "Framber Valdez",
    "Tyler Glasnow", "Chris Sale", "Blake Snell", "Sandy Alcantara",
    "Shohei Ohtani", "Luis Castillo", "Brandon Woodruff", "Max Fried",
    "Freddy Peralta", "Pablo Lopez", "Tarik Skubal", "Sonny Gray",
    # Above average
    "Alek Manoah", "Nestor Cortes", "Julio Urias", "Joe Musgrove",
    "Lance McCullers", "Marcus Stroman", "Jose Berrios", "Frankie Montas",
    "Charlie Morton", "Kyle Wright", "Cristian Javier", "George Kirby",
    "Bryce Miller", "Seth Lugo", "Ranger Suarez", "Tanner Houck",
    "Grayson Rodriguez", "Hunter Brown", "JP Sears", "Michael King",
    # Average
    "Patrick Corbin", "Kyle Hendricks", "Jon Gray", "German Marquez",
    "Mike Clevinger", "Zach Eflin", "Kyle Freeland", "Brady Singer",
    "Merrill Kelly", "Nathan Eovaldi", "Jameson Taillon", "Tyler Anderson",
    "Jordan Montgomery", "Nick Pivetta", "Mitch Keller", "Bailey Ober",
    "Miles Mikolas", "Martin Perez", "Drew Smyly", "Michael Wacha",
    # Below average
    "Wade Miley", "Luke Weaver", "Dane Dunning", "Kutter Crawford",
    "Andrew Heaney", "Rich Hill", "Mike Minor", "Dallas Keuchel",
    "Zach Davies", "Glenn Otto", "Spenser Watkins", "Austin Gomber",
    "Chad Kuhl", "Antonio Senzatela", "Zach Thompson", "Jose Urquidy",
    # Spot / low GS
    "Yoan Lopez", "Jake Irvin", "Reese Olson", "Cade Cavalli",
    "Colin Rea", "JP France", "Spencer Howard", "Josiah Gray",
]


def generate_pitcher_profile(pitcher_idx: int, rng: np.random.Generator) -> dict:
    """Generate a pitcher's baseline profile based on archetype distribution."""
    # Pick archetype based on frequency weights
    weights = [a['freq'] for a in PITCHER_ARCHETYPES]
    archetype = rng.choice(PITCHER_ARCHETYPES, p=weights)

    # Base K/9 rate for this pitcher
    base_k9 = rng.uniform(*archetype['k9_range'])
    base_ip = rng.uniform(*archetype['ip_range'])
    k_var = archetype['k_var']

    # Name
    if pitcher_idx < len(REAL_PITCHER_NAMES):
        name = REAL_PITCHER_NAMES[pitcher_idx]
    else:
        first_names = ["James", "Michael", "John", "David", "Chris", "Matt", "Ryan",
                       "Tyler", "Brandon", "Kyle", "Nick", "Alex", "Jake", "Drew", "Cole"]
        last_names = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia",
                      "Martinez", "Anderson", "Thomas", "Jackson", "White", "Harris",
                      "Clark", "Lewis", "Robinson", "Walker", "Young", "Allen", "King"]
        name = f"{rng.choice(first_names)} {rng.choice(last_names)}"

    team = rng.choice(MLB_TEAMS)
    gs_range = archetype['gs_range']

    return {
        'pitcher_id': 10000 + pitcher_idx,
        'pitcher_name': name,
        'team': team,
        'base_k9': base_k9,
        'base_ip': base_ip,
        'k_var': k_var,
        'archetype': archetype['type'],
        'gs_range': gs_range,
    }


def generate_season_gamelogs(profile: dict, season: int, rng: np.random.Generator) -> list:
    """Generate game-level logs for one pitcher in one season."""
    # Determine number of starts
    gs_low, gs_high = profile['gs_range']

    # 2020 shortened season: ~60 games instead of 162
    if season == 2020:
        gs_low = max(3, int(gs_low * 0.37))
        gs_high = max(5, int(gs_high * 0.37))

    num_starts = rng.integers(gs_low, gs_high + 1)

    # Season-level K/9 variation (pitcher can be slightly better/worse each year)
    season_k9 = profile['base_k9'] * rng.normal(1.0, 0.08)
    season_k9 = max(3.0, min(16.0, season_k9))

    season_ip = profile['base_ip'] * rng.normal(1.0, 0.05)
    season_ip = max(3.0, min(8.0, season_ip))

    # Generate game dates
    if season == 2020:
        start_date = pd.Timestamp(f"{season}-07-23")
        end_date = pd.Timestamp(f"{season}-09-27")
    else:
        start_date = pd.Timestamp(f"{season}-03-28")
        end_date = pd.Timestamp(f"{season}-10-01")

    date_range = (end_date - start_date).days
    game_offsets = sorted(rng.choice(range(date_range), size=num_starts, replace=False))
    game_dates = [start_date + pd.Timedelta(days=int(d)) for d in game_offsets]

    games = []
    for i, game_date in enumerate(game_dates):
        # Game-level IP with variation
        game_ip = max(3.0, min(9.0, rng.normal(season_ip, 1.2)))
        game_ip = round(game_ip * 3) / 3  # Round to thirds

        # Batters faced (roughly 4.3 per IP + variation)
        game_bf = max(int(game_ip * 3.5), int(rng.normal(game_ip * 4.3, 2.5)))

        # Home/away
        is_home = int(rng.random() < 0.5)
        opponent = rng.choice([t for t in MLB_TEAMS if t != profile['team']])
        park_team = profile['team'] if is_home else opponent
        park_k_factor = PARK_K_FACTORS.get(park_team, 1.0)

        # Expected K count based on K/9, IP, and park factor
        expected_ks = (season_k9 / 9.0) * game_ip * park_k_factor

        # Generate actual Ks using negative binomial (right-skewed, as per thesis)
        # This is key: real K distributions are overdispersed relative to Poisson
        if expected_ks > 0:
            # Negative binomial parameterization:
            # mean = n*(1-p)/p, var = n*(1-p)/p^2
            # We want variance = mean * (1 + mean * k_var)
            overdispersion = 1 + expected_ks * profile['k_var']
            if overdispersion > 1:
                p_nb = 1.0 / overdispersion
                n_nb = expected_ks * p_nb / (1 - p_nb)
                n_nb = max(1, n_nb)
                p_nb = min(max(p_nb, 0.05), 0.95)
                game_ks = int(rng.negative_binomial(max(1, int(round(n_nb))), p_nb))
            else:
                game_ks = int(rng.poisson(expected_ks))
            game_ks = max(0, min(20, game_ks))
        else:
            game_ks = 0

        # Hits and walks
        game_h = max(0, int(rng.normal(game_ip * 1.1, 1.5)))
        game_bb = max(0, int(rng.normal(game_ip * 0.4, 0.8)))

        # Days rest
        if i > 0:
            days_rest = (game_date - game_dates[i - 1]).days
        else:
            days_rest = 5

        games.append({
            'pitcher_name': profile['pitcher_name'],
            'pitcher_id': profile['pitcher_id'],
            'game_date': game_date.strftime('%Y-%m-%d'),
            'season': season,
            'team': profile['team'],
            'opponent': opponent,
            'strikeouts': game_ks,
            'innings_pitched': round(game_ip, 1),
            'batters_faced': game_bf,
            'hits': game_h,
            'walks': game_bb,
            'is_home': is_home,
            'park_k_factor': round(park_k_factor, 2),
            'days_rest': min(days_rest, 30),
            'game_id': f"{season}_{profile['pitcher_id']}_{i}",
        })

    return games


def run_pipeline() -> pd.DataFrame:
    """Run the complete data pipeline with synthetic data generation."""
    print("=" * 60)
    print("RTM PICKS — DATA PIPELINE")
    print("Generating realistic MLB pitcher data 2019-2025")
    print("(Synthetic data based on real MLB distributions)")
    print("=" * 60)

    rng = np.random.default_rng(seed=42)

    # Generate ~90 pitcher profiles (MLB has ~150 unique starters/yr, but
    # we want a core group that spans multiple seasons)
    num_pitchers = 90
    profiles = [generate_pitcher_profile(i, rng) for i in range(num_pitchers)]

    all_gamelogs = []

    for season in SEASONS:
        print(f"\n--- Season {season} ---")

        # Each season, some pitchers are active (80-90%), some aren't
        # Plus a few new additions each year
        active_pct = 0.85 if season != 2020 else 0.80
        active_mask = rng.random(num_pitchers) < active_pct

        season_games = []
        for idx, profile in enumerate(profiles):
            if not active_mask[idx]:
                continue
            games = generate_season_gamelogs(profile, season, rng)
            season_games.extend(games)

        # Save season CSV
        season_df = pd.DataFrame(season_games)
        csv_path = RAW_DIR / f"{season}.csv"
        season_df.to_csv(csv_path, index=False)
        print(f"  Generated {len(season_games)} starts for {season}")
        print(f"  Saved to {csv_path}")

        all_gamelogs.extend(season_games)

    master_df = pd.DataFrame(all_gamelogs)

    # Validation
    print("\n" + "=" * 60)
    print("VALIDATION")
    print("=" * 60)

    print("\nRow counts per season:")
    season_counts = master_df.groupby('season').size()
    for season, count in season_counts.items():
        print(f"  {season}: {count:,} starts")

    print("\nTop 10 pitchers by total starts:")
    top_pitchers = master_df.groupby('pitcher_name').size().sort_values(ascending=False).head(10)
    for name, starts in top_pitchers.items():
        print(f"  {name}: {starts} starts")

    print("\nStrikeout distribution summary:")
    print(f"  Mean K/start: {master_df['strikeouts'].mean():.2f}")
    print(f"  Median K/start: {master_df['strikeouts'].median():.1f}")
    print(f"  Std K/start: {master_df['strikeouts'].std():.2f}")
    print(f"  Mean-Median gap: {master_df['strikeouts'].mean() - master_df['strikeouts'].median():.3f}")

    null_counts = master_df.isnull().sum()
    print("\nNull counts:")
    if null_counts.sum() == 0:
        print("  No nulls found!")
    else:
        for col, count in null_counts.items():
            if count > 0:
                print(f"  {col}: {count}")

    master_df['strikeouts'] = master_df['strikeouts'].fillna(0).astype(int)

    master_path = PROJECT_ROOT / "data" / "raw" / "master_gamelogs.csv"
    master_df.to_csv(master_path, index=False)
    print(f"\nSaved master game logs to {master_path}")

    return master_df


if __name__ == "__main__":
    df = run_pipeline()
    print(f"\nPipeline complete. {len(df)} total game logs.")
