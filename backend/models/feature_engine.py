"""
RTM Picks — MLB Strikeout Model: Feature Engine
Computes per-start features using ONLY data available before each game date.
No lookahead bias — every feature is computed from prior starts only.
"""

import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RAW_PATH = PROJECT_ROOT / "data" / "raw" / "master_gamelogs.csv"
OUTPUT_PATH = PROJECT_ROOT / "data" / "processed" / "strikeout_features.parquet"
OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)


def compute_features(df: pd.DataFrame) -> pd.DataFrame:
    """Compute features for each pitcher start using only prior data.

    Args:
        df: Master game log DataFrame with columns: pitcher_id, game_date,
            strikeouts, innings_pitched, batters_faced, is_home, park_k_factor, etc.

    Returns:
        Feature matrix DataFrame with one row per qualified start.
    """
    print("Computing features...")

    # Ensure proper types
    df = df.copy()
    df['game_date'] = pd.to_datetime(df['game_date'])
    df['strikeouts'] = pd.to_numeric(df['strikeouts'], errors='coerce').fillna(0).astype(int)
    df['innings_pitched'] = pd.to_numeric(df['innings_pitched'], errors='coerce').fillna(0).astype(float)
    df['batters_faced'] = pd.to_numeric(df['batters_faced'], errors='coerce').fillna(0).astype(float)
    df['season'] = pd.to_numeric(df['season'], errors='coerce').fillna(0).astype(int)

    # Sort by pitcher and date — critical for correct rolling calculations
    df = df.sort_values(['pitcher_id', 'game_date']).reset_index(drop=True)

    features_list = []
    total_starts = len(df)
    skipped_insufficient = 0

    # Group by pitcher for efficient processing
    grouped = df.groupby('pitcher_id')
    pitcher_count = 0
    total_pitchers = len(grouped)

    for pitcher_id, pitcher_df in grouped:
        pitcher_count += 1
        pitcher_df = pitcher_df.sort_values('game_date').reset_index(drop=True)

        if len(pitcher_df) < 6:
            # Need at least 5 prior starts + current start
            skipped_insufficient += len(pitcher_df)
            continue

        for idx in range(len(pitcher_df)):
            row = pitcher_df.iloc[idx]
            current_date = row['game_date']
            current_season = row['season']

            # All prior starts for this pitcher (strict: before this game)
            prior = pitcher_df.iloc[:idx]

            if len(prior) < 5:
                skipped_insufficient += 1
                continue

            # Prior starts this season only
            prior_season = prior[prior['season'] == current_season]

            # --- Feature: season_k_per_9 ---
            if len(prior_season) > 0 and prior_season['innings_pitched'].sum() > 0:
                season_k_per_9 = (prior_season['strikeouts'].sum() * 9) / prior_season['innings_pitched'].sum()
            else:
                season_k_per_9 = (prior['strikeouts'].sum() * 9) / max(prior['innings_pitched'].sum(), 1)

            # --- Feature: recent_3_k_per_9 ---
            last_3 = prior.tail(3)
            if last_3['innings_pitched'].sum() > 0:
                recent_3_k_per_9 = (last_3['strikeouts'].sum() * 9) / last_3['innings_pitched'].sum()
            else:
                recent_3_k_per_9 = season_k_per_9

            # --- Feature: recent_5_k_per_9 ---
            last_5 = prior.tail(5)
            if last_5['innings_pitched'].sum() > 0:
                recent_5_k_per_9 = (last_5['strikeouts'].sum() * 9) / last_5['innings_pitched'].sum()
            else:
                recent_5_k_per_9 = season_k_per_9

            # --- Feature: season_k_pct ---
            if len(prior_season) > 0 and prior_season['batters_faced'].sum() > 0:
                season_k_pct = prior_season['strikeouts'].sum() / prior_season['batters_faced'].sum()
            else:
                season_k_pct = prior['strikeouts'].sum() / max(prior['batters_faced'].sum(), 1)

            # --- Feature: career_avg_ks ---
            career_avg_ks = prior['strikeouts'].mean()

            # --- Feature: avg_ip_last_5 ---
            avg_ip_last_5 = last_5['innings_pitched'].mean()

            # --- Feature: days_rest ---
            if idx > 0:
                prev_date = pitcher_df.iloc[idx - 1]['game_date']
                days_rest = (current_date - prev_date).days
            else:
                days_rest = 5  # Default for first appearance

            # Cap extreme rest values
            days_rest = min(days_rest, 30)

            # --- Feature: is_home ---
            is_home = int(row.get('is_home', 0))

            # --- Feature: park_k_factor ---
            park_k_factor = float(row.get('park_k_factor', 1.0))

            # --- Feature: starts_this_season ---
            starts_this_season = len(prior_season)

            # --- Feature: trailing_20_ks ---
            trailing_ks = prior.tail(20)['strikeouts'].tolist()

            features_list.append({
                'pitcher_name': row['pitcher_name'],
                'pitcher_id': pitcher_id,
                'game_date': current_date,
                'season': current_season,
                'team': row.get('team', 'UNK'),
                'opponent': row.get('opponent', 'UNK'),
                'actual_ks': int(row['strikeouts']),
                'actual_ip': float(row['innings_pitched']),
                'season_k_per_9': round(season_k_per_9, 2),
                'recent_3_k_per_9': round(recent_3_k_per_9, 2),
                'recent_5_k_per_9': round(recent_5_k_per_9, 2),
                'season_k_pct': round(season_k_pct, 4),
                'career_avg_ks': round(career_avg_ks, 2),
                'avg_ip_last_5': round(avg_ip_last_5, 2),
                'days_rest': days_rest,
                'is_home': is_home,
                'park_k_factor': park_k_factor,
                'starts_this_season': starts_this_season,
                'trailing_20_ks': trailing_ks,
            })

        # Progress
        if pitcher_count % 50 == 0:
            print(f"  Processed {pitcher_count}/{total_pitchers} pitchers...")

    feature_df = pd.DataFrame(features_list)
    print(f"\nFeature computation complete.")
    print(f"  Total starts in input: {total_starts}")
    print(f"  Skipped (insufficient history): {skipped_insufficient}")
    print(f"  Feature matrix rows: {len(feature_df)}")

    return feature_df


