"""
RTM Picks — MLB Strikeout Model: Simulator (CORRECTED)
Fits negative binomial / Poisson distributions to trailing K data,
runs 10,000 simulations per start, and detects market edge.

AUDIT FIXES APPLIED:
  1. Market line derived from trailing MEAN (independent of model),
     not from the model's own simulation median (circular logic).
  2. When variance <= mean (equidispersed), use Poisson instead of
     artificially inflating variance to force NegBin overdispersion.
  3. Use AIC to pick the best distribution — don't always force NegBin.
  4. Both over AND under bets are possible (not 99.98% overs).
"""

import ast
import math
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

warnings.filterwarnings("ignore")

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Simulation parameters
N_SIMULATIONS = 10000
MIN_TRAILING_STARTS = 5
BREAKEVEN_PROB = 0.5238  # Implied probability at -110 juice (110/210)
HALF_LINES = np.arange(2.5, 13.0, 1.0)  # 2.5 to 12.5


def fit_negative_binomial(data: np.ndarray) -> dict:
    """Fit a negative binomial distribution to strikeout data.

    Uses method of moments. Only fits when data is genuinely overdispersed
    (variance > mean). Does NOT artificially inflate variance.

    Returns:
        Dict with 'n', 'p', 'success' flag.
    """
    if len(data) < MIN_TRAILING_STARTS:
        return {'n': None, 'p': None, 'success': False}

    mean_val = np.mean(data)
    var_val = np.var(data, ddof=1) if len(data) > 1 else mean_val

    # NegBin requires genuine overdispersion (variance > mean).
    # If data is equidispersed or underdispersed, NegBin is not appropriate.
    if var_val <= mean_val:
        return {'n': None, 'p': None, 'success': False, 'reason': 'underdispersed'}

    if mean_val <= 0:
        return {'n': None, 'p': None, 'success': False}

    try:
        # Method of moments
        p = mean_val / var_val
        p = min(max(p, 0.01), 0.99)
        n = mean_val * p / (1 - p)
        n = max(n, 0.5)

        # Validate
        test_mean = n * (1 - p) / p
        if abs(test_mean - mean_val) > mean_val * 0.5:
            raise ValueError("Poor fit")

        return {'n': n, 'p': p, 'success': True, 'method': 'moments'}
    except Exception:
        pass

    return {'n': None, 'p': None, 'success': False}


def fit_poisson(data: np.ndarray) -> dict:
    """Fit a Poisson distribution (lambda = mean)."""
    if len(data) < MIN_TRAILING_STARTS:
        return {'lam': None, 'success': False}

    mean_val = np.mean(data)
    if mean_val <= 0:
        return {'lam': None, 'success': False}

    return {'lam': mean_val, 'success': True}


def compute_aic(data: np.ndarray, dist_name: str, params: dict) -> float:
    """Compute AIC for a fitted distribution."""
    try:
        if dist_name == 'nbinom' and params.get('success'):
            log_lik = np.sum(stats.nbinom.logpmf(data.astype(int), params['n'], params['p']))
            k = 2  # two parameters
        elif dist_name == 'poisson' and params.get('success'):
            log_lik = np.sum(stats.poisson.logpmf(data.astype(int), params['lam']))
            k = 1  # one parameter
        else:
            return np.inf
        return 2 * k - 2 * log_lik
    except Exception:
        return np.inf


def nearest_half_line(x: float) -> float:
    """Round a value to the nearest half-integer (X.5) for a K prop line.

    Sportsbooks set K lines at half-integers (4.5, 5.5, 6.5, etc.).
    This finds the closest one to the given value.

    When the value is equidistant between two half-integers (e.g., x=5.0
    is equidistant from 4.5 and 5.5), we pick the lower one — books
    tend to set K lines slightly below to attract over bettors.
    """
    lower = math.floor(x) + 0.5
    if lower > x:
        lower -= 1.0
    upper = lower + 1.0

    if abs(x - lower) < abs(x - upper):
        return lower
    elif abs(x - upper) < abs(x - lower):
        return upper
    else:
        # Equidistant — pick the lower line
        return lower


