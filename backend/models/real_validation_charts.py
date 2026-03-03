"""
RTM Props Model — Real Odds Validation Charts (Phase 3)
Generates 5 charts comparing model predictions to real sportsbook odds.
Same styling as existing charts: dark background, green/red branding.
"""

import warnings
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CHARTS_DIR = PROJECT_ROOT / "data" / "results" / "charts"
CHARTS_DIR.mkdir(parents=True, exist_ok=True)

# RTM branding colors (matches visualize.py)
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


def plot_model_vs_market_lines(df: pd.DataFrame) -> None:
    """Scatter plot: model's reconstructed line vs real consensus line.

    Shows how well the trailing-mean proxy matches actual sportsbook lines.
    """
    setup_style()
    fig, ax = plt.subplots(figsize=(9, 9))

    valid = df[~df['consensus_line'].isna() & ~df['market_line'].isna()].copy()
    if len(valid) == 0:
        plt.close()
        return

    model_lines = valid['market_line']
    real_lines = valid['consensus_line']

    # Scatter with transparency for overlapping points
    ax.scatter(real_lines, model_lines, color=BLUE, alpha=0.15, s=12, edgecolors='none')

    # Perfect agreement line
    line_min = min(real_lines.min(), model_lines.min()) - 0.5
    line_max = max(real_lines.max(), model_lines.max()) + 0.5
    ax.plot([line_min, line_max], [line_min, line_max], color=GRAY, linestyle='--',
            linewidth=1.5, label='Perfect agreement')

    # Correlation and stats
    corr = model_lines.corr(real_lines)
    diff = model_lines - real_lines
    mae = diff.abs().mean()
    pct_within_05 = (diff.abs() <= 0.5).mean() * 100

    # Linear fit
    z = np.polyfit(real_lines, model_lines, 1)
    p = np.poly1d(z)
    x_fit = np.linspace(line_min, line_max, 100)
    ax.plot(x_fit, p(x_fit), color=GREEN, linewidth=2, alpha=0.8,
            label=f'Best fit (r={corr:.3f})')

    ax.set_title('Model Line vs Real Sportsbook Line', fontsize=16, fontweight='bold')
    ax.set_xlabel('Real Consensus Line (K)')
    ax.set_ylabel('Model Reconstructed Line (K)')
    ax.legend(loc='upper left', fontsize=10)
    ax.grid(True, alpha=0.2)
    ax.set_aspect('equal')

    # Stats annotation
    ax.text(0.97, 0.05,
            f'MAE: {mae:.2f} K\nWithin 0.5 K: {pct_within_05:.0f}%\nn = {len(valid):,}',
            transform=ax.transAxes, ha='right', va='bottom',
            fontsize=10, color=WHITE, bbox=dict(boxstyle='round', facecolor='black', alpha=0.6))

    plt.tight_layout()
    path = CHARTS_DIR / 'model_vs_market_lines.png'
    plt.savefig(path, bbox_inches='tight', facecolor='black')
    plt.close()
    print(f"  Saved {path}")


def plot_edge_survival(df: pd.DataFrame) -> None:
    """Bar chart showing how many bets survive at various real-edge thresholds.

    X-axis: edge threshold (0%, 1%, 2%, 3%)
    Y-axis: ROI at that threshold
    Annotations: number of surviving bets
    """
    setup_style()
    fig, ax = plt.subplots(figsize=(10, 6))

    bets = df[(df['is_bet'] == True) & (df['predicted_side'] != 'none')].copy()
    non_push = bets[~bets['real_won'].isna()].copy()

    if len(non_push) == 0 or 'real_edge_consensus' not in non_push.columns:
        plt.close()
        return

    thresholds = [0.0, 0.01, 0.02, 0.03, 0.05]
    labels = ['0%', '1%', '2%', '3%', '5%']
    rois = []
    counts = []

    for thresh in thresholds:
        surviving = non_push[non_push['real_edge_consensus'] > thresh]
        n = len(surviving)
        pnl = surviving['real_pnl_consensus'].sum() if n > 0 else 0
        roi = pnl / max(n, 1) * 100
        rois.append(roi)
        counts.append(n)

    colors = [GREEN if r >= 0 else RED for r in rois]
    bars = ax.bar(labels, rois, color=colors, edgecolor='white', linewidth=0.5, width=0.5)

    # Annotate with bet counts and ROI
    for bar, roi, count in zip(bars, rois, counts):
        y_pos = bar.get_height() + 0.3 if roi >= 0 else bar.get_height() - 0.8
        ax.text(bar.get_x() + bar.get_width() / 2, y_pos,
                f'{roi:+.1f}%\n({count:,} bets)', ha='center', va='bottom',
                fontsize=10, color=WHITE)

    ax.axhline(y=0, color=WHITE, linewidth=0.8)
    ax.set_title('Edge Survival — ROI at Real Edge Thresholds', fontsize=16, fontweight='bold')
    ax.set_xlabel('Minimum Real Edge (Model Prob - Breakeven)')
    ax.set_ylabel('ROI (%)')
    ax.grid(True, alpha=0.2, axis='y')

    plt.tight_layout()
    path = CHARTS_DIR / 'edge_survival.png'
    plt.savefig(path, bbox_inches='tight', facecolor='black')
    plt.close()
    print(f"  Saved {path}")


