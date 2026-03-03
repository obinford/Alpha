"""
RTM Picks — MLB Strikeout Model: Metrics
Calculates and prints all performance metrics, calibration, and summary report.
"""

import json
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RESULTS_DIR = PROJECT_ROOT / "data" / "results"


def compute_all_metrics(df: pd.DataFrame) -> dict:
    """Compute all backtest metrics.

    Args:
        df: Backtest results DataFrame from backtester.

    Returns:
        Dict containing all metrics.
    """
    metrics = {}

    # Filter to successful fits
    df = df[df['fit_success'] == True].copy()
    df['game_date'] = pd.to_datetime(df['game_date'])

    bets = df[df['is_bet'] & ~df['is_push']].copy()
    total_bets = len(bets)
    wins = bets['bet_won'].sum()
    total_wagered = bets['bet_units'].sum()
    total_pnl = bets['pnl'].sum()

    # === OVERALL RESULTS ===
    metrics['total_starts'] = len(df)
    metrics['total_bets'] = total_bets
    metrics['total_wins'] = int(wins)
    metrics['win_rate'] = float(wins / max(total_bets, 1))
    metrics['total_wagered'] = float(total_wagered)
    metrics['total_pnl'] = float(total_pnl)
    metrics['roi'] = float(total_pnl / max(total_wagered, 1))

    # === BY TIER ===
    tier_metrics = {}
    for tier_name in ['A+', 'A', 'B', 'Monitor']:
        tier_bets = bets[bets['tier'] == tier_name]
        tier_all = df[df['tier'] == tier_name]
        if len(tier_bets) > 0:
            t_wins = tier_bets['bet_won'].sum()
            t_wagered = tier_bets['bet_units'].sum()
            t_pnl = tier_bets['pnl'].sum()
            tier_metrics[tier_name] = {
                'bets': len(tier_bets),
                'wins': int(t_wins),
                'win_rate': float(t_wins / len(tier_bets)),
                'wagered': float(t_wagered),
                'pnl': float(t_pnl),
                'roi': float(t_pnl / max(t_wagered, 1)),
            }
        else:
            tier_metrics[tier_name] = {
                'bets': 0,
                'wins': 0,
                'win_rate': 0.0,
                'wagered': 0.0,
                'pnl': 0.0,
                'roi': 0.0,
                'monitored': len(tier_all),
            }
    metrics['by_tier'] = tier_metrics

    # === BY SEASON ===
    season_metrics = {}
    for season in sorted(df['season'].unique()):
        season_bets = bets[bets['season'] == season]
        if len(season_bets) > 0:
            s_pnl = season_bets['pnl'].sum()
            s_wagered = season_bets['bet_units'].sum()
            season_metrics[int(season)] = {
                'bets': len(season_bets),
                'wins': int(season_bets['bet_won'].sum()),
                'win_rate': float(season_bets['bet_won'].mean()),
                'pnl': float(s_pnl),
                'roi': float(s_pnl / max(s_wagered, 1)),
            }
        else:
            season_starts = df[df['season'] == season]
            season_metrics[int(season)] = {
                'bets': 0,
                'wins': 0,
                'win_rate': 0.0,
                'pnl': 0.0,
                'roi': 0.0,
                'starts': len(season_starts),
            }
    metrics['by_season'] = season_metrics

    # === MEAN/MEDIAN ATTRIBUTION ===
    valid = df[~df['mean_median_gap'].isna()].copy()
    metrics['mean_gt_median_pct'] = float((valid['mean_median_gap'] > 0).mean())
    metrics['avg_mean_median_gap'] = float(valid['mean_median_gap'].mean())

    # Over bets ROI (exploiting mean > median)
    over_bets = bets[bets['predicted_side'] == 'over']
    if len(over_bets) > 0:
        over_pnl = over_bets['pnl'].sum()
        over_wagered = over_bets['bet_units'].sum()
        metrics['over_bets'] = len(over_bets)
        metrics['over_roi'] = float(over_pnl / max(over_wagered, 1))
        metrics['over_win_rate'] = float(over_bets['bet_won'].mean())
        metrics['over_pnl'] = float(over_pnl)
    else:
        metrics['over_bets'] = 0
        metrics['over_roi'] = 0.0
        metrics['over_win_rate'] = 0.0
        metrics['over_pnl'] = 0.0

    # Under bets ROI
    under_bets = bets[bets['predicted_side'] == 'under']
    if len(under_bets) > 0:
        under_pnl = under_bets['pnl'].sum()
        under_wagered = under_bets['bet_units'].sum()
        metrics['under_bets'] = len(under_bets)
        metrics['under_roi'] = float(under_pnl / max(under_wagered, 1))
        metrics['under_win_rate'] = float(under_bets['bet_won'].mean())
        metrics['under_pnl'] = float(under_pnl)
    else:
        metrics['under_bets'] = 0
        metrics['under_roi'] = 0.0
        metrics['under_win_rate'] = 0.0
        metrics['under_pnl'] = 0.0

    # Overs where mean > median by 0.3+
    strong_over_mask = (bets['predicted_side'] == 'over') & (bets['mean_median_gap'] >= 0.3)
    strong_overs = bets[strong_over_mask]
    if len(strong_overs) > 0:
        so_pnl = strong_overs['pnl'].sum()
        so_wagered = strong_overs['bet_units'].sum()
        metrics['strong_over_bets'] = len(strong_overs)
        metrics['strong_over_roi'] = float(so_pnl / max(so_wagered, 1))
        metrics['strong_over_win_rate'] = float(strong_overs['bet_won'].mean())
    else:
        metrics['strong_over_bets'] = 0
        metrics['strong_over_roi'] = 0.0
        metrics['strong_over_win_rate'] = 0.0

    # === DISTRIBUTION VALIDATION ===
    valid_sims = df[df['fit_success'] == True]
    metrics['avg_skewness'] = float(valid_sims['skewness'].mean()) if 'skewness' in valid_sims.columns else 0.0
    metrics['nbinom_preferred_pct'] = float(valid_sims['nbinom_preferred'].mean()) if 'nbinom_preferred' in valid_sims.columns else 0.0

    # === CALIBRATION ===
    calibration = compute_calibration(bets)
    metrics['calibration'] = calibration

    # === BANKROLL ===
    # Compute drawdown on BET ROWS ONLY for accurate measurement
    if 'bankroll' in df.columns:
        # Overall bankroll (for charting, includes all rows)
        bankroll = df['bankroll'].values
        metrics['starting_bankroll'] = 1000.0
        metrics['ending_bankroll'] = float(bankroll[-1]) if len(bankroll) > 0 else 1000.0

        # Drawdown on bets only (accurate)
        if len(bets) > 0:
            bet_cum_pnl = bets['pnl'].cumsum()
            bet_bankroll = 1000.0 + bet_cum_pnl.values
            peak = np.maximum.accumulate(bet_bankroll)
            drawdown = peak - bet_bankroll
            max_dd = float(np.max(drawdown))
            max_dd_pct = float(max_dd / np.max(peak) * 100) if np.max(peak) > 0 else 0.0
        else:
            max_dd = 0.0
            max_dd_pct = 0.0

        metrics['max_drawdown'] = max_dd
        metrics['max_drawdown_pct'] = max_dd_pct

        # Daily bankroll values for charting
        daily_bankroll = df.groupby('game_date')['bankroll'].last().reset_index()
        daily_bankroll.columns = ['date', 'bankroll']
        metrics['daily_bankroll'] = daily_bankroll.to_dict('records')
    else:
        metrics['starting_bankroll'] = 1000.0
        metrics['ending_bankroll'] = 1000.0
        metrics['max_drawdown'] = 0.0
        metrics['max_drawdown_pct'] = 0.0
        metrics['daily_bankroll'] = []

    # === NULL MODEL BASELINE ===
    # What if we bet EVERY over with no model? (tests if lines are fair)
    valid_lines = df[~df['market_line'].isna()].copy()
    if len(valid_lines) > 0:
        all_over_rate = (valid_lines['actual_ks'] > valid_lines['market_line']).mean()
        metrics['null_over_rate'] = float(all_over_rate)
    else:
        metrics['null_over_rate'] = 0.5

    # === TOP PERFORMERS ===
    if len(bets) > 0:
        pitcher_pnl = bets.groupby('pitcher_name').agg(
            total_pnl=('pnl', 'sum'),
            bets=('pnl', 'count'),
            wins=('bet_won', 'sum'),
        ).reset_index()
        pitcher_pnl['win_rate'] = pitcher_pnl['wins'] / pitcher_pnl['bets']

        top_10 = pitcher_pnl.nlargest(10, 'total_pnl')
        bottom_10 = pitcher_pnl.nsmallest(10, 'total_pnl')

        metrics['top_10_pitchers'] = top_10.to_dict('records')
        metrics['bottom_10_pitchers'] = bottom_10.to_dict('records')
    else:
        metrics['top_10_pitchers'] = []
        metrics['bottom_10_pitchers'] = []

    return metrics


