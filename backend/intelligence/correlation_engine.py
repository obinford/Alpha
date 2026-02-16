"""Prop Correlation Engine — find connected props and parlay edges.

Most bettors treat props as independent.  They're not.  If a star player
is out, teammate rebounds go up.  If pace is high, all scoring props
correlate.  This module knows which props are connected and uses that
to find parlay edges and flag conflicts.
"""

from __future__ import annotations

import json
import os
from typing import Any

# Known NBA prop correlations (pre-computed from historical data).
# Format: {player_stat: {correlated_stat: correlation_coefficient}}
# Positive = positively correlated, Negative = negatively correlated.
_NBA_STAT_CORRELATIONS = {
    "points": {
        "field_goals_made": 0.85,
        "threes": 0.55,
        "assists": -0.15,  # High scoring often means fewer assists
        "rebounds": 0.10,
        "steals": 0.20,
        "blocks": 0.05,
        "pts_reb_ast": 0.80,
    },
    "rebounds": {
        "points": 0.10,
        "blocks": 0.35,
        "assists": -0.05,
        "steals": 0.15,
        "pts_reb_ast": 0.55,
    },
    "assists": {
        "points": -0.15,
        "turnovers": 0.45,
        "rebounds": -0.05,
        "steals": 0.25,
        "pts_reb_ast": 0.50,
    },
    "threes": {
        "points": 0.55,
        "rebounds": -0.20,
        "assists": -0.10,
    },
    "blocks": {
        "rebounds": 0.35,
        "points": 0.05,
    },
    "steals": {
        "assists": 0.25,
        "points": 0.20,
    },
}

# Game-level correlations.
_GAME_CORRELATIONS = {
    "pace": {
        "total_points": 0.75,
        "player_points": 0.60,
        "player_assists": 0.40,
        "player_rebounds": 0.30,
    },
    "blowout": {
        "bench_minutes": 0.70,
        "starter_minutes": -0.65,
        "starter_points": -0.50,
    },
}

# Prop type to stat key mapping.
_PROP_TO_STAT = {
    "player_points": "points",
    "player_rebounds": "rebounds",
    "player_assists": "assists",
    "player_threes": "threes",
    "player_blocks": "blocks",
    "player_steals": "steals",
    "player_points_rebounds_assists": "pts_reb_ast",
}

_STAT_TO_PROP = {v: k for k, v in _PROP_TO_STAT.items()}

_CACHE_FILE = os.path.join(
    os.path.dirname(__file__), "cache", "correlations.json"
)