def plot_real_vs_reconstructed_roi(df: pd.DataFrame) -> None:
    """Grouped bar chart comparing reconstructed ROI vs real ROI by season.

    Side-by-side bars for each season show how much edge survives real vig.
    """
    setup_style()
    fig, ax = plt.subplots(figsize=(12, 7))

    bets = df[(df['is_bet'] == True) & (df['predicted_side'] != 'none')].copy()
    non_push = bets[~bets['real_won'].isna()].copy()

    if len(non_push) == 0:
        plt.close()
        return

    seasons = sorted(non_push['season'].unique())
    recon_rois = []
    real_rois = []
    best_rois = []

    for season in seasons:
        s = non_push[non_push['season'] == season]
        n = len(s)
        if n == 0:
            recon_rois.append(0)
            real_rois.append(0)
            best_rois.append(0)
            continue

        wagered = s['bet_units'].sum() if 'bet_units' in s.columns else n
        recon_rois.append(s['pnl'].sum() / max(wagered, 1) * 100)
        real_rois.append(s['real_pnl_consensus'].sum() / max(n, 1) * 100)
        best_rois.append(s['real_pnl_best'].sum() / max(n, 1) * 100)

    x = np.arange(len(seasons))
    width = 0.25

    bars1 = ax.bar(x - width, recon_rois, width, label='Reconstructed (-110)',
                   color=BLUE, edgecolor='white', linewidth=0.3, alpha=0.8)
    bars2 = ax.bar(x, real_rois, width, label='Real (Consensus)',
                   color=YELLOW, edgecolor='white', linewidth=0.3, alpha=0.8)
    bars3 = ax.bar(x + width, best_rois, width, label='Real (Best Line)',
                   color=GREEN, edgecolor='white', linewidth=0.3, alpha=0.8)

    # Value labels
    for bars in [bars1, bars2, bars3]:
        for bar in bars:
            h = bar.get_height()
            if abs(h) > 0.3:
                ax.text(bar.get_x() + bar.get_width() / 2, h + 0.2,
                        f'{h:+.1f}%', ha='center', va='bottom', fontsize=8, color=WHITE)

    ax.set_xticks(x)
    ax.set_xticklabels([str(int(s)) for s in seasons])
    ax.axhline(y=0, color=WHITE, linewidth=0.8)
    ax.set_title('Reconstructed vs Real ROI by Season', fontsize=16, fontweight='bold')
    ax.set_xlabel('Season')
    ax.set_ylabel('ROI (%)')
    ax.legend(loc='upper left', fontsize=10)
    ax.grid(True, alpha=0.2, axis='y')

    plt.tight_layout()
    path = CHARTS_DIR / 'real_vs_reconstructed_roi.png'
    plt.savefig(path, bbox_inches='tight', facecolor='black')
    plt.close()
    print(f"  Saved {path}")


