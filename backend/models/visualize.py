"""
RTM Picks — MLB Strikeout Model: Visualization
Generates all charts for the backtest analysis.
"""

import ast
import warnings
from pathlib import Path

import matplotlib
matplotlib.use('Agg')  # Non-interactive backend
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd
import seaborn as sns
from scipy import stats

warnings.filterwarnings("ignore")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RESULTS_DIR = PROJECT_ROOT / "data" / "results"
CHARTS_DIR = RESULTS_DIR / "charts"
CHARTS_DIR.mkdir(parents=True, exist_ok=True)

# RTM branding colors
GREEN = '#16C79A'
RED = '#E74C3C'
BLUE = '#3498DB'
YELLOW = '#F39C12'
WHITE = '#FFFFFF'
GRAY = '#888888'


def setup_style():
    """Set up dark background plotting style."""
    plt.style.use('dark_background')
    plt.rcParams.update({
        'figure.figsize': (12, 7),
        'figure.dpi': 150,
        'font.size': 11,
        'axes.titlesize': 14,
        'axes.labelsize': 12,
    })


def plot_bankroll_curve(df: pd.DataFrame) -> None:
    """Plot cumulative bankroll over time."""
    setup_style()
    fig, ax = plt.subplots(figsize=(14, 7))

    df = df.sort_values('game_date')
    daily = df.groupby('game_date')['bankroll'].last().reset_index()

    ax.plot(daily['game_date'], daily['bankroll'], color=GREEN, linewidth=1.5, alpha=0.9)
    ax.axhline(y=1000, color=GRAY, linestyle='--', alpha=0.5, label='Starting Bankroll')

    # Fill green above 1000, red below
    ax.fill_between(daily['game_date'], daily['bankroll'], 1000,
                     where=daily['bankroll'] >= 1000,
                     color=GREEN, alpha=0.15)
    ax.fill_between(daily['game_date'], daily['bankroll'], 1000,
                     where=daily['bankroll'] < 1000,
                     color=RED, alpha=0.15)

    ax.set_title('RTM Strikeout Model — Bankroll Growth 2019-2025', fontsize=16, fontweight='bold')
    ax.set_xlabel('Date')
    ax.set_ylabel('Bankroll (Units)')
    ax.legend(loc='upper left')
    ax.grid(True, alpha=0.2)

    plt.tight_layout()
    path = CHARTS_DIR / 'bankroll_curve.png'
    plt.savefig(path, bbox_inches='tight', facecolor='black')
    plt.close()
    print(f"  Saved {path}")


def plot_roi_by_season(df: pd.DataFrame) -> None:
    """Bar chart of ROI by season."""
    setup_style()
    fig, ax = plt.subplots(figsize=(10, 6))

    bets = df[(df['is_bet'] == True) & (df['is_push'] == False)].copy()
    season_stats = bets.groupby('season').agg(
        pnl=('pnl', 'sum'),
        wagered=('bet_units', 'sum'),
    ).reset_index()
    season_stats['roi'] = season_stats['pnl'] / season_stats['wagered'] * 100

    colors = [GREEN if r >= 0 else RED for r in season_stats['roi']]
    bars = ax.bar(season_stats['season'].astype(str), season_stats['roi'], color=colors, edgecolor='white', linewidth=0.5)

    # Add value labels
    for bar, roi in zip(bars, season_stats['roi']):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.3,
                f'{roi:+.1f}%', ha='center', va='bottom', fontsize=10, color=WHITE)

    ax.axhline(y=0, color=WHITE, linewidth=0.8)
    ax.set_title('ROI by Season', fontsize=16, fontweight='bold')
    ax.set_xlabel('Season')
    ax.set_ylabel('ROI (%)')
    ax.grid(True, alpha=0.2, axis='y')

    plt.tight_layout()
    path = CHARTS_DIR / 'roi_by_season.png'
    plt.savefig(path, bbox_inches='tight', facecolor='black')
    plt.close()
    print(f"  Saved {path}")


