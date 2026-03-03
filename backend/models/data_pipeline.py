"""
RTM Picks — MLB Strikeout Model: Data Pipeline
Pulls real pitcher game logs from 2019-2025 using Retrosheet day-by-day data
(via the Chadwick Bureau's retrosplits repository on GitHub).
Filters to starting pitchers and caches per-season CSVs.
"""

import io
import time
import urllib.request
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

# Retrosheet day-by-day data URL template (Chadwick Bureau retrosplits)
RETRO_URL = "https://raw.githubusercontent.com/chadwickbureau/retrosplits/master/daybyday/playing-{year}.csv"

# Also need the Chadwick register to map person.key -> real names
REGISTER_URL = "https://raw.githubusercontent.com/chadwickbureau/register/master/data/people.csv"

# Columns we need from the Retrosheet day-by-day files
RETRO_COLS = [
    "game.key", "game.date", "site.key", "season.phase",
    "team.alignment", "team.key", "opponent.key", "person.key",
    "P_G", "P_GS", "P_CG", "P_SHO", "P_GF", "P_W", "P_L", "P_SV",
    "P_OUT", "P_TBF", "P_H", "P_BB", "P_IBB", "P_SO", "P_HR",
    "P_WP", "P_BK", "P_PITCH", "P_STRIKE",
]

# Park K-rate factors (relative to league average = 1.0)
# Based on historical park factors for strikeouts
PARK_K_FACTORS = {
    # Retrosheet uses 3-letter team codes; map common ones
    "SDN": 1.08, "SDP": 1.08,
    "NYN": 1.06, "NYM": 1.06,
    "TBA": 1.05, "TBR": 1.05, "TB": 1.05,
    "MIL": 1.05,
    "SEA": 1.04,
    "CLE": 1.04,
    "ARI": 1.03,
    "LAN": 1.03, "LAD": 1.03,
    "SFN": 1.03, "SFG": 1.03, "SF": 1.03,
    "HOU": 1.02,
    "ATL": 1.02,
    "WAS": 1.01, "WSN": 1.01, "WSH": 1.01,
    "PHI": 1.01,
    "SLN": 1.00, "STL": 1.00,
    "PIT": 1.00,
    "CIN": 1.00,
    "BAL": 1.00,
    "TOR": 1.00,
    "OAK": 1.00,
    "MIN": 1.00,
    "DET": 1.00,
    "TEX": 0.99,
    "ANA": 0.99, "LAA": 0.99,
    "NYA": 0.99, "NYY": 0.99,
    "CHA": 0.99, "CHW": 0.99, "CWS": 0.99,
    "BOS": 0.98,
    "MIA": 0.98, "FLO": 0.98,
    "CHN": 0.97, "CHC": 0.97,
    "KCA": 0.96, "KCR": 0.96, "KC": 0.96,
    "COL": 0.92,
}


def download_with_retry(url: str, max_retries: int = 4) -> bytes:
    """Download a URL with exponential backoff retry."""
    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(url)
            resp = urllib.request.urlopen(req, timeout=60)
            return resp.read()
        except Exception as e:
            wait = 2 ** (attempt + 1)
            if attempt < max_retries - 1:
                print(f"    Attempt {attempt + 1} failed: {type(e).__name__}. Retrying in {wait}s...")
                time.sleep(wait)
            else:
                raise RuntimeError(f"Failed to download {url} after {max_retries} attempts: {e}")


def load_name_register() -> pd.DataFrame:
    """Load the Chadwick register to map person.key -> player names.

    The register is split across multiple files (people-0.csv through people-f.csv)
    in the chadwickbureau/register GitHub repo.
    """
    cache_path = RAW_DIR / "chadwick_register.csv"
    if cache_path.exists():
        print("  Loading cached name register...")
        return pd.read_csv(cache_path, low_memory=False)

    print("  Downloading Chadwick name register (16 files)...")
    all_dfs = []
    for c in list("0123456789abcdef"):
        url = f"https://raw.githubusercontent.com/chadwickbureau/register/master/data/people-{c}.csv"
        try:
            data = download_with_retry(url)
            df = pd.read_csv(io.BytesIO(data), low_memory=False,
                             usecols=["key_retro", "name_last", "name_first"])
            df = df.dropna(subset=["key_retro"])
            all_dfs.append(df)
        except Exception as e:
            print(f"    Warning: Could not load people-{c}.csv: {e}")

    if not all_dfs:
        print("  Warning: Could not load any register files")
        return pd.DataFrame()

    register = pd.concat(all_dfs, ignore_index=True)
    register.to_csv(cache_path, index=False)
    print(f"  Loaded {len(register)} MLB player name mappings")
    return register