def plot_real_bankroll_curve(df: pd.DataFrame) -> None:
    """Cumulative bankroll curve using real sportsbook P&L.

    Shows three lines: reconstructed, consensus odds, and best-line odds.
    """
    setup_style()
    fig, ax = plt.subplots(figsize=(14, 7))

    bets = df[(df['is_bet'] == True) & (df['predicted_side'] != 'none')].copy()
    non_push = bets[~bets['real_won'].isna()].copy()
    non_push = non_push.sort_values('game_date')

    if len(non_push) == 0:
        plt.close()
        return

    starting = 1000
    non_push['recon_cumulative'] = starting + non_push['pnl'].cumsum()
    non_push['real_consensus_cumulative'] = starting + non_push['real_pnl_consensus'].cumsum()
    non_push['real_best_cumulative'] = starting + non_push['real_pnl_best'].cumsum()

    ax.plot(non_push['game_date'], non_push['recon_cumulative'],
            color=BLUE, linewidth=1.2, alpha=0.7, label='Reconstructed (-110)')
    ax.plot(non_push['game_date'], non_push['real_consensus_cumulative'],
            color=YELLOW, linewidth=1.5, alpha=0.9, label='Real (Consensus Odds)')
    ax.plot(non_push['game_date'], non_push['real_best_cumulative'],
            color=GREEN, linewidth=1.5, alpha=0.9, label='Real (Best Line)')

    ax.axhline(y=starting, color=GRAY, linestyle='--', alpha=0.5, label='Starting Bankroll')

    # Fill green/red for consensus curve
    ax.fill_between(non_push['game_date'], non_push['real_consensus_cumulative'], starting,
                     where=non_push['real_consensus_cumulative'] >= starting,
                     color=YELLOW, alpha=0.08)
    ax.fill_between(non_push['game_date'], non_push['real_consensus_cumulative'], starting,
                     where=non_push['real_consensus_cumulative'] < starting,
                     color=RED, alpha=0.08)

    ax.set_title('Real Odds Bankroll Curve — Model vs Sportsbooks', fontsize=16, fontweight='bold')
    ax.set_xlabel('Date')
    ax.set_ylabel('Bankroll (Units)')
    ax.legend(loc='upper left', fontsize=10)
    ax.grid(True, alpha=0.2)

    # Final P&L annotation
    final_recon = non_push['recon_cumulative'].iloc[-1]
    final_real = non_push['real_consensus_cumulative'].iloc[-1]
    final_best = non_push['real_best_cumulative'].iloc[-1]
    ax.text(0.97, 0.05,
            f'Final P&L:\n  Reconstructed: {final_recon - starting:+.1f}u\n'
            f'  Consensus: {final_real - starting:+.1f}u\n'
            f'  Best Line: {final_best - starting:+.1f}u',
            transform=ax.transAxes, ha='right', va='bottom',
            fontsize=10, color=WHITE, bbox=dict(boxstyle='round', facecolor='black', alpha=0.6))

    plt.tight_layout()
    path = CHARTS_DIR / 'real_bankroll_curve.png'
    plt.savefig(path, bbox_inches='tight', facecolor='black')
    plt.close()
    print(f"  Saved {path}")


def plot_vig_distribution(df: pd.DataFrame) -> None:
    """Histogram of overround (vig) across all matched markets.

    Shows the distribution of juice the model must overcome.
    """
    setup_style()
    fig, ax = plt.subplots(figsize=(10, 6))

    if 'overround' not in df.columns:
        plt.close()
        return

    valid = df[~df['overround'].isna()]['overround']
    if len(valid) == 0:
        plt.close()
        return

    # Convert to vig percentage: (overround - 1) * 100
    vig_pct = (valid - 1) * 100

    n, bins, patches = ax.hist(vig_pct, bins=40, edgecolor='white', linewidth=0.3, alpha=0.8)

    # Color bins: lighter for lower vig, darker red for higher
    for patch, left_edge in zip(patches, bins[:-1]):
        if left_edge < 3:
            patch.set_facecolor(GREEN)
        elif left_edge < 6:
            patch.set_facecolor(YELLOW)
        else:
            patch.set_facecolor(RED)

    avg_vig = vig_pct.mean()
    median_vig = vig_pct.median()

    ax.axvline(x=avg_vig, color=WHITE, linewidth=2, linestyle='-',
               label=f'Mean vig: {avg_vig:.1f}%')
    ax.axvline(x=median_vig, color=GRAY, linewidth=1.5, linestyle='--',
               label=f'Median vig: {median_vig:.1f}%')

    ax.set_title('Sportsbook Vig Distribution (Strikeout Props)', fontsize=16, fontweight='bold')
    ax.set_xlabel('Vig / Overround (%)')
    ax.set_ylabel('Count')
    ax.legend(loc='upper right', fontsize=10)
    ax.grid(True, alpha=0.2)

    # Annotation
    ax.text(0.97, 0.75,
            f'n = {len(valid):,} markets\n'
            f'Min: {vig_pct.min():.1f}%\n'
            f'Max: {vig_pct.max():.1f}%',
            transform=ax.transAxes, ha='right', va='top',
            fontsize=10, color=WHITE, bbox=dict(boxstyle='round', facecolor='black', alpha=0.6))

    plt.tight_layout()
    path = CHARTS_DIR / 'vig_distribution.png'
    plt.savefig(path, bbox_inches='tight', facecolor='black')
    plt.close()
    print(f"  Saved {path}")


def generate_validation_charts(matched_df: pd.DataFrame) -> None:
    """Generate all 5 Phase 3 validation charts."""
    print("\n" + "=" * 60)
    print("RTM PROPS MODEL — VALIDATION CHARTS")
    print("=" * 60)

    print("\nGenerating validation charts...")
    plot_model_vs_market_lines(matched_df)
    plot_edge_survival(matched_df)
    plot_real_vs_reconstructed_roi(matched_df)
    plot_real_bankroll_curve(matched_df)
    plot_vig_distribution(matched_df)

    print(f"\nAll validation charts saved to {CHARTS_DIR}")