def compute_calibration(bets: pd.DataFrame) -> list:
    """Compute calibration table: binned probabilities vs actual hit rates."""
    if len(bets) == 0:
        return []

    # Use prob_over for over bets, prob_under for under bets
    bets = bets.copy()
    bets['model_prob'] = np.where(
        bets['predicted_side'] == 'over',
        bets['prob_over'],
        bets['prob_under']
    )

    bins = [(0.50, 0.55), (0.55, 0.60), (0.60, 0.65), (0.65, 0.70),
            (0.70, 0.75), (0.75, 0.80), (0.80, 0.85), (0.85, 0.90), (0.90, 1.0)]

    calibration = []
    for low, high in bins:
        bin_bets = bets[(bets['model_prob'] >= low) & (bets['model_prob'] < high)]
        if len(bin_bets) > 0:
            actual_rate = float(bin_bets['bet_won'].mean())
            calibration.append({
                'bin': f"{low:.0%}-{high:.0%}",
                'predicted_avg': float(bin_bets['model_prob'].mean()),
                'actual_rate': actual_rate,
                'count': len(bin_bets),
            })
        else:
            calibration.append({
                'bin': f"{low:.0%}-{high:.0%}",
                'predicted_avg': (low + high) / 2,
                'actual_rate': None,
                'count': 0,
            })

    return calibration


