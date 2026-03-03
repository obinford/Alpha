"""
RTM Props Model — Real Odds Validation (Phase 3)
Validates the model against actual sportsbook odds data.
Computes real P&L, edge survival, and line comparison.
"""

import json
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

from odds_processor import (
    american_to_decimal_profit,
    american_to_implied_prob,
    load_and_process_all_odds,
    match_odds_to_backtest,
)

warnings.filterwarnings("ignore")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RESULTS_DIR = PROJECT_ROOT / "data" / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)


def compute_real_pnl(row: pd.Series) -> dict:
    """Compute P&L using real sportsbook odds for a single bet.

    Returns dict with consensus and best-line P&L.
    """
    predicted_side = row.get("predicted_side", "none")
    actual_ks = row.get("actual_ks", 0)
    real_line = row.get("consensus_line", np.nan)

    if predicted_side == "none" or np.isnan(real_line):
        return {
            "real_won": np.nan, "real_pnl_consensus": 0, "real_pnl_best": 0,
            "real_edge_consensus": np.nan, "real_edge_best": np.nan,
            "real_breakeven_consensus": np.nan,
        }

    # Determine outcome against REAL line
    if predicted_side == "over":
        real_won = actual_ks > real_line
        consensus_price = row.get("consensus_over_price", np.nan)
        best_price = row.get("best_over_price", np.nan)
        model_prob = row.get("prob_over", 0.5)
    else:  # under
        real_won = actual_ks < real_line
        consensus_price = row.get("consensus_under_price", np.nan)
        best_price = row.get("best_under_price", np.nan)
        model_prob = row.get("prob_under", 0.5)

    # Handle push (actual == line; shouldn't happen with .5 lines, but be safe)
    if actual_ks == real_line:
        return {
            "real_won": np.nan, "real_pnl_consensus": 0, "real_pnl_best": 0,
            "real_edge_consensus": 0, "real_edge_best": 0,
            "real_breakeven_consensus": np.nan,
        }

    # Consensus P&L
    if not np.isnan(consensus_price):
        profit_rate = american_to_decimal_profit(consensus_price)
        breakeven = american_to_implied_prob(consensus_price)
        consensus_pnl = profit_rate if real_won else -1.0
        consensus_edge = model_prob - breakeven
    else:
        consensus_pnl = 0
        breakeven = np.nan
        consensus_edge = np.nan

    # Best-line P&L
    if not np.isnan(best_price):
        best_profit = american_to_decimal_profit(best_price)
        best_breakeven = american_to_implied_prob(best_price)
        best_pnl = best_profit if real_won else -1.0
        best_edge = model_prob - best_breakeven
    else:
        best_pnl = 0
        best_edge = np.nan

    return {
        "real_won": bool(real_won),
        "real_pnl_consensus": consensus_pnl,
        "real_pnl_best": best_pnl,
        "real_edge_consensus": consensus_edge,
        "real_edge_best": best_edge,
        "real_breakeven_consensus": breakeven,
    }


def validate_against_real_odds(
    backtest_df: pd.DataFrame,
    real_odds_df: pd.DataFrame,
) -> pd.DataFrame:
    """Full validation of model against real sportsbook odds.

    Joins backtest results with real odds, recomputes P&L and edge.
    """
    print("=" * 60)
    print("RTM PROPS MODEL — REAL ODDS VALIDATION")
    print("=" * 60)

    # Match odds to backtest
    print("\nMatching odds to backtest data...")
    matched = match_odds_to_backtest(real_odds_df, backtest_df)

    if len(matched) == 0:
        print("  No matches found. Cannot validate.")
        return pd.DataFrame()

    # Compute real P&L for each matched bet
    print(f"\nComputing real P&L for {len(matched)} matched starts...")
    real_results = matched.apply(compute_real_pnl, axis=1, result_type="expand")
    matched = pd.concat([matched, real_results], axis=1)

    # Save matched data
    out_path = RESULTS_DIR / "matched_odds_backtest.parquet"
    matched.to_parquet(out_path, index=False)
    print(f"  Saved matched backtest to {out_path}")

    return matched