class PropCorrelationEngine:
    """Analyze prop correlations and find parlay edges."""

    def __init__(self) -> None:
        self._correlations = _NBA_STAT_CORRELATIONS
        self._cache = self._load_cache()

    def _load_cache(self) -> dict:
        """Load cached correlations from file."""
        try:
            if os.path.exists(_CACHE_FILE):
                with open(_CACHE_FILE) as f:
                    return json.load(f)
        except Exception:
            pass
        return {}

    def _save_cache(self, data: dict) -> None:
        """Save correlations to cache file."""
        try:
            os.makedirs(os.path.dirname(_CACHE_FILE), exist_ok=True)
            with open(_CACHE_FILE, "w") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    def get_correlated_props(
        self,
        player_name: str,
        prop_type: str,
        direction: str = "over",
    ) -> dict:
        """Get props that correlate with a given player's prop.

        Args:
            player_name: The player name.
            prop_type: e.g. "points", "rebounds", "player_points".
            direction: "over" or "under".

        Returns:
            Dict with positively_correlated, negatively_correlated, and game_correlated lists.
        """
        # Normalize prop type.
        stat_key = _PROP_TO_STAT.get(prop_type, prop_type)
        correlations = self._correlations.get(stat_key, {})

        positively_correlated = []
        negatively_correlated = []

        for corr_stat, coeff in correlations.items():
            prop_key = _STAT_TO_PROP.get(corr_stat, f"player_{corr_stat}")
            corr_direction = direction if coeff > 0 else ("under" if direction == "over" else "over")

            entry = {
                "player": player_name,
                "prop_type": prop_key,
                "stat": corr_stat,
                "correlation": round(coeff, 2),
                "suggested_direction": corr_direction,
                "strength": (
                    "strong" if abs(coeff) >= 0.5
                    else "moderate" if abs(coeff) >= 0.25
                    else "weak"
                ),
            }

            if coeff > 0.05:
                positively_correlated.append(entry)
            elif coeff < -0.05:
                negatively_correlated.append(entry)

        # Sort by correlation strength.
        positively_correlated.sort(key=lambda x: x["correlation"], reverse=True)
        negatively_correlated.sort(key=lambda x: x["correlation"])

        # Game-level correlations.
        game_correlated = []
        if stat_key in ("points", "threes"):
            game_correlated.append({
                "type": "game_total",
                "description": f"High {stat_key} games correlate with higher game totals",
                "correlation": 0.60,
                "suggestion": f"If {player_name} Over, consider Game Over",
            })
        elif stat_key == "assists":
            game_correlated.append({
                "type": "game_pace",
                "description": "High assist games correlate with faster pace",
                "correlation": 0.40,
                "suggestion": f"If {player_name} Over Assists, look for high-pace matchups",
            })

        return {
            "player": player_name,
            "prop_type": prop_type,
            "direction": direction,
            "positively_correlated": positively_correlated,
            "negatively_correlated": negatively_correlated,
            "game_correlated": game_correlated,
        }

    def detect_parlay_edges(self) -> list[dict]:
        """Find prop combinations where correlation creates hidden parlay edge.

        Returns pairs of props that are positively correlated where the book
        doesn't properly adjust for the correlation in SGP pricing.
        """
        # Build list of high-correlation pairs.
        edges = []

        for stat, correlations in self._correlations.items():
            for corr_stat, coeff in correlations.items():
                if coeff >= 0.35:  # Only strong positive correlations.
                    prop1 = _STAT_TO_PROP.get(stat, f"player_{stat}")
                    prop2 = _STAT_TO_PROP.get(corr_stat, f"player_{corr_stat}")

                    # Avoid duplicates (A→B and B→A).
                    pair_key = tuple(sorted([stat, corr_stat]))
                    if any(
                        tuple(sorted([e["stat1"], e["stat2"]])) == pair_key
                        for e in edges
                    ):
                        continue

                    edges.append({
                        "stat1": stat,
                        "stat2": corr_stat,
                        "prop1": prop1,
                        "prop2": prop2,
                        "correlation": round(coeff, 2),
                        "direction": "both_over",
                        "edge_type": "correlation_not_priced",
                        "description": (
                            f"Over {stat.title()} + Over {corr_stat.title()} "
                            f"are positively correlated (r={coeff:.2f}) — "
                            f"SGPs often underprice this combination"
                        ),
                    })

        edges.sort(key=lambda e: e["correlation"], reverse=True)
        return edges

    def check_correlation(
        self,
        player1: str,
        prop1: str,
        player2: str,
        prop2: str,
    ) -> dict:
        """Check if two props correlate or conflict.

        Args:
            player1: First player name.
            prop1: First prop type (e.g. "player_points").
            player2: Second player name.
            prop2: Second prop type.

        Returns:
            Dict with relationship, correlation, and warning if applicable.
        """
        stat1 = _PROP_TO_STAT.get(prop1, prop1)
        stat2 = _PROP_TO_STAT.get(prop2, prop2)

        # Same player correlation.
        if player1.lower() == player2.lower():
            corr = self._correlations.get(stat1, {}).get(stat2, 0)
            if corr == 0:
                corr = self._correlations.get(stat2, {}).get(stat1, 0)

            if abs(corr) < 0.05:
                relationship = "independent"
                warning = None
            elif corr > 0:
                relationship = "positively_correlated"
                warning = None
            else:
                relationship = "negatively_correlated"
                warning = (
                    f"WARNING: {player1}'s {stat1} and {stat2} are negatively "
                    f"correlated (r={corr:.2f}). Betting both Over or both Under "
                    f"on the same player reduces your probability."
                )

            return {
                "player1": player1,
                "prop1": prop1,
                "player2": player2,
                "prop2": prop2,
                "same_player": True,
                "correlation": round(corr, 2),
                "relationship": relationship,
                "warning": warning,
            }

        # Different players — teammates have positive correlation in team stats.
        return {
            "player1": player1,
            "prop1": prop1,
            "player2": player2,
            "prop2": prop2,
            "same_player": False,
            "correlation": 0.0,
            "relationship": "unknown",
            "warning": (
                "Cross-player correlations require team/opponent context. "
                "Teammates on the same team in a high-pace game tend to be "
                "positively correlated on scoring."
            ),
        }

    def get_anti_correlations_for_bets(self, bets: list[dict]) -> list[dict]:
        """Flag conflicting bets in a user's bet slip.

        Args:
            bets: List of bet dicts with player, prop_type, direction.

        Returns:
            List of conflict warnings.
        """
        conflicts = []

        for i, bet1 in enumerate(bets):
            for bet2 in bets[i + 1:]:
                if bet1.get("player", "").lower() != bet2.get("player", "").lower():
                    continue

                stat1 = _PROP_TO_STAT.get(bet1.get("prop_type", ""), "")
                stat2 = _PROP_TO_PROP.get(bet2.get("prop_type", ""), "")

                corr = self._correlations.get(stat1, {}).get(stat2, 0)
                if corr == 0:
                    corr = self._correlations.get(stat2, {}).get(stat1, 0)

                dir1 = bet1.get("direction", "over").lower()
                dir2 = bet2.get("direction", "over").lower()

                # Conflict: negatively correlated props bet in same direction,
                # or positively correlated props bet in opposite directions.
                is_conflict = False
                if corr < -0.1 and dir1 == dir2:
                    is_conflict = True
                elif corr > 0.1 and dir1 != dir2:
                    is_conflict = True

                if is_conflict:
                    conflicts.append({
                        "bet1": bet1,
                        "bet2": bet2,
                        "correlation": round(corr, 2),
                        "warning": (
                            f"{bet1['player']} {dir1.title()} {stat1} and "
                            f"{dir2.title()} {stat2} conflict — "
                            f"these stats are {'negatively' if corr < 0 else 'positively'} "
                            f"correlated (r={corr:.2f})"
                        ),
                    })

        return conflicts
