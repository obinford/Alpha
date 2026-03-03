#!/usr/bin/env python3
"""
RTM Picks — MLB Strikeout Model: Full Pipeline Runner
Executes all steps end-to-end: data pull → features → simulation → backtest → metrics → charts.
"""

import sys
import time
from pathlib import Path

# Ensure project root is on path
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "backend" / "models"))

from data_pipeline import run_pipeline
from feature_engine import run_feature_engine
from simulator import run_simulations
from backtester import run_backtest
from metrics import run_metrics
from visualize import generate_all_charts


def main():
    """Run the full MLB strikeout backtest pipeline."""
    start_time = time.time()

    print("\n" + "=" * 60)
    print("RTM PICKS — MLB STRIKEOUT MODEL")
    print("Full Pipeline Execution")
    print("=" * 60 + "\n")

    # Step 1: Data Pipeline
    print("STEP 1/6: Data Pipeline")
    print("-" * 40)
    gamelogs_df = run_pipeline()
    print(f"\n✓ Data pipeline complete: {len(gamelogs_df)} game logs\n")

    # Step 2: Feature Engine
    print("\nSTEP 2/6: Feature Engine")
    print("-" * 40)
    feature_df = run_feature_engine(gamelogs_df)
    print(f"\n✓ Feature engine complete: {len(feature_df)} qualified starts\n")

    # Step 3: Simulator
    print("\nSTEP 3/6: Simulator")
    print("-" * 40)
    sim_df = run_simulations(feature_df)
    print(f"\n✓ Simulator complete: {len(sim_df)} simulated starts\n")

    # Step 4: Backtester
    print("\nSTEP 4/6: Backtester")
    print("-" * 40)
    backtest_df = run_backtest(sim_df)
    print(f"\n✓ Backtester complete\n")

    # Step 5: Metrics
    print("\nSTEP 5/6: Metrics")
    print("-" * 40)
    metrics = run_metrics(backtest_df)
    print(f"\n✓ Metrics complete\n")

    # Step 6: Visualization
    print("\nSTEP 6/6: Visualization")
    print("-" * 40)
    generate_all_charts(backtest_df)
    print(f"\n✓ Visualization complete\n")

    elapsed = time.time() - start_time
    print(f"\n{'=' * 60}")
    print(f"PIPELINE COMPLETE in {elapsed:.1f} seconds")
    print(f"{'=' * 60}")

    # Verify deliverables
    print("\nDeliverables check:")
    deliverables = [
        PROJECT_ROOT / "backend" / "models" / "data_pipeline.py",
        PROJECT_ROOT / "backend" / "models" / "feature_engine.py",
        PROJECT_ROOT / "backend" / "models" / "simulator.py",
        PROJECT_ROOT / "backend" / "models" / "backtester.py",
        PROJECT_ROOT / "backend" / "models" / "metrics.py",
        PROJECT_ROOT / "backend" / "models" / "visualize.py",
        PROJECT_ROOT / "data" / "processed" / "strikeout_features.parquet",
        PROJECT_ROOT / "data" / "results" / "strikeout_backtest.parquet",
        PROJECT_ROOT / "data" / "results" / "summary_stats.json",
        PROJECT_ROOT / "data" / "results" / "summary_report.txt",
    ]

    all_ok = True
    for path in deliverables:
        exists = path.exists()
        status = "✓" if exists else "✗"
        print(f"  {status} {path.relative_to(PROJECT_ROOT)}")
        if not exists:
            all_ok = False

    # Check charts
    charts_dir = PROJECT_ROOT / "data" / "results" / "charts"
    expected_charts = [
        'bankroll_curve.png', 'roi_by_season.png', 'mean_median_gap_distribution.png',
        'calibration_plot.png', 'roi_by_tier.png', 'example_distribution.png',
    ]
    for chart in expected_charts:
        chart_path = charts_dir / chart
        exists = chart_path.exists()
        status = "✓" if exists else "✗"
        print(f"  {status} data/results/charts/{chart}")
        if not exists:
            all_ok = False

    # Check raw CSVs
    raw_dir = PROJECT_ROOT / "data" / "raw" / "pitcher_gamelogs"
    csv_count = len(list(raw_dir.glob("*.csv")))
    print(f"  {'✓' if csv_count > 0 else '✗'} data/raw/pitcher_gamelogs/ ({csv_count} CSV files)")

    if all_ok:
        print("\n✓ All deliverables present!")
    else:
        print("\n⚠ Some deliverables missing")


if __name__ == "__main__":
    main()