def generate_validation_report(matched_df: pd.DataFrame, backtest_df: pd.DataFrame) -> str:
    """Generate the full validation report comparing reconstructed vs real odds."""

    df = matched_df.copy()
    df["game_date"] = pd.to_datetime(df["game_date"])

    # Filter to actual bets (is_bet == True)
    bets = df[(df["is_bet"] == True) & (df["predicted_side"] != "none")].copy()
    non_push = bets[~bets["real_won"].isna()].copy()

    # === DATA COVERAGE ===
    total_backtest = len(backtest_df[backtest_df["fit_success"] == True])
    matched_starts = len(df)
    avg_books = df["num_books"].mean() if "num_books" in df.columns else 0

    # === LINE COMPARISON ===
    valid_lines = df[~df["consensus_line"].isna() & ~df["market_line"].isna()].copy()
    line_diff = valid_lines["market_line"] - valid_lines["consensus_line"]
    line_corr = valid_lines["market_line"].corr(valid_lines["consensus_line"]) if len(valid_lines) > 2 else 0

    pct_within_05 = (line_diff.abs() <= 0.5).mean() * 100 if len(line_diff) > 0 else 0
    pct_within_10 = (line_diff.abs() <= 1.0).mean() * 100 if len(line_diff) > 0 else 0
    pct_off_15 = (line_diff.abs() >= 1.5).mean() * 100 if len(line_diff) > 0 else 0
    pct_agree = (line_diff.abs() < 0.01).mean() * 100 if len(line_diff) > 0 else 0

    # === RECONSTRUCTED PERFORMANCE (on matched subset) ===
    recon_bets = non_push[non_push["is_bet"] == True]
    recon_wins = recon_bets["bet_won"].sum() if len(recon_bets) > 0 else 0
    recon_wr = recon_wins / max(len(recon_bets), 1) * 100
    recon_pnl = recon_bets["pnl"].sum() if len(recon_bets) > 0 else 0
    recon_wagered = recon_bets["bet_units"].sum() if len(recon_bets) > 0 else 1
    recon_roi = recon_pnl / max(recon_wagered, 1) * 100

    # === REAL PERFORMANCE (consensus odds) ===
    real_bets = non_push[non_push["is_bet"] == True].copy()
    real_won_mask = real_bets["real_won"] == True
    real_wins = real_won_mask.sum()
    real_wr = real_wins / max(len(real_bets), 1) * 100
    real_pnl = real_bets["real_pnl_consensus"].sum()
    real_roi = real_pnl / max(len(real_bets), 1) * 100  # per unit bet

    # === REAL PERFORMANCE (best line) ===
    best_pnl = real_bets["real_pnl_best"].sum()
    best_roi = best_pnl / max(len(real_bets), 1) * 100

    # === EDGE SURVIVAL ===
    edge_thresholds = [0.0, 0.01, 0.02, 0.03]
    edge_survival = []
    for thresh in edge_thresholds:
        surviving = real_bets[real_bets["real_edge_consensus"] > thresh]
        s_count = len(surviving)
        s_won = (surviving["real_won"] == True).sum() if s_count > 0 else 0
        s_pnl = surviving["real_pnl_consensus"].sum() if s_count > 0 else 0
        s_roi = s_pnl / max(s_count, 1) * 100
        edge_survival.append({
            "threshold": thresh,
            "surviving": s_count,
            "total": len(real_bets),
            "pct": s_count / max(len(real_bets), 1) * 100,
            "roi": s_roi,
        })

    # === BY SEASON ===
    season_results = {}
    for season in sorted(real_bets["season"].unique()):
        s = real_bets[real_bets["season"] == season]
        s_won = (s["real_won"] == True).sum()
        s_pnl = s["real_pnl_consensus"].sum()
        season_results[int(season)] = {
            "bets": len(s),
            "wins": int(s_won),
            "wr": s_won / max(len(s), 1) * 100,
            "roi": s_pnl / max(len(s), 1) * 100,
        }

    # === OVER vs UNDER ===
    over_bets = real_bets[real_bets["predicted_side"] == "over"]
    under_bets = real_bets[real_bets["predicted_side"] == "under"]

    over_wr = (over_bets["real_won"] == True).mean() * 100 if len(over_bets) > 0 else 0
    over_roi = over_bets["real_pnl_consensus"].sum() / max(len(over_bets), 1) * 100 if len(over_bets) > 0 else 0

    under_wr = (under_bets["real_won"] == True).mean() * 100 if len(under_bets) > 0 else 0
    under_roi = under_bets["real_pnl_consensus"].sum() / max(len(under_bets), 1) * 100 if len(under_bets) > 0 else 0

    # === BY TIER ===
    tier_real = {}
    for tier in ["A+", "A", "B"]:
        t = real_bets[real_bets["tier"] == tier]
        if len(t) > 0:
            tier_real[tier] = t["real_pnl_consensus"].sum() / max(len(t), 1) * 100
        else:
            tier_real[tier] = 0

    # === VIG IMPACT ===
    avg_overround = df["overround"].mean() if "overround" in df.columns else np.nan
    avg_vig = (avg_overround - 1) * 100 if not np.isnan(avg_overround) else np.nan
    avg_real_edge = real_bets["real_edge_consensus"].mean() * 100 if len(real_bets) > 0 else 0
    avg_recon_edge = real_bets["edge_pct"].mean() * 100 if len(real_bets) > 0 else 0
    edge_lost = avg_recon_edge - avg_real_edge

    # === VERDICT ===
    if real_roi > 5:
        verdict_text = "MODEL IS PROFITABLE — proceed to Phase 2 feature expansion"
    elif real_roi > 2:
        verdict_text = "MODEL HAS EDGE — Phase 2 features needed to widen it"
    elif real_roi > 0:
        verdict_text = "MODEL IS MARGINAL — significant improvement needed"
    else:
        verdict_text = "MODEL IS UNPROFITABLE — edge does not survive real vig"

    gap = max(0, 5 - real_roi)

    report = f"""
{'=' * 55}
RTM PROPS MODEL — REAL ODDS VALIDATION REPORT
Model vs Actual Sportsbook Lines
{'=' * 55}

DATA COVERAGE:
  Model pitcher starts in period: {total_backtest:,}
  Matched to real odds data: {matched_starts:,} ({matched_starts/max(total_backtest,1)*100:.1f}%)
  Qualifying bets matched: {len(real_bets):,}
  Avg books per market: {avg_books:.1f}

LINE COMPARISON:
  Avg difference (model line - real line): {line_diff.mean():.2f}
  Correlation: {line_corr:.3f}
  Agree exactly: {pct_agree:.1f}%
  Within 0.5 K: {pct_within_05:.1f}%
  Within 1.0 K: {pct_within_10:.1f}%
  Off by 1.5+:  {pct_off_15:.1f}%

RECONSTRUCTED vs REAL PERFORMANCE:
                        Reconstructed    Real (consensus)    Real (best line)
  Qualifying bets:      {len(recon_bets):>5}            {len(real_bets):>5}               {len(real_bets):>5}
  Win rate:             {recon_wr:>5.1f}%           {real_wr:>5.1f}%              {real_wr:>5.1f}%
  ROI:                  {recon_roi:>+5.1f}%           {real_roi:>+5.1f}%              {best_roi:>+5.1f}%
  Units profit:         {recon_pnl:>+8.1f}           {real_pnl:>+8.1f}              {best_pnl:>+8.1f}

EDGE SURVIVAL:
  Backtest edges that survive real vig:"""

    for es in edge_survival:
        report += f"\n    {es['threshold']*100:.0f}%+ edge: {es['surviving']:>5} / {es['total']} bets survive ({es['pct']:.1f}%) | ROI: {es['roi']:+.1f}%"

    report += f"""

REAL ROI BY SEASON:"""
    for season, s in sorted(season_results.items()):
        report += f"\n  {season}: {s['roi']:+.1f}% on {s['bets']} bets ({s['wr']:.1f}% WR)"

    report += f"""

OVER vs UNDER (real odds):
  Over bets:  {len(over_bets):>5} bets | {over_wr:.1f}% win rate | {over_roi:+.1f}% ROI
  Under bets: {len(under_bets):>5} bets | {under_wr:.1f}% win rate | {under_roi:+.1f}% ROI

BY TIER (real odds):
  A+ (7%+ reconstructed edge): {tier_real.get('A+', 0):+.1f}% real ROI
  A  (5-7%):                   {tier_real.get('A', 0):+.1f}% real ROI
  B  (3-5%):                   {tier_real.get('B', 0):+.1f}% real ROI

VIG IMPACT:
  Average overround: {avg_overround:.3f} ({avg_vig:.1f}% vig)
  Average reconstructed edge: {avg_recon_edge:.1f}%
  Average real edge: {avg_real_edge:.1f}%
  Edge lost to real vig: {edge_lost:.1f}%

{'=' * 55}
VERDICT: {verdict_text}
{'=' * 55}

GAP TO CLOSE:
  Current real ROI: {real_roi:+.1f}%
  Target ROI for production: 5%+
  Improvement needed from Phase 2 features: {gap:.1f}%
"""

    print(report)
    return report