def pull_season_data(year: int, register: pd.DataFrame) -> pd.DataFrame:
    """Pull and process Retrosheet day-by-day pitching data for one season."""
    csv_path = RAW_DIR / f"{year}.csv"
    if csv_path.exists():
        print(f"  Loading cached {year} data from {csv_path}")
        return pd.read_csv(csv_path)

    url = RETRO_URL.format(year=year)
    print(f"  Downloading {year} Retrosheet data...")

    try:
        data = download_with_retry(url)
    except Exception as e:
        print(f"  ERROR: Could not download {year}: {e}")
        return pd.DataFrame()

    # Parse CSV
    raw = pd.read_csv(io.BytesIO(data), low_memory=False)
    print(f"  Raw rows: {len(raw)}")

    # Filter to regular season only
    if 'season.phase' in raw.columns:
        raw = raw[raw['season.phase'] == 'R'].copy()

    # Filter to rows where the player pitched (P_G > 0)
    if 'P_G' not in raw.columns:
        print(f"  ERROR: P_G column not found in {year} data")
        return pd.DataFrame()

    raw['P_G'] = pd.to_numeric(raw['P_G'], errors='coerce').fillna(0)
    pitchers = raw[raw['P_G'] > 0].copy()
    print(f"  Pitcher appearances: {len(pitchers)}")

    # Filter to starting pitchers (P_GS == 1)
    pitchers['P_GS'] = pd.to_numeric(pitchers['P_GS'], errors='coerce').fillna(0)
    starters = pitchers[pitchers['P_GS'] == 1].copy()
    print(f"  Starting pitcher appearances: {len(starters)}")

    # Convert numeric columns
    for col in ['P_OUT', 'P_TBF', 'P_H', 'P_BB', 'P_IBB', 'P_SO', 'P_HR',
                'P_WP', 'P_BK', 'P_PITCH', 'P_STRIKE']:
        if col in starters.columns:
            starters[col] = pd.to_numeric(starters[col], errors='coerce').fillna(0).astype(int)

    # Compute innings pitched from outs (P_OUT)
    starters['innings_pitched'] = starters['P_OUT'] / 3.0

    # Filter: minimum 3.0 IP or P_GS flag (already filtered by GS)
    # Keep all starts since we already filtered to P_GS == 1

    # Map person.key to player names
    starters['person.key'] = starters['person.key'].astype(str)
    if not register.empty and 'key_retro' in register.columns:
        name_map = register.drop_duplicates('key_retro').set_index('key_retro')
        starters = starters.merge(
            name_map[['name_first', 'name_last']],
            left_on='person.key', right_index=True, how='left'
        )
        starters['pitcher_name'] = (
            starters['name_first'].fillna('') + ' ' + starters['name_last'].fillna('')
        ).str.strip()
        starters.loc[starters['pitcher_name'] == '', 'pitcher_name'] = starters['person.key']
    else:
        starters['pitcher_name'] = starters['person.key']

    # Determine home/away from team.alignment (1 = home, 0 = away)
    starters['is_home'] = pd.to_numeric(starters.get('team.alignment', 0), errors='coerce').fillna(0).astype(int)

    # Park K factor
    home_team = np.where(starters['is_home'] == 1,
                         starters['team.key'],
                         starters['opponent.key'])
    starters['park_k_factor'] = pd.Series(home_team).map(PARK_K_FACTORS).fillna(1.0).values

    # Build clean output
    result = pd.DataFrame({
        'pitcher_name': starters['pitcher_name'].values,
        'pitcher_id': starters['person.key'].values,
        'game_date': pd.to_datetime(starters['game.date']).dt.strftime('%Y-%m-%d'),
        'season': year,
        'team': starters['team.key'].values,
        'opponent': starters['opponent.key'].values,
        'strikeouts': starters['P_SO'].values,
        'innings_pitched': starters['innings_pitched'].round(1).values,
        'batters_faced': starters['P_TBF'].values,
        'pitches_thrown': starters['P_PITCH'].values if 'P_PITCH' in starters.columns else 0,
        'hits': starters['P_H'].values,
        'walks': starters['P_BB'].values,
        'home_runs': starters['P_HR'].values,
        'is_home': starters['is_home'].values,
        'park_k_factor': starters['park_k_factor'].round(2).values,
        'game_id': starters['game.key'].values,
    })

    # Save
    result.to_csv(csv_path, index=False)
    print(f"  Saved {len(result)} starter appearances for {year}")
    return result


def run_pipeline() -> pd.DataFrame:
    """Run the complete data pipeline."""
    print("=" * 60)
    print("RTM PICKS — DATA PIPELINE")
    print("Pulling real MLB pitcher data 2019-2025")
    print("Source: Retrosheet (Chadwick Bureau retrosplits)")
    print("=" * 60)

    # Load name register first
    register = load_name_register()

    all_seasons = []
    for year in SEASONS:
        print(f"\n--- Season {year} ---")
        season_df = pull_season_data(year, register)
        if not season_df.empty:
            all_seasons.append(season_df)
        else:
            print(f"  WARNING: No data for {year}")

    if not all_seasons:
        raise RuntimeError("No data pulled for any season!")

    master_df = pd.concat(all_seasons, ignore_index=True)

    # Compute days_rest per pitcher
    master_df['game_date_dt'] = pd.to_datetime(master_df['game_date'])
    master_df = master_df.sort_values(['pitcher_id', 'game_date_dt']).reset_index(drop=True)

    days_rest = []
    for _, grp in master_df.groupby('pitcher_id'):
        dates = grp['game_date_dt'].values
        rest = [5]  # default for first start
        for i in range(1, len(dates)):
            diff = (dates[i] - dates[i-1]) / np.timedelta64(1, 'D')
            rest.append(min(int(diff), 30))
        days_rest.extend(rest)

    master_df['days_rest'] = days_rest
    master_df = master_df.drop(columns=['game_date_dt'])

    # Validation
    print("\n" + "=" * 60)
    print("VALIDATION")
    print("=" * 60)

    print("\nRow counts per season:")
    season_counts = master_df.groupby('season').size()
    for season, count in season_counts.items():
        print(f"  {season}: {count:,} starts")
    print(f"  Total: {len(master_df):,} starts")

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