def simulate_start(trailing_ks: np.ndarray) -> dict:
    """Run full simulation for a single pitcher start.

    CORRECTED: Market line is derived from the trailing MEAN (a simple,
    independent baseline), NOT from the model's own simulation. The model
    (NegBin/Poisson) is used only for probability estimation against
    this independent line. Edge = model_prob - breakeven.

    Args:
        trailing_ks: Array of pitcher's last N strikeout totals.

    Returns:
        Dict with simulation results, distribution params, and edge detection.
    """
    result = {
        'sim_mean': np.nan,
        'sim_median': np.nan,
        'sim_std': np.nan,
        'mean_median_gap': np.nan,
        'market_line': np.nan,
        'predicted_side': None,
        'edge_pct': np.nan,
        'prob_over': np.nan,
        'prob_under': np.nan,
        'dist_used': None,
        'nbinom_aic': np.nan,
        'poisson_aic': np.nan,
        'skewness': np.nan,
        'nbinom_preferred': False,
        'fit_success': False,
    }

    # Add prob_over columns for each line
    for line in HALF_LINES:
        result[f'prob_over_{line:.1f}'] = np.nan

    if len(trailing_ks) < MIN_TRAILING_STARTS:
        return result

    data = np.array(trailing_ks, dtype=float)

    # =========================================================
    # Step A: Set market line INDEPENDENTLY from trailing mean
    # =========================================================
    trailing_mean = float(np.mean(data))
    market_line = nearest_half_line(trailing_mean)
    market_line = max(0.5, market_line)
    result['market_line'] = market_line

    # =========================================================
    # Step B: Fit distributions
    # =========================================================
    nb_params = fit_negative_binomial(data)
    pois_params = fit_poisson(data)

    # Compute AIC for comparison
    nb_aic = compute_aic(data, 'nbinom', nb_params)
    pois_aic = compute_aic(data, 'poisson', pois_params)
    result['nbinom_aic'] = nb_aic
    result['poisson_aic'] = pois_aic
    result['nbinom_preferred'] = nb_aic < pois_aic

    # =========================================================
    # Step C: Simulate 10,000 outcomes using BEST distribution
    # =========================================================
    # Use AIC to pick the better model, not always NegBin
    simulations = None

    if nb_params['success'] and pois_params['success']:
        # Both fit — use the one with lower AIC
        if nb_aic < pois_aic:
            try:
                simulations = stats.nbinom.rvs(nb_params['n'], nb_params['p'], size=N_SIMULATIONS)
                result['dist_used'] = 'nbinom'
            except Exception:
                simulations = None
        if simulations is None:
            try:
                simulations = stats.poisson.rvs(pois_params['lam'], size=N_SIMULATIONS)
                result['dist_used'] = 'poisson'
            except Exception:
                simulations = None
    elif nb_params['success']:
        try:
            simulations = stats.nbinom.rvs(nb_params['n'], nb_params['p'], size=N_SIMULATIONS)
            result['dist_used'] = 'nbinom'
        except Exception:
            simulations = None
    elif pois_params['success']:
        try:
            simulations = stats.poisson.rvs(pois_params['lam'], size=N_SIMULATIONS)
            result['dist_used'] = 'poisson'
        except Exception:
            simulations = None

    if simulations is None:
        return result

    result['fit_success'] = True
    simulations = simulations.astype(float)

    # Compute simulation statistics
    result['sim_mean'] = float(np.mean(simulations))
    result['sim_median'] = float(np.median(simulations))
    result['sim_std'] = float(np.std(simulations))
    result['mean_median_gap'] = result['sim_mean'] - result['sim_median']
    result['skewness'] = float(stats.skew(simulations))

    # =========================================================
    # Step D: Compute probabilities against INDEPENDENT market line
    # =========================================================
    # Probabilities for each half-point line
    for line in HALF_LINES:
        result[f'prob_over_{line:.1f}'] = float(np.mean(simulations > line))

    # Prob over/under for the MARKET line (set from trailing mean, not model)
    prob_over = float(np.mean(simulations > market_line))
    prob_under = float(np.mean(simulations < market_line))
    result['prob_over'] = prob_over
    result['prob_under'] = prob_under

    # =========================================================
    # Step E: Detect edge — model prob vs breakeven
    # =========================================================
    over_edge = prob_over - BREAKEVEN_PROB
    under_edge = prob_under - BREAKEVEN_PROB

    if over_edge > under_edge and over_edge > 0:
        result['predicted_side'] = 'over'
        result['edge_pct'] = over_edge
    elif under_edge > over_edge and under_edge > 0:
        result['predicted_side'] = 'under'
        result['edge_pct'] = under_edge
    elif over_edge > 0:
        result['predicted_side'] = 'over'
        result['edge_pct'] = over_edge
    elif under_edge > 0:
        result['predicted_side'] = 'under'
        result['edge_pct'] = under_edge
    else:
        result['predicted_side'] = 'none'
        result['edge_pct'] = max(over_edge, under_edge)

    return result