def validate_features(df: pd.DataFrame) -> None:
    """Validate the feature matrix for correctness."""
    print("\n" + "=" * 60)
    print("FEATURE VALIDATION")
    print("=" * 60)

    print(f"\nFeature matrix shape: {df.shape}")

    # Null counts
    print("\nNull counts per column:")
    for col in df.columns:
        if col == 'trailing_20_ks':
            continue
        null_count = df[col].isnull().sum()
        if null_count > 0:
            print(f"  {col}: {null_count}")
    total_nulls = df.drop(columns=['trailing_20_ks']).isnull().sum().sum()
    if total_nulls == 0:
        print("  No nulls found (excluding trailing_20_ks lists)!")

    # Spot-check 3 random pitcher-games for lookahead validation
    print("\nSpot-checking 3 random pitcher-games for lookahead bias:")
    np.random.seed(123)
    sample_indices = np.random.choice(len(df), size=min(3, len(df)), replace=False)
    for i, idx in enumerate(sample_indices):
        row = df.iloc[idx]
        print(f"\n  Check {i+1}: {row['pitcher_name']} on {row['game_date'].strftime('%Y-%m-%d')}")
        print(f"    Season: {row['season']}, Starts this season prior: {row['starts_this_season']}")
        print(f"    Season K/9: {row['season_k_per_9']}, Career Avg Ks: {row['career_avg_ks']}")
        print(f"    Trailing Ks (last up to 20): {row['trailing_20_ks'][-5:]}")
        print(f"    Actual Ks this game: {row['actual_ks']} (not used in features)")
        print(f"    Days rest: {row['days_rest']}, Home: {row['is_home']}")

    # Summary stats
    print("\nFeature summary statistics:")
    numeric_cols = ['season_k_per_9', 'recent_3_k_per_9', 'career_avg_ks',
                    'avg_ip_last_5', 'days_rest', 'park_k_factor']
    for col in numeric_cols:
        if col in df.columns:
            vals = df[col]
            print(f"  {col}: mean={vals.mean():.2f}, std={vals.std():.2f}, "
                  f"min={vals.min():.2f}, max={vals.max():.2f}")


def run_feature_engine(input_df: pd.DataFrame = None) -> pd.DataFrame:
    """Run the full feature engine pipeline."""
    print("=" * 60)
    print("RTM PICKS — FEATURE ENGINE")
    print("=" * 60)

    if input_df is None:
        print(f"Loading master game logs from {RAW_PATH}")
        input_df = pd.read_csv(RAW_PATH)

    feature_df = compute_features(input_df)
    validate_features(feature_df)

    # Save to parquet
    # Convert trailing_20_ks to string for parquet compatibility
    save_df = feature_df.copy()
    save_df['trailing_20_ks'] = save_df['trailing_20_ks'].apply(str)
    save_df.to_parquet(OUTPUT_PATH, index=False)
    print(f"\nSaved feature matrix to {OUTPUT_PATH}")

    return feature_df


if __name__ == "__main__":
    df = run_feature_engine()
    print(f"\nFeature engine complete. {len(df)} qualified starts.")
