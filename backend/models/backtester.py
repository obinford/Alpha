"""
RTM Picks — MLB Strikeout Model: Backtester (CORRECTED)
Runs the full backtest across 2019-2025 data.
Applies edge tiers, calculates P&L, tracks bankroll.

AUDIT FIXES:
  - Drawdown computed on BET rows only (not diluted by non-bet rows)
"""

import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RESULTS_DIR = PROJECT_ROOT / "data" / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

# Edge tiers and unit sizing
TIERS = {
    'A+': {'min_edge': 0.07, 'max_edge': 1.0, 'units': 2.0},
    'A': {'min_edge': 0.05, 'max_edge': 0.07, 'units': 1.5},
    'B': {'min_edge': 0.03, 'max_edge': 0.05, 'units': 1.0},
    'Monitor': {'min_edge': 0.01, 'max_edge': 0.03, 'units': 0.0},
}

# Betting odds
WIN_PAYOUT = 0.909  # Profit on a -110 bet per unit
STARTING_BANKROLL = 1000.0


def classify_tier(edge: float) -> str:
    """Classify a bet into a tier based on edge percentage."""
    if np.isnan(edge):
        return 'No Edge'
    for tier_name, tier_info in TIERS.items():
        if tier_info['min_edge'] <= edge < tier_info['max_edge']:
            return tier_name
    if edge >= 1.0:
        return 'A+'
    return 'No Edge'


def get_units(tier: str) -> float:
    """Get the unit size for a given tier."""
    if tier in TIERS:
        return TIERS[tier]['units']
    return 0.0


def run_backtest(sim_df: pd.DataFrame) -> pd.DataFrame:
    """Run the full backtest on simulation results.

    Args:
        sim_df: DataFrame from simulator with all simulation results.

    Returns:
        DataFrame with backtest results including P&L and bankroll.
    """
    print("=" * 60)
    print("RTM PICKS — BACKTESTER")
    print("=" * 60)

    df = sim_df.copy()

    # Filter to successful simulations only
    df = df[df['fit_success'] == True].copy()
    print(f"Starts with successful simulations: {len(df)}")

    # Sort by date for chronological processing
    df['game_date'] = pd.to_datetime(df['game_date'])
    df = df.sort_values('game_date').reset_index(drop=True)

    # Classify tiers
    df['tier'] = df['edge_pct'].apply(classify_tier)
    df['bet_units'] = df['tier'].apply(get_units)

    # Determine bet outcomes
    df['is_bet'] = df['bet_units'] > 0  # Only tiers A+, A, B are actual bets

    # Calculate wins: did the predicted side actually hit?
    df['bet_won'] = False
    df['is_push'] = False

    for idx in range(len(df)):
        row = df.iloc[idx]
        if not row['is_bet']:
            continue

        predicted = row['predicted_side']
        if predicted == 'over':
            if row['actual_over'] == 1:
                df.at[df.index[idx], 'bet_won'] = True
            elif row['actual_push'] == 1:
                df.at[df.index[idx], 'is_push'] = True
        elif predicted == 'under':
            if row['actual_under'] == 1:
                df.at[df.index[idx], 'bet_won'] = True
            elif row['actual_push'] == 1:
                df.at[df.index[idx], 'is_push'] = True

    # Calculate P&L per bet
    df['pnl'] = 0.0
    bet_mask = df['is_bet'] & ~df['is_push']
    df.loc[bet_mask & df['bet_won'], 'pnl'] = df.loc[bet_mask & df['bet_won'], 'bet_units'] * WIN_PAYOUT
    df.loc[bet_mask & ~df['bet_won'], 'pnl'] = -df.loc[bet_mask & ~df['bet_won'], 'bet_units']

    # Pushes have 0 P&L (already set)

    # Calculate cumulative bankroll — on BETS ONLY for accurate tracking
    # First compute cumulative P&L across all rows (for charting)
    df['cumulative_pnl'] = df['pnl'].cumsum()
    df['bankroll'] = STARTING_BANKROLL + df['cumulative_pnl']

    # Running ROI (profit / total wagered) — only count actual bets
    df['cumulative_wagered'] = 0.0
    cumulative_wagered = 0.0
    for idx in range(len(df)):
        if df.iloc[idx]['is_bet'] and not df.iloc[idx]['is_push']:
            cumulative_wagered += df.iloc[idx]['bet_units']
        df.at[df.index[idx], 'cumulative_wagered'] = cumulative_wagered

    df['running_roi'] = np.where(
        df['cumulative_wagered'] > 0,
        df['cumulative_pnl'] / df['cumulative_wagered'],
        0
    )

    # Compute bankroll on bets only for accurate drawdown
    bet_rows = df[df['is_bet'] & ~df['is_push']].copy()
    if len(bet_rows) > 0:
        bet_rows['bet_cumulative_pnl'] = bet_rows['pnl'].cumsum()
        bet_rows['bet_bankroll'] = STARTING_BANKROLL + bet_rows['bet_cumulative_pnl']
        peak = np.maximum.accumulate(bet_rows['bet_bankroll'].values)
        drawdowns = peak - bet_rows['bet_bankroll'].values
        df['max_drawdown_bets'] = float(np.max(drawdowns))
        max_dd_peak = peak[np.argmax(drawdowns)]
        df['max_drawdown_pct_bets'] = float(np.max(drawdowns) / max_dd_peak * 100) if max_dd_peak > 0 else 0.0
    else:
        df['max_drawdown_bets'] = 0.0
        df['max_drawdown_pct_bets'] = 0.0

    # Summary stats
    bets = df[df['is_bet'] & ~df['is_push']]
    total_bets = len(bets)
    wins = bets['bet_won'].sum()
    total_wagered = bets['bet_units'].sum()
    total_pnl = bets['pnl'].sum()

    print(f"\nBacktest Results Summary:")
    print(f"  Total starts analyzed: {len(df)}")
    print(f"  Total bets placed: {total_bets}")
    print(f"  Wins: {wins} ({wins/max(total_bets,1)*100:.1f}%)")
    print(f"  Total wagered: {total_wagered:.1f} units")
    print(f"  Total P&L: {total_pnl:+.1f} units")
    print(f"  ROI: {total_pnl/max(total_wagered,1)*100:+.1f}%")
    print(f"  Ending bankroll: {STARTING_BANKROLL + total_pnl:.1f} units")

    # By tier
    print(f"\nBy Tier:")
    for tier_name in ['A+', 'A', 'B', 'Monitor']:
        tier_bets = bets[bets['tier'] == tier_name]
        if len(tier_bets) == 0:
            tier_monitor = df[df['tier'] == tier_name]
            print(f"  {tier_name}: {len(tier_monitor)} starts (no bets)")
            continue
        t_wins = tier_bets['bet_won'].sum()
        t_wagered = tier_bets['bet_units'].sum()
        t_pnl = tier_bets['pnl'].sum()
        print(f"  {tier_name}: {len(tier_bets)} bets | "
              f"{t_wins/len(tier_bets)*100:.1f}% win rate | "
              f"{t_pnl/max(t_wagered,1)*100:+.1f}% ROI | "
              f"{t_pnl:+.1f} units")

    # Save results
    output_path = RESULTS_DIR / "strikeout_backtest.parquet"
    df.to_parquet(output_path, index=False)
    print(f"\nSaved backtest results to {output_path}")

    return df


if __name__ == "__main__":
    input_path = RESULTS_DIR / "simulation_results.parquet"
    sim_df = pd.read_parquet(input_path)
    backtest_df = run_backtest(sim_df)