def run_simulations(feature_df: pd.DataFrame) -> pd.DataFrame:
    """Run simulations for all pitcher starts in the feature matrix.

    Args:
        feature_df: Feature matrix from feature_engine.

    Returns:
        DataFrame with simulation results merged with original features.
    """
    print("=" * 60)
    print("RTM PICKS — SIMULATOR (CORRECTED)")
    print(f"Running {N_SIMULATIONS:,} simulations per start")
    print("Market line: trailing mean (independent of model)")
    print("Distribution: AIC-selected (NegBin only if genuinely overdispersed)")
    print("=" * 60)

    total = len(feature_df)
    results = []
    failed_fits = 0

    for idx in range(total):
        row = feature_df.iloc[idx]

        # Parse trailing_20_ks
        trailing_ks = row['trailing_20_ks']
        if isinstance(trailing_ks, str):
            try:
                trailing_ks = ast.literal_eval(trailing_ks)
            except (ValueError, SyntaxError):
                trailing_ks = []
        if not isinstance(trailing_ks, (list, np.ndarray)):
            trailing_ks = []

        trailing_ks = np.array(trailing_ks, dtype=float)

        # Run simulation
        sim_result = simulate_start(trailing_ks)

        if not sim_result['fit_success']:
            failed_fits += 1

        # Determine if the actual result beat the market line
        actual_ks = row['actual_ks']
        market_line = sim_result['market_line']

        if not np.isnan(market_line):
            sim_result['actual_over'] = int(actual_ks > market_line)
            sim_result['actual_under'] = int(actual_ks < market_line)
            sim_result['actual_push'] = int(actual_ks == market_line)
        else:
            sim_result['actual_over'] = np.nan
            sim_result['actual_under'] = np.nan
            sim_result['actual_push'] = np.nan

        results.append(sim_result)

        # Progress
        if (idx + 1) % 500 == 0 or idx == total - 1:
            print(f"  Processing start {idx + 1}/{total}...")

    sim_df = pd.DataFrame(results)

    # Merge with original features
    merge_cols = [c for c in feature_df.columns if c != 'trailing_20_ks']
    combined = pd.concat([feature_df[merge_cols].reset_index(drop=True),
                          sim_df.reset_index(drop=True)], axis=1)

    # Summary stats
    valid = combined[combined['fit_success'] == True]
    n_nbinom = (valid['dist_used'] == 'nbinom').sum()
    n_poisson = (valid['dist_used'] == 'poisson').sum()
    n_over = (valid['predicted_side'] == 'over').sum()
    n_under = (valid['predicted_side'] == 'under').sum()
    n_none = (valid['predicted_side'] == 'none').sum()

    print(f"\nSimulation complete.")
    print(f"  Total starts: {total}")
    print(f"  Failed fits: {failed_fits} ({failed_fits/max(total,1)*100:.1f}%)")
    print(f"  Successful: {total - failed_fits}")
    print(f"  Distribution used: NegBin={n_nbinom}, Poisson={n_poisson}")
    print(f"  Predicted side: Over={n_over}, Under={n_under}, None={n_none}")

    return combined


if __name__ == "__main__":
    from feature_engine import OUTPUT_PATH as FEATURE_PATH
    feature_df = pd.read_parquet(FEATURE_PATH)
    combined = run_simulations(feature_df)
    output_path = PROJECT_ROOT / "data" / "results" / "simulation_results.parquet"
    combined.to_parquet(output_path, index=False)
    print(f"\nSaved to {output_path}")
