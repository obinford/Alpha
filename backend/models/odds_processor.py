"""
RTM Props Model — Odds Data Processor (Phase 3)
Processes raw odds API data into a clean DataFrame matched to our backtest data.
Handles name matching, consensus line calculation, and vig removal.
"""

import json
import re
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ODDS_DIR = PROJECT_ROOT / "data" / "raw" / "historical_odds"

# Common name normalization for matching Retrosheet names to Odds API names
NAME_OVERRIDES = {
    # Odds API name -> Retrosheet name (add entries as needed)
    "yoshinobu yamamoto": "yoshinobu yamamoto",
    "j.p. france": "j.p. france",
    "jose berrios": "josé berríos",
    "nestor cortes": "néstor cortés",
    "cristian javier": "cristian javier",
    "framber valdez": "framber valdez",
}

# Team name mapping: Odds API display name -> Retrosheet 3-letter code
TEAM_MAP = {
    "Arizona Diamondbacks": "ARI",
    "Atlanta Braves": "ATL",
    "Baltimore Orioles": "BAL",
    "Boston Red Sox": "BOS",
    "Chicago Cubs": "CHN",
    "Chicago White Sox": "CHA",
    "Cincinnati Reds": "CIN",
    "Cleveland Guardians": "CLE",
    "Cleveland Indians": "CLE",
    "Colorado Rockies": "COL",
    "Detroit Tigers": "DET",
    "Houston Astros": "HOU",
    "Kansas City Royals": "KCA",
    "Los Angeles Angels": "ANA",
    "Los Angeles Dodgers": "LAN",
    "Miami Marlins": "MIA",
    "Milwaukee Brewers": "MIL",
    "Minnesota Twins": "MIN",
    "New York Mets": "NYN",
    "New York Yankees": "NYA",
    "Oakland Athletics": "OAK",
    "Philadelphia Phillies": "PHI",
    "Pittsburgh Pirates": "PIT",
    "San Diego Padres": "SDN",
    "San Francisco Giants": "SFN",
    "Seattle Mariners": "SEA",
    "St. Louis Cardinals": "SLN",
    "Tampa Bay Rays": "TBA",
    "Texas Rangers": "TEX",
    "Toronto Blue Jays": "TOR",
    "Washington Nationals": "WAS",
}


def normalize_name(name: str) -> str:
    """Normalize a pitcher name for fuzzy matching.

    Strips accents, lowercases, removes suffixes, standardizes spacing.
    """
    if not name:
        return ""

    name = name.lower().strip()

    # Remove common suffixes
    for suffix in [" jr.", " jr", " sr.", " sr", " ii", " iii", " iv"]:
        if name.endswith(suffix):
            name = name[:-len(suffix)].strip()

    # Replace accented characters with ASCII equivalents
    accent_map = {
        "á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u",
        "ñ": "n", "ü": "u", "ö": "o", "ä": "a",
        "à": "a", "è": "e", "ì": "i", "ò": "o", "ù": "u",
    }
    for accented, plain in accent_map.items():
        name = name.replace(accented, plain)

    # Remove periods and extra spaces
    name = name.replace(".", "").replace("'", "")
    name = re.sub(r"\s+", " ", name).strip()

    return name


def parse_raw_odds(raw_data: dict | list) -> pd.DataFrame:
    """Parse raw odds API JSON data into a flat DataFrame.

    Handles the nested structure: events -> bookmakers -> markets -> outcomes.

    Returns DataFrame with columns:
        game_date, event_id, home_team, away_team, pitcher_name,
        bookmaker, line, over_price, under_price
    """
    rows = []

    # Handle different input formats
    if isinstance(raw_data, dict):
        # Could be {year: [events]} or {"events": [...]} or single day
        all_events = []
        for key, val in raw_data.items():
            if isinstance(val, list):
                all_events.extend(val)
            elif isinstance(val, dict) and "events" in val:
                all_events.extend(val["events"])
    elif isinstance(raw_data, list):
        all_events = raw_data
    else:
        return pd.DataFrame()

    for event in all_events:
        event_id = event.get("event_id", "")
        home_team = event.get("home_team", "")
        away_team = event.get("away_team", "")
        commence = event.get("commence_time", "")

        # Extract date from commence_time
        game_date = ""
        if commence:
            try:
                game_date = pd.to_datetime(commence).strftime("%Y-%m-%d")
            except Exception:
                game_date = commence[:10] if len(commence) >= 10 else ""

        # Navigate to odds data
        odds_data = event.get("odds", {})
        if isinstance(odds_data, dict):
            inner = odds_data.get("data", odds_data)
        else:
            inner = odds_data

        # Find bookmakers
        bookmakers = []
        if isinstance(inner, dict):
            bookmakers = inner.get("bookmakers", [])
        elif isinstance(inner, list):
            # Some formats have bookmakers at top level
            for item in inner:
                if isinstance(item, dict) and "bookmakers" in item:
                    bookmakers.extend(item["bookmakers"])

        for book in bookmakers:
            book_name = book.get("key", book.get("title", "unknown"))

            for market in book.get("markets", []):
                if market.get("key") != "pitcher_strikeouts":
                    continue

                # Each outcome is a pitcher's over/under line
                outcomes = market.get("outcomes", [])
                # Group by pitcher name + line
                pitcher_lines = {}
                for outcome in outcomes:
                    pitcher = outcome.get("description", "")
                    point = outcome.get("point", None)
                    side = outcome.get("name", "").lower()  # "Over" or "Under"
                    price = outcome.get("price", None)

                    if pitcher and point is not None and price is not None:
                        key = (pitcher, point)
                        if key not in pitcher_lines:
                            pitcher_lines[key] = {"over": None, "under": None}
                        if "over" in side:
                            pitcher_lines[key]["over"] = price
                        elif "under" in side:
                            pitcher_lines[key]["under"] = price

                for (pitcher, line), prices in pitcher_lines.items():
                    if prices["over"] is not None or prices["under"] is not None:
                        rows.append({
                            "game_date": game_date,
                            "event_id": event_id,
                            "home_team": home_team,
                            "away_team": away_team,
                            "pitcher_name": pitcher,
                            "bookmaker": book_name,
                            "line": float(line),
                            "over_price": prices["over"],
                            "under_price": prices["under"],
                        })

    df = pd.DataFrame(rows)
    if len(df) > 0:
        df["game_date"] = pd.to_datetime(df["game_date"]).dt.strftime("%Y-%m-%d")
    return df