def save_validation_results(report: str, matched_df: pd.DataFrame):
    """Save report and summary JSON."""
    # Save report
    report_path = RESULTS_DIR / "real_odds_validation.txt"
    with open(report_path, "w") as f:
        f.write(report)
    print(f"Saved report to {report_path}")

    # Save summary JSON
    summary = {
        "total_matched": len(matched_df),
        "total_bets": len(matched_df[matched_df["is_bet"] == True]),
    }

    if len(matched_df) > 0 and "real_pnl_consensus" in matched_df.columns:
        bets = matched_df[(matched_df["is_bet"] == True) & ~matched_df["real_won"].isna()]
        summary["real_wins"] = int((bets["real_won"] == True).sum())
        summary["real_win_rate"] = float((bets["real_won"] == True).mean()) if len(bets) > 0 else 0
        summary["real_pnl_consensus"] = float(bets["real_pnl_consensus"].sum())
        summary["real_pnl_best"] = float(bets["real_pnl_best"].sum())
        summary["real_roi_consensus"] = float(bets["real_pnl_consensus"].sum() / max(len(bets), 1))
        summary["real_roi_best"] = float(bets["real_pnl_best"].sum() / max(len(bets), 1))

    json_path = RESULTS_DIR / "real_odds_summary.json"
    with open(json_path, "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"Saved summary to {json_path}")


def run_real_validation(backtest_df: pd.DataFrame = None):
    """Full real odds validation pipeline."""
    # Load backtest if not provided
    if backtest_df is None:
        bt_path = RESULTS_DIR / "strikeout_backtest.parquet"
        if not bt_path.exists():
            print("ERROR: No backtest results found. Run the backtest first.")
            return
        backtest_df = pd.read_parquet(bt_path)

    # Load and process odds
    real_odds = load_and_process_all_odds()

    if len(real_odds) == 0:
        print("\nNo real odds data available.")
        print("Run `python models/odds_fetcher.py` to pull historical odds.")

        # Generate placeholder report
        placeholder = f"""
{'=' * 55}
RTM PROPS MODEL — REAL ODDS VALIDATION REPORT
{'=' * 55}

STATUS: AWAITING ODDS DATA

No historical odds data found in data/raw/historical_odds/.

To proceed:
1. Set THE_ODDS_API_KEY in .env
2. Run: python models/odds_fetcher.py
3. Create confirmation file: touch data/raw/historical_odds/.confirmed
4. Re-run: python models/odds_fetcher.py
5. Then re-run this validation: python models/real_validation.py

Estimated credits needed: ~27,000 (2024 season only)
Monthly budget: 100,000 credits at $59/mo

{'=' * 55}
"""
        print(placeholder)
        report_path = RESULTS_DIR / "real_odds_validation.txt"
        with open(report_path, "w") as f:
            f.write(placeholder)
        return

    # Validate against real odds
    matched = validate_against_real_odds(backtest_df, real_odds)

    if len(matched) == 0:
        print("\nNo matches between model and odds data. Check name matching.")
        return

    # Generate report
    report = generate_validation_report(matched, backtest_df)
    save_validation_results(report, matched)

    # Generate charts
    try:
        from real_validation_charts import generate_validation_charts
        generate_validation_charts(matched)
    except ImportError:
        print("\nSkipping validation charts (real_validation_charts not found).")


if __name__ == "__main__":
    run_real_validation()