def print_summary_report(metrics: dict) -> str:
    """Generate and print the full summary report."""

    # Determine verdict with realistic thresholds
    overall_roi = metrics['roi'] * 100
    over_roi = metrics['over_roi'] * 100
    null_rate = metrics.get('null_over_rate', 0.5) * 100
    win_rate = metrics['win_rate'] * 100

    # Evaluate thesis:
    # Original claim: mean > median (NegBin skew) creates systematic OVER edge
    # Test: does the model profit? And is it driven by overs specifically?
    over_count = metrics.get('over_bets', 0)
    under_count = metrics.get('under_bets', 0)
    over_pct = over_count / max(over_count + under_count, 1)

    if overall_roi > 2 and win_rate > 53 and over_pct > 0.6 and over_roi > 3:
        verdict = "THESIS CONFIRMED — over edge from mean-median gap"
    elif overall_roi > 2 and win_rate > 53:
        verdict = "MODEL PROFITABLE — but edge is from forecasting, not mean-median gap"
    elif overall_roi > 0 and win_rate > 52:
        verdict = "THESIS INCONCLUSIVE — marginal edge"
    elif overall_roi > -2:
        verdict = "THESIS INCONCLUSIVE — no clear edge after vig"
    else:
        verdict = "THESIS REJECTED"

    report = f"""
{'=' * 55}
RTM PICKS — CORRECTED BACKTEST RESULTS
Audit completed. Bugs found and fixed.
Phase 1 | 2019-2025 | Pitcher Strikeouts
{'=' * 55}

THESIS VALIDATION: MEAN VS MEDIAN GAP
  Starts where mean > median: {metrics['mean_gt_median_pct']*100:.1f}%
  Average gap (K): {metrics['avg_mean_median_gap']:.3f}
  Over-only ROI (exploiting gap): {metrics['over_roi']*100:+.1f}%
  Over-only win rate: {metrics['over_win_rate']*100:.1f}%
  Strong overs (gap >= 0.3): {metrics['strong_over_bets']} bets, {metrics['strong_over_roi']*100:+.1f}% ROI

OVERALL PERFORMANCE:
  Total starts analyzed: {metrics['total_starts']:,}
  Total bets placed: {metrics['total_bets']:,}
  Win rate: {metrics['win_rate']*100:.1f}%
  ROI: {metrics['roi']*100:+.1f}%
  Units profit: {metrics['total_pnl']:+.1f}

BY TIER:"""

    for tier in ['A+', 'A', 'B']:
        t = metrics['by_tier'].get(tier, {})
        if t.get('bets', 0) > 0:
            report += f"\n  {tier:3s} ({_tier_desc(tier)}): {t['bets']:>5} bets | {t['win_rate']*100:.1f}% win rate | {t['roi']*100:+.1f}% ROI | {t['pnl']:+.1f} units"
        else:
            report += f"\n  {tier:3s} ({_tier_desc(tier)}): 0 bets"

    report += f"""

BY SEASON:"""
    for season, s in sorted(metrics['by_season'].items()):
        if s.get('bets', 0) > 0:
            report += f"\n  {season}: {s['bets']:>5} bets | {s['win_rate']*100:.1f}% WR | {s['roi']*100:+.1f}% ROI | {s['pnl']:+.1f} units"
        else:
            report += f"\n  {season}: {s.get('starts', 0):>5} starts (no qualifying bets)"

    report += f"""

BANKROLL:
  Starting: 1,000 units
  Ending: {metrics['ending_bankroll']:,.1f} units
  Max drawdown: {metrics['max_drawdown']:.1f} units ({metrics['max_drawdown_pct']:.1f}%)

DISTRIBUTION FIT:
  NegBin preferred: {metrics['nbinom_preferred_pct']*100:.1f}% of starts
  Average skewness: {metrics['avg_skewness']:.3f}

CALIBRATION:"""

    for cal in metrics.get('calibration', []):
        if cal['count'] > 0 and cal['actual_rate'] is not None:
            report += f"\n  {cal['bin']:>9s}: predicted {cal['predicted_avg']:.1%} → actual {cal['actual_rate']:.1%} ({cal['count']} bets)"
        else:
            report += f"\n  {cal['bin']:>9s}: no bets"

    report += f"""

TOP 10 MOST PROFITABLE PITCHERS:"""
    for i, p in enumerate(metrics.get('top_10_pitchers', [])[:10]):
        report += f"\n  {i+1:2d}. {p['pitcher_name']:<25s} {p['total_pnl']:+.1f} units ({p['bets']} bets, {p['win_rate']*100:.0f}% WR)"

    report += f"""

TOP 10 WORST PITCHERS TO BET:"""
    for i, p in enumerate(metrics.get('bottom_10_pitchers', [])[:10]):
        report += f"\n  {i+1:2d}. {p['pitcher_name']:<25s} {p['total_pnl']:+.1f} units ({p['bets']} bets, {p['win_rate']*100:.0f}% WR)"

    report += f"""

OVER vs UNDER BREAKDOWN:
  Over bets: {metrics['over_bets']} | {metrics['over_win_rate']*100:.1f}% WR | {metrics['over_roi']*100:+.1f}% ROI
  Under bets: {metrics['under_bets']} | {metrics['under_win_rate']*100:.1f}% WR | {metrics['under_roi']*100:+.1f}% ROI

NULL MODEL BASELINE:
  Blind over rate (all starts): {metrics.get('null_over_rate', 0.5)*100:.1f}%
  Breakeven at -110: 52.4%

{'=' * 55}
VERDICT: {verdict}
{'=' * 55}
"""

    print(report)
    return report, verdict