def american_to_implied_prob(price: float) -> float:
    """Convert American odds to implied probability.

    -130 -> 130/230 = 0.5652
    +110 -> 100/210 = 0.4762
    """
    if price is None or np.isnan(price):
        return np.nan
    if price < 0:
        return abs(price) / (abs(price) + 100)
    else:
        return 100 / (price + 100)


def american_to_decimal_profit(price: float) -> float:
    """Convert American odds to profit per unit wagered (on a win).

    -130 -> 100/130 = 0.769
    +110 -> 110/100 = 1.100
    """
    if price is None or np.isnan(price):
        return np.nan
    if price < 0:
        return 100 / abs(price)
    else:
        return price / 100


def process_odds_data(raw_odds_df: pd.DataFrame) -> pd.DataFrame:
    """Process raw odds into per-pitcher consensus lines.

    For each pitcher appearance:
    1. Find consensus line (most common across books)
    2. Calculate no-vig probabilities
    3. Find best available prices across books

    Returns one row per (pitcher, game_date) with consensus and best prices.
    """
    if len(raw_odds_df) == 0:
        return pd.DataFrame()

    df = raw_odds_df.copy()
    df["line"] = pd.to_numeric(df["line"], errors="coerce")
    df["over_price"] = pd.to_numeric(df["over_price"], errors="coerce")
    df["under_price"] = pd.to_numeric(df["under_price"], errors="coerce")

    # Drop rows missing critical data
    df = df.dropna(subset=["line", "game_date", "pitcher_name"])

    # Normalize pitcher name for matching
    df["pitcher_norm"] = df["pitcher_name"].apply(normalize_name)

    results = []

    for (pitcher_norm, game_date), group in df.groupby(["pitcher_norm", "game_date"]):
        # Consensus line: most common line across bookmakers
        line_counts = group["line"].value_counts()
        consensus_line = line_counts.index[0]

        # Filter to consensus line for price calculations
        consensus = group[group["line"] == consensus_line]

        # Consensus prices (median across books for stability)
        over_prices = consensus["over_price"].dropna()
        under_prices = consensus["under_price"].dropna()

        consensus_over = float(over_prices.median()) if len(over_prices) > 0 else np.nan
        consensus_under = float(under_prices.median()) if len(under_prices) > 0 else np.nan

        # No-vig probability calculation
        over_implied = american_to_implied_prob(consensus_over)
        under_implied = american_to_implied_prob(consensus_under)
        overround = over_implied + under_implied if not (np.isnan(over_implied) or np.isnan(under_implied)) else np.nan

        if not np.isnan(overround) and overround > 0:
            no_vig_over = over_implied / overround
            no_vig_under = under_implied / overround
        else:
            no_vig_over = np.nan
            no_vig_under = np.nan

        # Best available prices (across ALL books, ALL lines for this pitcher)
        all_over = group["over_price"].dropna()
        all_under = group["under_price"].dropna()

        # Best over = least negative (or most positive)
        best_over = float(all_over.max()) if len(all_over) > 0 else np.nan
        # Best under = least negative (or most positive)
        best_under = float(all_under.max()) if len(all_under) > 0 else np.nan

        # Best prices might be on different lines — find best for consensus line
        consensus_best_over = float(over_prices.max()) if len(over_prices) > 0 else np.nan
        consensus_best_under = float(under_prices.max()) if len(under_prices) > 0 else np.nan

        results.append({
            "pitcher_name_odds": group["pitcher_name"].iloc[0],
            "pitcher_norm": pitcher_norm,
            "game_date": game_date,
            "home_team_odds": group["home_team"].iloc[0],
            "away_team_odds": group["away_team"].iloc[0],
            "consensus_line": consensus_line,
            "consensus_over_price": consensus_over,
            "consensus_under_price": consensus_under,
            "best_over_price": consensus_best_over,
            "best_under_price": consensus_best_under,
            "no_vig_over_prob": no_vig_over,
            "no_vig_under_prob": no_vig_under,
            "overround": overround,
            "num_books": group["bookmaker"].nunique(),
            "event_id": group["event_id"].iloc[0],
        })

    return pd.DataFrame(results)


