"""Monte Carlo prop simulator — the Unabated secret sauce.

Key insight: player stats are positively skewed (can't go below 0, can
have blowup games). The MEAN is always higher than the MEDIAN. Sportsbooks
set lines at the median. Most projection sources give means. If you bet
means against median lines, you bet too many overs and lose.

This simulator converts mean projections into full distributions, finds
the true probabilities of over/under at any line, and calculates fair
odds to detect edges against sportsbooks.

Distribution choices by prop type:
  - Points: Shifted gamma (right-skewed, continuous)
  - Rebounds/Assists: Negative binomial (count-based, right-skewed)
  - Three-pointers: Poisson (discrete rare events)
  - Steals/Blocks: Poisson (very rare events)
  - PRA: Sum of individual component distributions
"""

from __future__ import annotations

import numpy as np
from scipy import stats

from projections.math_utils import (
    american_to_implied_prob,
    implied_prob_to_american,
    american_to_decimal,
)

# Number of simulations per prop.
DEFAULT_SIMS = 10_000

# Prop type to distribution mapping.
GAMMA_PROPS = {"points", "pts_reb_ast"}
NBINOM_PROPS = {"rebounds", "assists"}
POISSON_PROPS = {"threes", "steals", "blocks"}


class PropSimulator:
    """Monte Carlo simulator for player prop probabilities."""

    def __init__(self, num_simulations: int = DEFAULT_SIMS):
        self.num_sims = num_simulations

    def simulate_player_prop(
        self,
        mean: float,
        std_dev: float,
        prop_type: str,
    ) -> np.ndarray:
        """Run Monte Carlo simulation for a player prop.

        Returns a sorted array of simulated values.
        """
        if mean <= 0:
            return np.zeros(self.num_sims)

        # Ensure std_dev is reasonable.
        std_dev = max(std_dev, mean * 0.15)

        if prop_type in GAMMA_PROPS:
            return self._simulate_gamma(mean, std_dev)
        elif prop_type in NBINOM_PROPS:
            return self._simulate_nbinom(mean, std_dev)
        elif prop_type in POISSON_PROPS:
            return self._simulate_poisson(mean, std_dev)
        else:
            # Default to gamma for unknown types.
            return self._simulate_gamma(mean, std_dev)

    def _simulate_gamma(self, mean: float, std_dev: float) -> np.ndarray:
        """Shifted gamma distribution for continuous stats (points, PRA).

        Gamma is naturally right-skewed with a floor at 0.
        shape (alpha) = (mean/std)^2, scale (beta) = std^2/mean.
        """
        alpha = (mean / std_dev) ** 2
        beta = (std_dev ** 2) / mean
        samples = np.random.gamma(alpha, beta, size=self.num_sims)
        return np.sort(samples)

    def _simulate_nbinom(self, mean: float, std_dev: float) -> np.ndarray:
        """Negative binomial distribution for count stats (rebounds, assists).

        Handles overdispersion better than Poisson.
        If variance < mean, falls back to Poisson.
        """
        variance = std_dev ** 2
        if variance <= mean:
            return self._simulate_poisson(mean, std_dev)

        # Negative binomial parameterization.
        p = mean / variance
        p = max(0.01, min(0.99, p))
        r = mean * p / (1 - p)
        r = max(0.1, r)

        samples = np.random.negative_binomial(r, p, size=self.num_sims)
        return np.sort(samples.astype(float))

    def _simulate_poisson(self, mean: float, std_dev: float) -> np.ndarray:
        """Poisson distribution for rare count events (3s, steals, blocks)."""
        lam = max(0.1, mean)
        samples = np.random.poisson(lam, size=self.num_sims)
        return np.sort(samples.astype(float))

    def simulate_pra(
        self,
        pts_mean: float, pts_std: float,
        reb_mean: float, reb_std: float,
        ast_mean: float, ast_std: float,
    ) -> np.ndarray:
        """Simulate PRA by summing individual component simulations.

        This preserves proper correlation structure.
        """
        pts = self._simulate_gamma(pts_mean, pts_std)
        reb = self._simulate_nbinom(reb_mean, reb_std)
        ast = self._simulate_nbinom(ast_mean, ast_std)

        # Shuffle before summing to avoid spurious correlations from sorting.
        np.random.shuffle(pts)
        np.random.shuffle(reb)
        np.random.shuffle(ast)

        pra = pts + reb + ast
        return np.sort(pra)

    def calculate_prop_fair_odds(
        self,
        distribution: np.ndarray,
        line: float,
    ) -> dict:
        """Calculate fair probabilities and odds for a prop line.

        Returns dict with: over_prob, under_prob, fair_over_odds,
        fair_under_odds, median, mean, percentile_25, percentile_75.
        """
        over_count = np.sum(distribution > line)
        under_count = np.sum(distribution <= line)
        total = len(distribution)

        over_prob = over_count / total
        under_prob = under_count / total

        # Clamp to avoid division by zero.
        over_prob = max(0.001, min(0.999, over_prob))
        under_prob = max(0.001, min(0.999, under_prob))

        return {
            "over_prob": round(over_prob, 4),
            "under_prob": round(under_prob, 4),
            "fair_over_odds": implied_prob_to_american(over_prob),
            "fair_under_odds": implied_prob_to_american(under_prob),
            "median": round(float(np.median(distribution)), 1),
            "mean": round(float(np.mean(distribution)), 1),
            "p25": round(float(np.percentile(distribution, 25)), 1),
            "p75": round(float(np.percentile(distribution, 75)), 1),
        }

    def find_prop_edges(
        self,
        player_projection: dict,
        sportsbook_lines: list[dict],
    ) -> list[dict]:
        """Find edges between our projections and sportsbook lines.

        Args:
            player_projection: dict from ProjectionEngine.project_player()
            sportsbook_lines: list of dicts with: prop_type, line, side,
                book, book_odds

        Returns list of edges found.
        """
        edges = []
        projections = player_projection.get("projections", {})
        player_name = player_projection.get("player_name", "")

        for sb_line in sportsbook_lines:
            prop_type = sb_line.get("prop_type", "")
            line = sb_line.get("line")
            side = sb_line.get("side", "").lower()  # "over" or "under"
            book = sb_line.get("book", "")
            book_odds = sb_line.get("book_odds", -110)

            if line is None:
                continue

            # Map prop type to our projection keys.
            proj_key = _prop_type_to_key(prop_type)
            if proj_key not in projections:
                continue

            proj = projections[proj_key]
            mean = proj["mean"]
            std_dev = proj["std_dev"]

            # Run simulation.
            if proj_key == "pts_reb_ast" and all(
                k in projections for k in ("points", "rebounds", "assists")
            ):
                distribution = self.simulate_pra(
                    projections["points"]["mean"],
                    projections["points"]["std_dev"],
                    projections["rebounds"]["mean"],
                    projections["rebounds"]["std_dev"],
                    projections["assists"]["mean"],
                    projections["assists"]["std_dev"],
                )
            else:
                distribution = self.simulate_player_prop(mean, std_dev, proj_key)

            fair = self.calculate_prop_fair_odds(distribution, line)

            # Our probability for the given side.
            our_prob = fair["over_prob"] if side == "over" else fair["under_prob"]
            fair_odds = fair["fair_over_odds"] if side == "over" else fair["fair_under_odds"]

            # Book's implied probability.
            book_implied = american_to_implied_prob(book_odds)

            # Edge = our_fair_prob * sportsbook_decimal_odds - 1.
            book_decimal = american_to_decimal(book_odds)
            edge_pct = round((our_prob * book_decimal - 1) * 100, 2)

            if edge_pct > 0:
                edges.append({
                    "player": player_name,
                    "player_id": player_projection.get("player_id"),
                    "prop_type": prop_type,
                    "prop_key": proj_key,
                    "line": line,
                    "side": side,
                    "book": book,
                    "book_odds": book_odds,
                    "book_implied_prob": round(book_implied, 4),
                    "our_prob": round(our_prob, 4),
                    "fair_odds": fair_odds,
                    "edge_pct": edge_pct,
                    "projection_mean": mean,
                    "projection_median": fair["median"],
                    "projection_std": std_dev,
                })

        return edges

    def get_distribution_data(
        self,
        mean: float,
        std_dev: float,
        prop_type: str,
        line: float | None = None,
    ) -> dict:
        """Generate visualization data for a prop distribution.

        Returns histogram bins, cumulative curve, and fair odds at
        various line values.
        """
        distribution = self.simulate_player_prop(mean, std_dev, prop_type)
        fair = self.calculate_prop_fair_odds(
            distribution, line if line is not None else mean
        )

        # Histogram bins.
        hist_counts, bin_edges = np.histogram(distribution, bins=30)
        histogram = [
            {"bin_start": round(float(bin_edges[i]), 1),
             "bin_end": round(float(bin_edges[i + 1]), 1),
             "count": int(hist_counts[i])}
            for i in range(len(hist_counts))
        ]

        # Fair odds at various line values.
        min_val = max(0, mean - 3 * std_dev)
        max_val = mean + 3 * std_dev
        lines_range = np.linspace(min_val, max_val, 20)
        odds_curve = []
        for l in lines_range:
            f = self.calculate_prop_fair_odds(distribution, l)
            odds_curve.append({
                "line": round(float(l), 1),
                "over_prob": f["over_prob"],
                "under_prob": f["under_prob"],
            })

        return {
            **fair,
            "histogram": histogram,
            "odds_curve": odds_curve,
        }


def _prop_type_to_key(prop_type: str) -> str:
    """Map sportsbook prop type names to our internal keys."""
    mapping = {
        "player_points": "points",
        "player_rebounds": "rebounds",
        "player_assists": "assists",
        "player_threes": "threes",
        "player_blocks": "blocks",
        "player_steals": "steals",
        "player_points_rebounds_assists": "pts_reb_ast",
    }
    return mapping.get(prop_type, prop_type)