def _tier_desc(tier: str) -> str:
    """Get tier description."""
    return {
        'A+': '7%+ edge',
        'A': '5-7% edge',
        'B': '3-5% edge',
        'Monitor': '1-3% edge',
    }.get(tier, '')


def save_metrics(metrics: dict, report: str) -> None:
    """Save metrics to JSON and report to text file."""
    # Save summary stats JSON (exclude non-serializable items)
    json_metrics = {k: v for k, v in metrics.items() if k != 'daily_bankroll'}
    json_metrics['daily_bankroll_count'] = len(metrics.get('daily_bankroll', []))

    json_path = RESULTS_DIR / "summary_stats.json"
    with open(json_path, 'w') as f:
        json.dump(json_metrics, f, indent=2, default=str)
    print(f"Saved summary stats to {json_path}")

    # Save report text
    report_path = RESULTS_DIR / "summary_report.txt"
    with open(report_path, 'w') as f:
        f.write(report)
    print(f"Saved summary report to {report_path}")


def run_metrics(backtest_df: pd.DataFrame) -> dict:
    """Run all metrics computation and reporting."""
    print("=" * 60)
    print("RTM PICKS — METRICS")
    print("=" * 60)

    metrics = compute_all_metrics(backtest_df)
    report, verdict = print_summary_report(metrics)
    save_metrics(metrics, report)

    return metrics


if __name__ == "__main__":
    input_path = RESULTS_DIR / "strikeout_backtest.parquet"
    backtest_df = pd.read_parquet(input_path)
    metrics = run_metrics(backtest_df)