def plot_mean_median_gap(df: pd.DataFrame) -> None:
    """Histogram of mean-median gap across all starts."""
    setup_style()
    fig, ax = plt.subplots(figsize=(10, 6))

    valid = df[~df['mean_median_gap'].isna()]['mean_median_gap']

    # Create histogram
    n, bins, patches = ax.hist(valid, bins=50, edgecolor='white', linewidth=0.3, alpha=0.8)

    # Color positive green, negative red
    for patch, left_edge in zip(patches, bins[:-1]):
        if left_edge >= 0:
            patch.set_facecolor(GREEN)
        else:
            patch.set_facecolor(RED)

    ax.axvline(x=0, color=WHITE, linewidth=1.5, linestyle='--', label='Zero gap')
    ax.axvline(x=valid.mean(), color=YELLOW, linewidth=1.5, linestyle='-', label=f'Mean gap: {valid.mean():.3f}')

    pct_positive = (valid > 0).mean() * 100
    ax.set_title(f'Mean-Median Gap Distribution ({pct_positive:.0f}% positive = right-skewed)',
                 fontsize=14, fontweight='bold')
    ax.set_xlabel('Mean - Median (Strikeouts)')
    ax.set_ylabel('Count')
    ax.legend(loc='upper right')
    ax.grid(True, alpha=0.2)

    plt.tight_layout()
    path = CHARTS_DIR / 'mean_median_gap_distribution.png'
    plt.savefig(path, bbox_inches='tight', facecolor='black')
    plt.close()
    print(f"  Saved {path}")


def plot_calibration(df: pd.DataFrame) -> None:
    """Calibration plot: predicted probability vs actual hit rate."""
    setup_style()
    fig, ax = plt.subplots(figsize=(8, 8))

    bets = df[(df['is_bet'] == True) & (df['is_push'] == False)].copy()
    bets['model_prob'] = np.where(
        bets['predicted_side'] == 'over',
        bets['prob_over'],
        bets['prob_under']
    )

    # Bin into deciles
    bins = np.arange(0.50, 0.95, 0.05)
    bets['prob_bin'] = pd.cut(bets['model_prob'], bins=bins, include_lowest=True)

    cal = bets.groupby('prob_bin', observed=True).agg(
        predicted=('model_prob', 'mean'),
        actual=('bet_won', 'mean'),
        count=('bet_won', 'count'),
    ).dropna()

    # Diagonal reference line (perfect calibration)
    ax.plot([0.45, 0.95], [0.45, 0.95], color=GRAY, linestyle='--', linewidth=1.5, label='Perfect calibration')

    # Plot actual calibration
    sizes = cal['count'] / cal['count'].max() * 200 + 50
    ax.scatter(cal['predicted'], cal['actual'], s=sizes, color=GREEN, zorder=5, edgecolors=WHITE, linewidth=0.5)
    ax.plot(cal['predicted'], cal['actual'], color=GREEN, linewidth=1.5, alpha=0.7)

    ax.set_title('Model Calibration', fontsize=16, fontweight='bold')
    ax.set_xlabel('Predicted Probability')
    ax.set_ylabel('Actual Hit Rate')
    ax.set_xlim(0.45, 0.95)
    ax.set_ylim(0.45, 0.95)
    ax.legend(loc='upper left')
    ax.grid(True, alpha=0.2)
    ax.set_aspect('equal')

    plt.tight_layout()
    path = CHARTS_DIR / 'calibration_plot.png'
    plt.savefig(path, bbox_inches='tight', facecolor='black')
    plt.close()
    print(f"  Saved {path}")


def plot_roi_by_tier(df: pd.DataFrame) -> None:
    """Bar chart comparing ROI across tiers."""
    setup_style()
    fig, ax = plt.subplots(figsize=(8, 6))

    bets = df[(df['is_bet'] == True) & (df['is_push'] == False)].copy()
    tier_stats = []
    for tier in ['A+', 'A', 'B']:
        tier_bets = bets[bets['tier'] == tier]
        if len(tier_bets) > 0:
            pnl = tier_bets['pnl'].sum()
            wagered = tier_bets['bet_units'].sum()
            tier_stats.append({
                'tier': tier,
                'roi': pnl / max(wagered, 1) * 100,
                'bets': len(tier_bets),
            })

    if not tier_stats:
        plt.close()
        return

    tier_df = pd.DataFrame(tier_stats)
    colors = [GREEN if r >= 0 else RED for r in tier_df['roi']]
    bars = ax.bar(tier_df['tier'], tier_df['roi'], color=colors, edgecolor='white', linewidth=0.5, width=0.5)

    for bar, row in zip(bars, tier_df.itertuples()):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.3,
                f'{row.roi:+.1f}%\n({row.bets} bets)', ha='center', va='bottom',
                fontsize=10, color=WHITE)

    ax.axhline(y=0, color=WHITE, linewidth=0.8)
    ax.set_title('ROI by Edge Tier', fontsize=16, fontweight='bold')
    ax.set_xlabel('Tier')
    ax.set_ylabel('ROI (%)')
    ax.grid(True, alpha=0.2, axis='y')

    plt.tight_layout()
    path = CHARTS_DIR / 'roi_by_tier.png'
    plt.savefig(path, bbox_inches='tight', facecolor='black')
    plt.close()
    print(f"  Saved {path}")