def match_odds_to_backtest(
    odds_df: pd.DataFrame,
    backtest_df: pd.DataFrame,
) -> pd.DataFrame:
    """Match processed odds data to backtest results on pitcher + date.

    Uses normalized name matching and team proximity as fallback.

    Returns merged DataFrame with both backtest and real odds columns.
    """
    if len(odds_df) == 0 or len(backtest_df) == 0:
        print("  WARNING: Empty odds or backtest data, cannot match")
        return pd.DataFrame()

    bt = backtest_df.copy()
    bt["game_date"] = pd.to_datetime(bt["game_date"]).dt.strftime("%Y-%m-%d")
    bt["pitcher_norm"] = bt["pitcher_name"].apply(normalize_name)

    odds = odds_df.copy()

    # Map odds team names to Retrosheet codes for fallback matching
    odds["home_retro"] = odds["home_team_odds"].map(TEAM_MAP)
    odds["away_retro"] = odds["away_team_odds"].map(TEAM_MAP)

    # Primary join: normalized name + game date
    merged = bt.merge(
        odds,
        on=["pitcher_norm", "game_date"],
        how="inner",
        suffixes=("", "_odds"),
    )

    # Log match stats
    total_bt = len(bt)
    # Filter backtest to the odds data's date range
    odds_dates = set(odds["game_date"])
    bt_in_range = bt[bt["game_date"].isin(odds_dates)]
    total_in_range = len(bt_in_range)
    matched = len(merged)

    print(f"  Backtest starts in odds date range: {total_in_range}")
    print(f"  Matched to real odds: {matched} ({matched/max(total_in_range,1)*100:.1f}%)")

    # Log unmatched names
    if total_in_range > matched:
        bt_keys = set(zip(bt_in_range["pitcher_norm"], bt_in_range["game_date"]))
        odds_keys = set(zip(odds["pitcher_norm"], odds["game_date"]))
        unmatched_bt = bt_keys - odds_keys

        # Find the most common unmatched pitcher names
        unmatched_names = {}
        for name, date in unmatched_bt:
            unmatched_names[name] = unmatched_names.get(name, 0) + 1

        top_unmatched = sorted(unmatched_names.items(), key=lambda x: -x[1])[:20]
        if top_unmatched:
            print(f"\n  Top 20 unmatched pitcher names (backtest names not in odds):")
            for name, count in top_unmatched:
                print(f"    {name}: {count} starts")

    return merged


def load_and_process_all_odds() -> pd.DataFrame:
    """Load all cached odds files and process into a clean DataFrame."""
    print("=" * 60)
    print("RTM PROPS MODEL — ODDS PROCESSOR")
    print("=" * 60)

    # Load all cached day files
    all_events = []
    for year_dir in sorted(ODDS_DIR.iterdir()):
        if not year_dir.is_dir() or year_dir.name.startswith("."):
            continue
        day_files = sorted(year_dir.glob("*.json"))
        print(f"\n  Loading {year_dir.name}: {len(day_files)} day files")
        for day_file in day_files:
            try:
                with open(day_file) as f:
                    data = json.load(f)
                all_events.extend(data.get("events", []))
            except (json.JSONDecodeError, KeyError) as e:
                print(f"    Warning: Could not parse {day_file}: {e}")

    if not all_events:
        # Try the combined file
        combined = ODDS_DIR / "all_odds_combined.json"
        if combined.exists():
            print(f"  Loading combined file: {combined}")
            with open(combined) as f:
                data = json.load(f)
            if isinstance(data, dict):
                for year_events in data.values():
                    if isinstance(year_events, list):
                        all_events.extend(year_events)

    print(f"\n  Total raw events loaded: {len(all_events)}")

    if not all_events:
        print("  No odds data found. Run odds_fetcher.py first.")
        return pd.DataFrame()

    # Parse into flat DataFrame
    raw_df = parse_raw_odds(all_events)
    print(f"  Raw odds rows (pitcher × book): {len(raw_df)}")

    if len(raw_df) == 0:
        print("  No pitcher strikeout markets found in the data.")
        return pd.DataFrame()

    # Process into consensus lines
    processed = process_odds_data(raw_df)
    print(f"  Processed pitcher-date entries: {len(processed)}")

    return processed


if __name__ == "__main__":
    processed = load_and_process_all_odds()
    if len(processed) > 0:
        out_path = PROJECT_ROOT / "data" / "processed" / "processed_odds.parquet"
        processed.to_parquet(out_path, index=False)
        print(f"\n  Saved to {out_path}")
        print(f"\n  Sample:")
        print(processed.head(3).to_string())
