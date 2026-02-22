"""RTM Signal — confluence model for high-confidence betting signals.

Combines up to five independent systems:
  1. +EV from devigged sharp books (top-down)
  2. Steam detection / line movement confirmation
  3. In-house player projections + simulation (bottom-up, NBA only)
  4. Market consensus — how many books show +EV on the same side
  5. Intelligence layers — stale lines, book profiling, market timing, correlations

Sport-adaptive weights (with intelligence):
  NBA (5 components): ev=0.25, steam=0.15, projection=0.25, consensus=0.15, intelligence=0.20
  Other sports (4 components): ev=0.40, steam=0.20, consensus=0.20, intelligence=0.20

Signal tiers:
  70+ → STRONG SIGNAL (5 stars)
  55+ → SIGNAL (4 stars)
  40+ → LEAN (3 stars)
  <40 → no signal
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from projections.simulator import PropSimulator, _prop_type_to_key
from projections.math_utils import american_to_decimal, american_to_implied_prob

# ---------------------------------------------------------------------------
# Sport-adaptive weights
# ---------------------------------------------------------------------------

# NBA uses all 5 components including projections + intelligence.
NBA_WEIGHTS = {
    "ev": 0.25,
    "steam": 0.15,
    "projection": 0.25,
    "consensus": 0.15,
    "intelligence": 0.20,
}

# CBB uses KenPom game-level projections (less weight than NBA player projections).
CBB_WEIGHTS = {
    "ev": 0.30,
    "steam": 0.15,
    "projection": 0.20,
    "consensus": 0.15,
    "intelligence": 0.20,
}

# All other sports use 4 components (no projection data available).
DEFAULT_WEIGHTS = {
    "ev": 0.40,
    "steam": 0.20,
    "projection": 0.00,
    "consensus": 0.20,
    "intelligence": 0.20,
}

# NBA prop weights (projection is more important for props).
NBA_PROP_WEIGHTS = {
    "ev": 0.20,
    "steam": 0.15,
    "projection": 0.30,
    "consensus": 0.15,
    "intelligence": 0.20,
}

# Signal tier thresholds.
TIER_STRONG = 70
TIER_SIGNAL = 55
TIER_LEAN = 40

# Star ratings.
STAR_RATINGS = {5: TIER_STRONG, 4: TIER_SIGNAL, 3: TIER_LEAN}

# Odds range for signals: only fire on -160 to +150 (inclusive).
# Targets high win-rate plays, not longshots or heavy favorites.
SIGNAL_MIN_ODDS = -160
SIGNAL_MAX_ODDS = 150

# Sportsbooks to never include in signals (removed from scanner, stale data).
_BLOCKED_SIGNAL_BOOKS: set[str] = {"betopenly", "betparx"}

# Flat bet amount for all signals ($100).
SIGNAL_BET_AMOUNT = 100.0

# Sports that have projection support.
_PROJECTION_SPORTS = {"basketball_nba", "basketball_ncaab"}


def _get_weights(sport: str, is_prop: bool) -> dict[str, float]:
    """Return the appropriate weight set for a sport and market type.

    NBA props use 5-component weights with player projections.
    CBB uses KenPom game-level projections for mainlines.
    All other sports use 4-component weights (no projection data).
    """
    if is_prop and sport == "basketball_nba":
        return NBA_PROP_WEIGHTS
    if sport == "basketball_nba":
        return NBA_WEIGHTS
    if sport == "basketball_ncaab":
        return CBB_WEIGHTS
    return DEFAULT_WEIGHTS


# ---------------------------------------------------------------------------
# Linear interpolation helper
# ---------------------------------------------------------------------------

def _lerp(value: float, tiers: list[tuple[float, float, int, int]]) -> int:
    """Linearly interpolate a score from tier breakpoints.

    Each tier is (low, high, score_low, score_high).
    Value below first tier returns 0. Value above last returns score_high of last.
    """
    for low, high, s_low, s_high in tiers:
        if value < low:
            return 0
        if value <= high:
            if high == low:
                return s_low
            frac = (value - low) / (high - low)
            return round(s_low + frac * (s_high - s_low))
    # Above all tiers — return max.
    return tiers[-1][3] if tiers else 0


class RTMSignal:
    """The RTM Signal confluence model."""

    def __init__(self, db_client=None, simulator: PropSimulator | None = None):
        self._db = db_client
        self._sim = simulator or PropSimulator(num_simulations=10_000)
        # Caches for steam alerts and line movements.
        self._steam_cache: dict[str, list[dict]] | None = None
        self._movements_cache: dict[str, list[dict]] | None = None
        # EV consensus: (game_id, market_type, normalized_side) -> set of sportsbooks
        self._consensus_map: dict[tuple[str, str, str], set[str]] | None = None
        # Intelligence caches (populated by load_cache).
        self._stale_cache: dict[str, list[dict]] | None = None
        self._reaction_cache: dict[str, list[dict]] | None = None
        # Market timing analysis cache — computed once per scan, not per opp.
        self._timing_analysis_cache: dict[str, dict] | None = None

    # ------------------------------------------------------------------
    # Individual scoring components
    # ------------------------------------------------------------------

    def ev_score(self, ev_percentage: float) -> int:
        """Score based on +EV from devigged sharp books.

        Returns 0-100 with linear interpolation within tiers:
          1-2%  → 15-30
          2-3%  → 30-50
          3-5%  → 50-70
          5-8%  → 70-85
          8-12% → 85-100
          12%+  → 100
        """
        if ev_percentage < 1.0:
            return 0
        return _lerp(ev_percentage, [
            (1.0, 2.0, 15, 30),
            (2.0, 3.0, 30, 50),
            (3.0, 5.0, 50, 70),
            (5.0, 8.0, 70, 85),
            (8.0, 12.0, 85, 100),
            (12.0, 100.0, 100, 100),
        ])

    def steam_score(
        self,
        game_id: str,
        side: str,
        market_type: str,
    ) -> int:
        """Score based on steam alert confirmation.

        Checks if a steam alert exists that confirms this bet direction.
        3 books → 40, 4 books → 70, 5+ books AND magnitude ≥ 3 → 100.
        """
        steam_alerts = self._get_steam_alerts(game_id)
        if not steam_alerts:
            return 0

        best_score = 0
        for alert in steam_alerts:
            alert_side = alert.get("side", "")
            alert_market = alert.get("market_type", "")
            alert_direction = alert.get("direction", "")

            # Check if steam confirms our side.
            if alert_market != market_type:
                continue

            # "shortened" means odds shortened (sharp money ON this side).
            if alert_direction != "shortened":
                continue

            # Match side — flexible substring matching.
            if not _sides_match(side, alert_side):
                continue

            books_moved = alert.get("books_moved", [])
            if isinstance(books_moved, str):
                books_moved = books_moved.split(",")
            num_books = len(books_moved) if isinstance(books_moved, list) else 1
            magnitude = float(alert.get("magnitude", 0))

            if num_books >= 5 and magnitude >= 3:
                best_score = max(best_score, 100)
            elif num_books >= 4:
                best_score = max(best_score, 70)
            elif num_books >= 3:
                best_score = max(best_score, 40)
            else:
                best_score = max(best_score, 20)

        return best_score

    def projection_score(
        self,
        player_projection: dict | None,
        line: float,
        side: str,
        prop_type: str,
    ) -> int:
        """Score based on our proprietary projection vs sportsbook line.

        Only applicable to player props with projection support (NBA).
        """
        if player_projection is None:
            return 0

        projections = player_projection.get("projections", {})
        proj_key = _prop_type_to_key(prop_type)

        if proj_key not in projections:
            return 0

        proj = projections[proj_key]
        mean = proj["mean"]
        std_dev = proj["std_dev"]

        # Simulate to get fair probability.
        if proj_key == "pts_reb_ast" and all(
            k in projections for k in ("points", "rebounds", "assists")
        ):
            dist = self._sim.simulate_pra(
                projections["points"]["mean"], projections["points"]["std_dev"],
                projections["rebounds"]["mean"], projections["rebounds"]["std_dev"],
                projections["assists"]["mean"], projections["assists"]["std_dev"],
            )
        else:
            dist = self._sim.simulate_player_prop(mean, std_dev, proj_key)

        fair = self._sim.calculate_prop_fair_odds(dist, line)

        our_prob = fair["over_prob"] if side.lower() == "over" else fair["under_prob"]

        # Score based on edge between our prob and 50% (vig-free fair line).
        edge = (our_prob - 0.5) * 100 * 2  # Scale to 0-100ish

        if edge >= 16:
            return 90
        elif edge >= 10:
            return 70
        elif edge >= 6:
            return 50
        elif edge >= 2:
            return 30
        elif edge >= 0:
            return 10
        return 0

    # Counter for debug logging (first N CBB opportunities).
    _cbb_debug_count = 0
    _CBB_DEBUG_LIMIT = 5

    def game_projection_score(
        self,
        game_proj: dict,
        side: str,
        market_type: str,
        game_info: dict,
        point: float | None = None,
    ) -> int:
        """Score based on KenPom game-level projection (CBB).

        For h2h: compares KenPom win probability with the bet side.
        For spreads: compares KenPom predicted margin with the line.
        For totals: compares KenPom predicted total with the line.

        Returns 0-100 score.
        """
        if not game_proj:
            return 0

        home_wp = game_proj.get("home_wp", 0.5)
        home_pred = game_proj.get("home_pred", 0)
        away_pred = game_proj.get("away_pred", 0)
        home_team = game_info.get("home_team", "")
        away_team = game_info.get("away_team", "")

        score = 0

        if market_type == "h2h":
            # Determine which side we're betting.
            side_norm = side.strip().lower()
            home_norm = home_team.strip().lower()
            away_norm = away_team.strip().lower()

            if side_norm == home_norm or home_norm in side_norm:
                our_wp = home_wp
            elif side_norm == away_norm or away_norm in side_norm:
                our_wp = 1.0 - home_wp
            else:
                self._debug_cbb(
                    market_type, side, home_team, away_team,
                    home_pred, away_pred, home_wp, point, 0,
                    reason=f"side '{side_norm}' matched neither home '{home_norm}' nor away '{away_norm}'",
                )
                return 0

            # Score: how much KenPom agrees with this side.
            # 50% = neutral, 75% = strong agreement.
            edge = (our_wp - 0.5) * 200  # Scale: 50%=0, 75%=50, 100%=100
            score = int(min(100, max(0, edge)))
            self._debug_cbb(
                market_type, side, home_team, away_team,
                home_pred, away_pred, home_wp, point, score,
                reason=f"our_wp={our_wp:.3f}, edge={edge:.1f}",
            )
            return score

        elif market_type == "spreads":
            # KenPom predicted margin (positive = home favored).
            kp_margin = home_pred - away_pred
            if point is None:
                self._debug_cbb(
                    market_type, side, home_team, away_team,
                    home_pred, away_pred, home_wp, point, 0,
                    reason="point is None",
                )
                return 0

            # The spread point is from the bet side's perspective.
            # If betting home at -5.5, we need home to win by >5.5.
            # KenPom margin of 8 vs line of -5.5 → 2.5 points of value.
            side_norm = side.strip().lower()
            home_norm = home_team.strip().lower()

            if home_norm in side_norm:
                # Betting home side: value = kp_margin - |point|
                value = kp_margin - abs(point)
            else:
                # Betting away side: KenPom margin < spread means cushion.
                # E.g., KenPom home by 3, away gets +5.5 → 2.5 pts value.
                value = abs(point) - kp_margin

            # Scale: 0 pts value=20, 3 pts=50, 6 pts=80, 10+=100
            if value <= 0:
                score = 0
            else:
                score = int(min(100, 20 + value * 10))

            self._debug_cbb(
                market_type, side, home_team, away_team,
                home_pred, away_pred, home_wp, point, score,
                reason=f"kp_margin={kp_margin:.1f}, spread={point}, value={value:.1f}",
            )
            return score

        elif market_type == "totals":
            kp_total = home_pred + away_pred
            if point is None:
                self._debug_cbb(
                    market_type, side, home_team, away_team,
                    home_pred, away_pred, home_wp, point, 0,
                    reason="point is None",
                )
                return 0

            side_lower = side.strip().lower()
            if "over" in side_lower:
                value = kp_total - point
            elif "under" in side_lower:
                value = point - kp_total
            else:
                self._debug_cbb(
                    market_type, side, home_team, away_team,
                    home_pred, away_pred, home_wp, point, 0,
                    reason=f"side '{side_lower}' has neither over nor under",
                )
                return 0

            if value <= 0:
                score = 0
            else:
                score = int(min(100, 20 + value * 10))

            self._debug_cbb(
                market_type, side, home_team, away_team,
                home_pred, away_pred, home_wp, point, score,
                reason=f"kp_total={kp_total:.1f}, line={point}, value={value:.1f}",
            )
            return score

        return 0

    def _debug_cbb(
        self,
        market_type: str,
        side: str,
        home_team: str,
        away_team: str,
        home_pred: float,
        away_pred: float,
        home_wp: float,
        point: float | None,
        score: int,
        reason: str = "",
    ) -> None:
        """Print debug info for the first N CBB projection scores."""
        if RTMSignal._cbb_debug_count >= RTMSignal._CBB_DEBUG_LIMIT:
            return
        RTMSignal._cbb_debug_count += 1
        print(
            f"  [KENPOM DEBUG {RTMSignal._cbb_debug_count}/{RTMSignal._CBB_DEBUG_LIMIT}] "
            f"{market_type} | side='{side}' | {away_team} @ {home_team} | "
            f"KP: {away_pred:.0f}-{home_pred:.0f} (home WP {home_wp:.1%}) | "
            f"point={point} | score={score} | {reason}"
        )

    def intelligence_score(
        self,
        game_id: str,
        sport: str,
        market_type: str,
        side: str,
        sportsbook: str,
        hours_until_start: float | None = None,
    ) -> tuple[int, dict]:
        """Score based on intelligence layers.

        Combines:
          - Stale line detection (+30 pts if this book has a stale line)
          - Book profiling (+15 pts if this book is historically slow)
          - Market timing (+10 pts if in optimal bet window)
          - Prop correlation (+15 pts if correlated props confirm)
          - Peak timing (+10 pts if edge is at peak in lifecycle)

        Uses pre-loaded caches from load_cache() to avoid per-opportunity
        DB queries (N+1 fix).

        Returns (score 0-100, context dict).
        """
        score = 0
        context: dict[str, Any] = {
            "is_stale_line": False,
            "stale_tip": "",
            "slow_book": False,
            "optimal_window": False,
            "timing_tip": "",
            "has_correlation": False,
            "correlation_tip": "",
        }

        if self._db is None:
            return score, context

        # 1. Stale line check — use cache if available.
        if self._stale_cache is not None:
            for sl in self._stale_cache.get(game_id, []):
                if (
                    sl.get("market_type") == market_type
                    and sl.get("stale_book") == sportsbook
                    and sl.get("status") == "active"
                ):
                    score += 30
                    context["is_stale_line"] = True
                    context["stale_tip"] = (
                        f"{sportsbook.replace('_', ' ')} hasn't caught up "
                        f"({sl.get('stale_type', 'stale')})"
                    )
                    break
        else:
            try:
                stale_lines = self._db._get(
                    "stale_line_alerts",
                    select="stale_book,edge_percentage,stale_type",
                    filters={
                        "game_id": f"eq.{game_id}",
                        "market_type": f"eq.{market_type}",
                        "stale_book": f"eq.{sportsbook}",
                        "status": "eq.active",
                    },
                    limit=1,
                )
                if stale_lines:
                    score += 30
                    context["is_stale_line"] = True
                    sl = stale_lines[0]
                    context["stale_tip"] = (
                        f"{sportsbook.replace('_', ' ')} hasn't caught up "
                        f"({sl.get('stale_type', 'stale')})"
                    )
            except Exception:
                pass

        # 2. Book profiling — use cache if available.
        if self._reaction_cache is not None:
            book_key = f"{sportsbook}:{sport}"
            reactions = self._reaction_cache.get(book_key, [])
            if reactions:
                times = [
                    r["reaction_seconds"]
                    for r in reactions
                    if r.get("reaction_seconds") is not None
                ]
                if times:
                    avg_time = sum(times) / len(times)
                    if avg_time > 180:
                        score += 15
                        context["slow_book"] = True
        else:
            try:
                reactions = self._db._get(
                    "book_reaction_times",
                    select="reaction_seconds",
                    filters={
                        "soft_book": f"eq.{sportsbook}",
                        "sport": f"eq.{sport}",
                    },
                    limit=20,
                )
                if reactions:
                    times = [
                        r["reaction_seconds"]
                        for r in reactions
                        if r.get("reaction_seconds") is not None
                    ]
                    if times:
                        avg_time = sum(times) / len(times)
                        if avg_time > 180:
                            score += 15
                            context["slow_book"] = True
            except Exception:
                pass

        # 3. Market timing: use pre-computed analysis from load_cache.
        if self._timing_analysis_cache is not None:
            analysis = self._timing_analysis_cache.get(sport, {})
            timing_ctx = self._eval_timing_context(
                analysis, sport, market_type, hours_until_start
            )
            bonus = timing_ctx.get("score_bonus", 0)
            if bonus > 0:
                score += bonus
                context["optimal_window"] = True
                context["timing_tip"] = timing_ctx.get("context", "")
        else:
            try:
                from intelligence.market_timing import MarketTimingEngine
                timing = MarketTimingEngine(self._db)
                timing_ctx = timing.get_timing_context_for_signal(
                    sport, market_type, hours_until_start
                )
                bonus = timing_ctx.get("score_bonus", 0)
                if bonus > 0:
                    score += bonus
                    context["optimal_window"] = True
                    context["timing_tip"] = timing_ctx.get("context", "")
            except Exception:
                pass

        # 4. Prop correlation: if this is a prop, check for confirming correlations.
        if market_type.startswith("player_"):
            try:
                from intelligence.correlation_engine import PropCorrelationEngine
                corr_engine = PropCorrelationEngine()
                m = re.match(r"^(.+?)\s+(over|under)", side, re.IGNORECASE)
                if m:
                    player = m.group(1).strip()
                    direction = m.group(2).lower()
                    corr = corr_engine.get_correlated_props(
                        player, market_type, direction
                    )
                    pos = corr.get("positively_correlated", [])
                    if any(c["strength"] in ("strong", "moderate") for c in pos):
                        score += 15
                        context["has_correlation"] = True
                        top_corr = pos[0] if pos else None
                        if top_corr:
                            context["correlation_tip"] = (
                                f"Correlated with {top_corr['stat']} "
                                f"(r={top_corr['correlation']})"
                            )
            except Exception:
                pass

        # 5. Peak timing: is the edge at peak in the line lifecycle?
        if hours_until_start is not None and 2 <= hours_until_start <= 8:
            score += 10  # Sweet spot for most sports

        # Cap at 100.
        return min(100, score), context

    def market_consensus_score(
        self,
        game_id: str,
        side: str,
        market_type: str,
    ) -> tuple[int, int]:
        """Score based on how many sportsbooks show +EV on the same side.

        Counts distinct sportsbooks from the current EV opportunities.
        More granular scaling to differentiate between book counts:
          1 book → 10, 2 → 20, 3 → 35, 4 → 45, 5 → 55, 6 → 65, 7+ → 75
        +15 bonus if a steam alert confirms this side.

        Returns (score, num_books) tuple.
        """
        num_books = 0
        if self._consensus_map is not None:
            key = (game_id, market_type, _dedup_side(side, market_type))
            books = self._consensus_map.get(key, set())
            num_books = len(books)

        _CONSENSUS_TIERS = {1: 10, 2: 20, 3: 35, 4: 45, 5: 55, 6: 65}
        if num_books >= 7:
            base = 75
        elif num_books >= 1:
            base = _CONSENSUS_TIERS.get(num_books, 10)
        else:
            base = 0

        # Bonus if steam confirms this side.
        steam = self._get_steam_alerts(game_id)
        has_steam_confirm = False
        for alert in steam:
            if alert.get("market_type") != market_type:
                continue
            if alert.get("direction") != "shortened":
                continue
            if _sides_match(side, alert.get("side", "")):
                has_steam_confirm = True
                break

        if has_steam_confirm:
            base = min(100, base + 15)

        return base, num_books

    # ------------------------------------------------------------------
    # Signal generation
    # ------------------------------------------------------------------

    def score_opportunity(
        self,
        opportunity: dict,
        player_projection: dict | None = None,
        game_projection: dict | None = None,
    ) -> dict | None:
        """Score a single betting opportunity through the confluence model.

        Args:
            opportunity: EV opportunity dict.
            player_projection: Player-level projection (NBA props).
            game_projection: Game-level projection from KenPom (CBB).

        Returns a signal dict if it meets the threshold, else None.
        """
        game_id = opportunity.get("game_id", "")
        market_type = opportunity.get("market_type", "")
        side = opportunity.get("side", "")
        ev_pct = float(opportunity.get("ev_percentage", 0))
        book_odds = opportunity.get("book_odds", -110)
        sportsbook = opportunity.get("sportsbook", "")

        # Determine sport.
        game_info = opportunity.get("games", {}) or {}
        sport = game_info.get("sport", opportunity.get("sport", ""))

        is_prop = market_type.startswith("player_")

        # Calculate individual scores.
        ev = self.ev_score(ev_pct)
        steam = self.steam_score(game_id, side, market_type)

        # Projection score.
        proj = 0
        proj_data = None

        # NBA player props: use player-level projections.
        if is_prop and player_projection and sport in _PROJECTION_SPORTS:
            m = re.search(r"(over|under)\s+([\d.]+)", side, re.IGNORECASE)
            if m:
                direction = m.group(1)
                line = float(m.group(2))
                proj = self.projection_score(
                    player_projection, line, direction, market_type
                )
                proj_data = {
                    "line": line,
                    "direction": direction,
                    "mean": player_projection.get("projections", {}).get(
                        _prop_type_to_key(market_type), {}
                    ).get("mean"),
                }

        # CBB game lines: use KenPom game-level projections.
        elif game_projection and sport == "basketball_ncaab" and not is_prop:
            # Parse the point from the side string for spreads/totals.
            point = None
            m_pt = re.search(r"[-+]?\d+\.?\d*$", side)
            if m_pt:
                try:
                    point = float(m_pt.group())
                except ValueError:
                    pass
            proj = self.game_projection_score(
                game_projection, side, market_type, game_info, point
            )
            if proj > 0:
                proj_data = {
                    "source": game_projection.get("source", "kenpom"),
                    "home_pred": game_projection.get("home_pred"),
                    "away_pred": game_projection.get("away_pred"),
                    "home_wp": game_projection.get("home_wp"),
                }

        consensus, consensus_books = self.market_consensus_score(
            game_id, side, market_type,
        )

        # Intelligence score (stale lines, book profiling, timing, correlations).
        intel, intel_context = self.intelligence_score(
            game_id=game_id,
            sport=sport,
            market_type=market_type,
            side=side,
            sportsbook=sportsbook,
            hours_until_start=opportunity.get("hours_until_start"),
        )

        # Select sport-adaptive weights.
        weights = _get_weights(sport, is_prop)

        # Calculate signal strength.
        signal_strength = (
            ev * weights["ev"]
            + steam * weights["steam"]
            + proj * weights["projection"]
            + consensus * weights["consensus"]
            + intel * weights["intelligence"]
        )
        signal_strength = round(signal_strength, 1)

        # Determine star rating.
        if signal_strength >= TIER_STRONG:
            stars = 5
        elif signal_strength >= TIER_SIGNAL:
            stars = 4
        elif signal_strength >= TIER_LEAN:
            stars = 3
        else:
            return None  # Below threshold.

        home_team = game_info.get("home_team", "")
        away_team = game_info.get("away_team", "")

        # Parse player name from prop side.
        player_name = None
        prop_line = None
        if is_prop:
            m = re.match(r"^(.+?)\s+(over|under)\s+([\d.]+)$", side, re.IGNORECASE)
            if m:
                player_name = m.group(1).strip()
                prop_line = float(m.group(3))

        true_prob = float(opportunity.get("true_prob", 0.5))

        # Compute full Kelly fraction for this signal.
        kelly_frac = 0.0
        if true_prob > 0 and true_prob < 1 and book_odds != 0:
            decimal_odds = american_to_decimal(book_odds)
            if decimal_odds > 1:
                edge = true_prob * decimal_odds - 1
                kelly_frac = max(edge / (decimal_odds - 1), 0.0)

        # Compute fair value odds from true probability.
        fair_odds = None
        if true_prob > 0 and true_prob < 1:
            if true_prob >= 0.5:
                fair_odds = round(-true_prob / (1 - true_prob) * 100)
            else:
                fair_odds = round((1 - true_prob) / true_prob * 100)

        return {
            "game_id": game_id,
            "sport": sport,
            "market_type": market_type,
            "side": side,
            "player_name": player_name,
            "prop_line": prop_line,
            "sportsbook": sportsbook,
            "book_odds": book_odds,
            "signal_strength": signal_strength,
            "star_rating": stars,
            "ev_score": ev,
            "steam_score": steam,
            "projection_score": proj,
            "consensus_score": consensus,
            "consensus_books": consensus_books,
            "intelligence_score": intel,
            "intelligence_context": intel_context,
            "fair_odds": fair_odds,
            "true_prob": true_prob,
            "edge_percentage": ev_pct,
            "kelly_fraction": round(kelly_frac, 6),
            "bet_amount": SIGNAL_BET_AMOUNT,
            "home_team": home_team,
            "away_team": away_team,
            "game": f"{away_team} @ {home_team}" if home_team else "",
            "projection_data": proj_data,
            "commence_time": opportunity.get("commence_time"),
            "hours_until_start": opportunity.get("hours_until_start"),
            "devig_source": opportunity.get("devig_source", ""),
            "devig_confidence": opportunity.get("devig_confidence", ""),
            "devig_method": opportunity.get("devig_method", "multiplicative"),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

    def generate_signals(
        self,
        opportunities: list[dict],
        player_projections: dict[int, dict] | None = None,
        game_projections: dict[str, dict] | None = None,
    ) -> list[dict]:
        """Score all opportunities and return those meeting signal threshold.

        Builds a consensus map from all opportunities first, then scores each.
        Deduplicates by (game_id, market_type, side) keeping highest strength.

        Args:
            opportunities: List of EV opportunity dicts.
            player_projections: Dict of player_id -> projection dict (NBA props).
            game_projections: Dict of game_id -> KenPom projection dict (CBB).

        Returns list of signal dicts sorted by strength descending.
        """
        # Build consensus map: count distinct sportsbooks per (game, market, team/direction).
        # Uses _dedup_side so "Team -3.5" and "Team -5.5" count toward the same consensus.
        self._consensus_map = {}
        for opp in opportunities:
            gid = opp.get("game_id", "")
            mkt = opp.get("market_type", "")
            side_raw = opp.get("side", "")
            book = opp.get("sportsbook", "")
            key = (gid, mkt, _dedup_side(side_raw, mkt))
            self._consensus_map.setdefault(key, set()).add(book)

        projections = player_projections or {}
        game_projs = game_projections or {}
        all_signals: list[dict] = []

        # Reset CBB debug counter for this scan cycle.
        RTMSignal._cbb_debug_count = 0

        # Diagnostic counters for CBB projection flow.
        _cbb_total = 0
        _cbb_matched = 0
        _cbb_proj_nonzero = 0

        for opp in opportunities:
            # Skip blocked sportsbooks.
            if opp.get("sportsbook", "") in _BLOCKED_SIGNAL_BOOKS:
                continue

            # Filter: only fire signals in the allowed odds window.
            odds_val = opp.get("book_odds", 0)
            try:
                odds_val = int(odds_val)
            except (ValueError, TypeError):
                continue
            if odds_val < SIGNAL_MIN_ODDS or odds_val > SIGNAL_MAX_ODDS:
                continue

            # Find matching projection for props.
            proj = None
            if opp.get("market_type", "").startswith("player_"):
                m = re.match(
                    r"^(.+?)\s+(over|under)\s+",
                    opp.get("side", ""),
                    re.IGNORECASE,
                )
                if m:
                    player_name = m.group(1).strip().lower()
                    for pid, p in projections.items():
                        if p.get("player_name", "").lower() == player_name:
                            proj = p
                            break

            # Look up game-level projection for CBB.
            game_proj = game_projs.get(opp.get("game_id", ""))

            # Track CBB projection matching for diagnostics.
            opp_sport = (opp.get("games") or {}).get("sport", opp.get("sport", ""))
            if opp_sport == "basketball_ncaab" and not opp.get("market_type", "").startswith("player_"):
                _cbb_total += 1
                if game_proj is not None:
                    _cbb_matched += 1

            signal = self.score_opportunity(opp, proj, game_proj)
            if signal:
                if signal.get("sport") == "basketball_ncaab" and signal.get("projection_score", 0) > 0:
                    _cbb_proj_nonzero += 1
                all_signals.append(signal)

        # Print CBB projection diagnostics.
        if game_projs:
            print(
                f"  [KENPOM] Signal engine: {len(game_projs)} projections received | "
                f"{_cbb_matched}/{_cbb_total} CBB opps matched a projection | "
                f"{_cbb_proj_nonzero} signals with Proj>0"
            )
            if _cbb_total > 0 and _cbb_matched == 0:
                # Debug: show sample game_ids to diagnose key mismatch.
                sample_proj_keys = list(game_projs.keys())[:3]
                sample_opp_ids = [
                    o.get("game_id", "")
                    for o in opportunities
                    if (o.get("games") or {}).get("sport") == "basketball_ncaab"
                ][:3]
                print(
                    f"  [KENPOM] KEY MISMATCH — projection keys: {sample_proj_keys} | "
                    f"opp game_ids: {sample_opp_ids}"
                )

        # Deduplicate: keep the strongest signal per (game_id, market_type, team/direction).
        # Uses _dedup_side to strip point values so "Team -3.5" and "Team -5.5" merge.
        # Collect all books for each play to populate other_books.
        groups: dict[tuple[str, str, str], list[dict]] = {}
        for sig in all_signals:
            key = (sig["game_id"], sig["market_type"], _dedup_side(sig["side"], sig["market_type"]))
            groups.setdefault(key, []).append(sig)

        signals = []
        for key, group in groups.items():
            # Sort by signal_strength desc, then EV desc as tiebreaker.
            group.sort(
                key=lambda s: (s["signal_strength"], s.get("edge_percentage", 0)),
                reverse=True,
            )
            best = group[0]
            # Attach other books/lines (excluding featured book and blocked books).
            # Includes alternate point values from other books.
            other_books = []
            seen_books: set[str] = {best["sportsbook"]}
            for alt in group[1:]:
                if alt["sportsbook"] in _BLOCKED_SIGNAL_BOOKS:
                    continue
                if alt["sportsbook"] in seen_books:
                    continue
                seen_books.add(alt["sportsbook"])
                other_books.append({
                    "sportsbook": alt["sportsbook"],
                    "book_odds": alt["book_odds"],
                    "ev_pct": alt["edge_percentage"],
                    "side": alt["side"],
                })
            best["other_books"] = other_books
            signals.append(best)

        # Sort by signal strength descending.
        signals.sort(key=lambda s: s["signal_strength"], reverse=True)
        return signals

    # ------------------------------------------------------------------
    # Data retrieval helpers
    # ------------------------------------------------------------------

    def _get_steam_alerts(self, game_id: str) -> list[dict]:
        """Get steam alerts for a game from DB or cache."""
        if self._steam_cache is not None:
            return self._steam_cache.get(game_id, [])

        if self._db is None:
            return []

        try:
            rows = self._db._get(
                "steam_alerts",
                filters={"game_id": f"eq.{game_id}"},
                order="detected_at.desc",
            )
            return rows
        except Exception:
            return []

    def _get_line_movements(self, game_id: str) -> list[dict]:
        """Get line movements for a game from DB or cache."""
        if self._movements_cache is not None:
            return self._movements_cache.get(game_id, [])

        if self._db is None:
            return []

        try:
            rows = self._db._get(
                "line_movements",
                filters={"game_id": f"eq.{game_id}"},
                order="timestamp.desc",
            )
            return rows
        except Exception:
            return []

    def load_cache(self, game_ids: list[str]) -> None:
        """Bulk-load steam, movement, stale-line, and reaction data.

        Uses IN filters to fetch all games in a handful of queries instead
        of 2+ queries per game/opportunity (N+1 fix).
        """
        if self._db is None:
            self._steam_cache = {}
            self._movements_cache = {}
            self._stale_cache = {}
            self._reaction_cache = {}
            return

        self._steam_cache = {gid: [] for gid in game_ids}
        self._movements_cache = {gid: [] for gid in game_ids}
        self._stale_cache = {gid: [] for gid in game_ids}
        self._reaction_cache = {}

        if not game_ids:
            return

        # Batch-fetch steam alerts for all games at once.
        for i in range(0, len(game_ids), 200):
            chunk = game_ids[i : i + 200]
            id_list = ",".join(chunk)
            try:
                rows = self._db._get(
                    "steam_alerts",
                    select="game_id,market_type,side,book_count,direction,created_at",
                    filters={"game_id": f"in.({id_list})"},
                )
                for r in rows:
                    gid = r.get("game_id", "")
                    self._steam_cache.setdefault(gid, []).append(r)
            except Exception:
                pass

        # Batch-fetch line movements for all games at once.
        for i in range(0, len(game_ids), 200):
            chunk = game_ids[i : i + 200]
            id_list = ",".join(chunk)
            try:
                rows = self._db._get(
                    "line_movements",
                    select="game_id,bookmaker,market_type,side,odds,previous_odds,odds_change,timestamp",
                    filters={"game_id": f"in.({id_list})"},
                )
                for r in rows:
                    gid = r.get("game_id", "")
                    self._movements_cache.setdefault(gid, []).append(r)
            except Exception:
                pass

        # Batch-fetch stale line alerts for all games at once.
        for i in range(0, len(game_ids), 200):
            chunk = game_ids[i : i + 200]
            id_list = ",".join(chunk)
            try:
                rows = self._db._get(
                    "stale_line_alerts",
                    select="game_id,market_type,stale_book,status,stale_type,edge_percentage",
                    filters={
                        "game_id": f"in.({id_list})",
                        "status": "eq.active",
                    },
                )
                for r in rows:
                    gid = r.get("game_id", "")
                    self._stale_cache.setdefault(gid, []).append(r)
            except Exception:
                pass

        # Batch-fetch ALL book reaction times in one query (not per-game).
        # Keyed by "soft_book:sport" for quick lookup.
        try:
            rows = self._db._get(
                "book_reaction_times",
                select="soft_book,sport,reaction_seconds",
            )
            for r in rows:
                key = f"{r.get('soft_book', '')}:{r.get('sport', '')}"
                self._reaction_cache.setdefault(key, []).append(r)
        except Exception:
            pass

        # Pre-compute market timing analysis ONCE per scan (not per opp).
        # Keyed by sport so intelligence_score can look up without DB calls.
        self._timing_analysis_cache = {}
        try:
            from intelligence.market_timing import MarketTimingEngine
            timing = MarketTimingEngine(self._db)
            # Collect unique sports from game_ids we're scoring.
            # Pass None to get all sports at once.
            analysis = timing.analyze_optimal_windows(sport=None)
            # Index windows by sport for O(1) lookup.
            for w in analysis.get("windows", []):
                sport_key = w.get("sport", "")
                self._timing_analysis_cache.setdefault(sport_key, {
                    "windows": [],
                    "hours_before_game": analysis.get("hours_before_game", {}),
                })
                self._timing_analysis_cache[sport_key]["windows"].append(w)
        except Exception:
            pass

    @staticmethod
    def _eval_timing_context(
        analysis: dict,
        sport: str,
        market_type: str,
        hours_until_start: float | None,
    ) -> dict:
        """Evaluate timing context from pre-computed analysis (no DB).

        Mirrors MarketTimingEngine.get_timing_context_for_signal logic.
        """
        windows = analysis.get("windows", [])
        matching = None
        for w in windows:
            if w.get("sport") == sport and w.get("market_type") == market_type:
                matching = w
                break

        context = ""
        score_bonus = 0

        if matching and matching.get("best_hour_utc") is not None:
            current_hour = datetime.now(timezone.utc).hour
            best_hour = matching["best_hour_utc"]
            diff = abs(current_hour - best_hour)
            if diff <= 2 or diff >= 22:
                context = "Optimal bet window — peak edge time for this market"
                score_bonus = 10

        if hours_until_start is not None:
            hours_before = analysis.get("hours_before_game", {}).get(sport, {})
            best_hrs = hours_before.get("best_hours_before_game")
            if best_hrs is not None:
                diff = abs((hours_until_start or 0) - best_hrs)
                if diff <= 2:
                    if not context:
                        context = f"Near peak timing — {hours_until_start:.0f}h before game"
                    score_bonus = max(score_bonus, 8)

        return {
            "context": context,
            "score_bonus": score_bonus,
            "hours_until_start": hours_until_start,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize_side(side: str) -> str:
    """Normalize a side string for dedup/consensus grouping.

    Strips sportsbook-specific variations so the same logical bet
    (e.g. "Team A -3.5" from different books) groups together.
    """
    return side.strip().lower()


def _dedup_side(side: str, market_type: str) -> str:
    """Extract team name or direction for deduplication, stripping point values.

    Different books may offer different lines for the same team (e.g. -3.5 vs -5.5).
    We want ONE signal per team per game per market, not one per line.

    spreads:  "Miami (OH) RedHawks -5.5" → "miami (oh) redhawks"
    totals:   "Over 145.5"               → "over"
    h2h:      "Miami (OH) RedHawks"       → "miami (oh) redhawks"
    props:    "Player Name Over 25.5"     → "player name over"
    """
    s = side.strip().lower()
    if market_type == "totals":
        # For totals, just keep the over/under direction.
        if "over" in s:
            return "over"
        if "under" in s:
            return "under"
        return s
    # Strip trailing point value: " -5.5", " +3.5", " 145.5", etc.
    return re.sub(r'\s*[-+]?\d+\.?\d*$', '', s).strip()


def _sides_match(bet_side: str, alert_side: str) -> bool:
    """Check if a bet side matches a steam alert side.

    Uses flexible substring matching in both directions.
    """
    a = bet_side.strip().lower()
    b = alert_side.strip().lower()
    return a in b or b in a


# ---------------------------------------------------------------------------
# Storage & formatting
# ---------------------------------------------------------------------------

def store_signals(db_client, signals: list[dict]) -> int:
    """Store signals in the rtm_signals Supabase table.

    Returns number of signals stored.
    """
    if not signals or db_client is None:
        return 0

    import json as _json

    rows = []
    for s in signals:
        # Only include columns that exist in the rtm_signals table.
        # Verified against 005_rtm_signal.sql + 006_intelligence_layers.sql
        # + 007_signal_bet_amount.sql.
        # Omitted: away_team, commence_time, consensus_books, home_team,
        #          other_books, true_prob.
        intel_ctx = s.get("intelligence_context")
        rows.append({
            "game_id": s["game_id"],
            "sport": s["sport"],
            "market_type": s["market_type"],
            "side": s["side"],
            "player_name": s.get("player_name"),
            "prop_line": s.get("prop_line"),
            "sportsbook": s["sportsbook"],
            "book_odds": s["book_odds"],
            "signal_strength": s["signal_strength"],
            "star_rating": s["star_rating"],
            "ev_score": s["ev_score"],
            "steam_score": s["steam_score"],
            "projection_score": s.get("projection_score", 0),
            "consensus_score": s["consensus_score"],
            "intelligence_score": s.get("intelligence_score", 0),
            "intelligence_context": _json.dumps(intel_ctx) if isinstance(intel_ctx, dict) else intel_ctx,
            "fair_odds": s.get("fair_odds"),
            "edge_percentage": s["edge_percentage"],
            "kelly_size": s.get("kelly_fraction"),
            "bet_amount": s.get("bet_amount", SIGNAL_BET_AMOUNT),
            "status": "active",
        })

    if rows:
        print(f"  [DEBUG] rtm_signals columns: {sorted(rows[0].keys())}")

    try:
        db_client._post_many("rtm_signals", rows)
        return len(rows)
    except Exception as e:
        print(f"Warning: Failed to store signals: {e}")
        return 0


def format_signal_for_console(signal: dict) -> str:
    """Format a signal for console output."""
    stars = "\u2b50" * signal["star_rating"]
    tier = "STRONG SIGNAL" if signal["star_rating"] == 5 else (
        "SIGNAL" if signal["star_rating"] == 4 else "LEAN"
    )
    h = signal.get("hours_until_start")
    if h is not None and h > 24:
        time_tag = f" | EARLY ({h:.0f}h out)"
    elif h is not None and h > 0:
        time_tag = f" | {h:.0f}h out"
    elif h is not None:
        time_tag = " | LIVE"
    else:
        time_tag = ""
    intel = signal.get("intelligence_score", 0)
    intel_ctx = signal.get("intelligence_context", {})
    intel_tags = []
    if intel_ctx.get("is_stale_line"):
        intel_tags.append("\U0001f3af STALE")
    if intel_ctx.get("optimal_window"):
        intel_tags.append("\u23f0 WINDOW")
    if intel_ctx.get("has_correlation"):
        intel_tags.append("\U0001f517 CORR")
    intel_str = " ".join(intel_tags) if intel_tags else ""

    return (
        f"\u26a1 RTM {tier} {stars} | "
        f"{signal['side']} at {signal['sportsbook']} {signal['book_odds']:+d} | "
        f"Strength: {signal['signal_strength']:.0f} | "
        f"EV:{signal['ev_score']} Steam:{signal['steam_score']} "
        f"Proj:{signal['projection_score']} Cons:{signal['consensus_score']} "
        f"Intel:{intel}"
        f"{time_tag}"
        f"{' | ' + intel_str if intel_str else ''}"
    )