def plot_example_distribution(df: pd.DataFrame) -> None:
    """Plot an example NegBin distribution showing mean/median/market line gap."""
    setup_style()
    fig, ax = plt.subplots(figsize=(10, 6))

    # Find a start with a big edge and over prediction
    candidates = df[
        (df['fit_success'] == True) &
        (df['predicted_side'] == 'over') &
        (df['edge_pct'] > 0.05) &
        (df['mean_median_gap'] > 0.3)
    ].copy()

    if len(candidates) == 0:
        # Fallback: any start with positive edge
        candidates = df[
            (df['fit_success'] == True) &
            (df['edge_pct'] > 0.02)
        ].copy()

    if len(candidates) == 0:
        print("  No suitable example found for distribution plot")
        plt.close()
        return

    # Pick one with a clear gap
    example = candidates.nlargest(1, 'mean_median_gap').iloc[0]

    # Reconstruct the distribution from the sim_mean and sim_std
    sim_mean = example['sim_mean']
    sim_std = example['sim_std']
    market_line = example['market_line']
    sim_median = example['sim_median']

    # Fit a NegBin for plotting
    if sim_std > 0 and sim_mean > 0:
        var = sim_std ** 2
        if var <= sim_mean:
            var = sim_mean * 1.1
        p = sim_mean / var
        p = min(max(p, 0.01), 0.99)
        n = sim_mean * p / (1 - p)
        n = max(n, 0.5)

        x = np.arange(0, 20)
        pmf = stats.nbinom.pmf(x, n, p)

        bars = ax.bar(x, pmf, color=BLUE, alpha=0.7, edgecolor='white', linewidth=0.3, label='Neg. Binomial PMF')

        # Mark mean, median, market line
        ax.axvline(x=sim_mean, color=GREEN, linewidth=2.5, linestyle='-', label=f'Mean: {sim_mean:.2f}')
        ax.axvline(x=sim_median, color=YELLOW, linewidth=2.5, linestyle='--', label=f'Median: {sim_median:.1f}')
        ax.axvline(x=market_line, color=RED, linewidth=2.5, linestyle=':', label=f'Market Line: {market_line:.1f}')

        # Shade the "edge" area (above market line)
        for i, (xi, yi) in enumerate(zip(x, pmf)):
            if xi > market_line:
                ax.bar(xi, yi, color=GREEN, alpha=0.4, edgecolor='none')

        pitcher_name = example.get('pitcher_name', 'Unknown')
        game_date = str(example.get('game_date', ''))[:10]
        actual = int(example.get('actual_ks', 0))
        edge = example['edge_pct'] * 100

        ax.set_title(f'{pitcher_name} — {game_date}\n'
                     f'Actual: {actual} Ks | Edge: {edge:+.1f}% | Gap: {sim_mean - sim_median:.2f}',
                     fontsize=14, fontweight='bold')
        ax.set_xlabel('Strikeouts')
        ax.set_ylabel('Probability')
        ax.legend(loc='upper right', fontsize=10)
        ax.grid(True, alpha=0.2)

        # Add annotation explaining the gap
        gap = sim_mean - sim_median
        ax.annotate(f'Mean > Median by {gap:.2f} Ks\n→ Over has edge',
                    xy=(sim_mean, max(pmf) * 0.6),
                    xytext=(sim_mean + 2, max(pmf) * 0.8),
                    fontsize=11, color=GREEN,
                    arrowprops=dict(arrowstyle='->', color=GREEN, lw=1.5))

    plt.tight_layout()
    path = CHARTS_DIR / 'example_distribution.png'
    plt.savefig(path, bbox_inches='tight', facecolor='black')
    plt.close()
    print(f"  Saved {path}")


def generate_all_charts(df: pd.DataFrame) -> None:
    """Generate all visualization charts."""
    print("=" * 60)
    print("RTM PICKS — VISUALIZATION")
    print("=" * 60)

    print("\nGenerating charts...")
    plot_bankroll_curve(df)
    plot_roi_by_season(df)
    plot_mean_median_gap(df)
    plot_calibration(df)
    plot_roi_by_tier(df)
    plot_example_distribution(df)

    print(f"\nAll charts saved to {CHARTS_DIR}")


if __name__ == "__main__":
    input_path = RESULTS_DIR / "strikeout_backtest.parquet"
    df = pd.read_parquet(input_path)
    generate_all_charts(df)
