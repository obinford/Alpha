"""RTM Signal — confluence model for high-confidence betting signals.

Combines four independent systems:
  1. +EV from devigged sharp books (top-down)
  2. Steam detection / line movement confirmation
  3. In-house player projections + simulation (bottom-up)
  4. Market consensus / outlier detection

When 2+ systems agree → interesting. 3+ → RTM Signal. All 4 → max confidence.

Signal tiers:
  75+ → STRONG SIGNAL (5 stars)
  60+ → SIGNAL (4 stars)
  45+ → LEAN (3 stars)
  <45 → no signal
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from projections.simulator import PropSimulator, _prop_type_to_key
from projections.math_utils import american_to_decimal, american_to_implied_prob

# Configurable weights (can be tuned via shared/config.py later).
# Game line weights.
GAME_LINE_WEIGHTS = {
    "ev": 0.40,
    "steam": 0.30,
    "projection": 0.00,  # No projections for game lines
    "consensus": 0.30,
}

# Player prop weights.
PROP_WEIGHTS = {
    "ev": 0.25,
    "steam": 0.20,
    "projection": 0.35,
    "consensus": 0.20,
}

# Signal tier thresholds.
TIER_STRONG = 75
TIER_SIGNAL = 60
TIER_LEAN = 45

# Star ratings.
STAR_RATINGS = {5: TIER_STRONG, 4: TIER_SIGNAL, 3: TIER_LEAN}


class RTMSignal:
    """The RTM Signal confluence model."""

    def __init__(self, db_client=None, simulator: PropSimulator | None = None):
        self._db = db_client
        self._sim = simulator or PropSimulator(num_simulations=10_000)
        # Cache for steam alerts and line movements.
        self._steam_cache: dict[str, list[dict]] | None = None
        self._movements_cache: dict[str, list[dict]] | None = None

    # ------------------------------------------------------------------
    # Individual scoring components
    # ------------------------------------------------------------------

    def ev_score(self, ev_percentage: float) -> int:
        """Score based on +EV from devigged sharp books.

        Returns 0-100 score.
        """
        if ev_percentage >= 12:
            return 100
        elif ev_percentage >= 8:
            return 80
        elif ev_percentage >= 5:
            return 60
        elif ev_percentage >= 3:
            return 40
        elif ev_percentage >= 1:
            return 20
        return 0

    def steam_score(
        self,
        game_id: str,
        side: str,
        market_type: str,
    ) -> int:
        """Score based on steam alert confirmation.

        Checks if a steam alert exists that confirms this bet direction.
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

            # Match side.
            if side.lower() not in alert_side.lower() and alert_side.lower() not in side.lower():
                continue

            books_moved = alert.get("books_moved", [])
            if isinstance(books_moved, str):
                books_moved = books_moved.split(",")
            num_books = len(books_moved) if isinstance(books_moved, list) else 1
            magnitude = int(alert.get("magnitude", 0))

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

        Only applicable to player props.
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

    def market_consensus_score(
        self,
        game_id: str,
        side: str,
        market_type: str,
    ) -> int:
        """Score based on how many books agree on this side having value.

        Checks line_movements: if multiple books moved in the same direction,
        it's a market consensus.
        """
        movements = self._get_line_movements(game_id)
        if not movements:
            return 30  # Default moderate score when no data available.

        # Count books that moved odds shorter on this side (confirming value).
        confirming_books = set()
        for mv in movements:
            mv_market = mv.get("market_type", "")
            mv_side = mv.get("side", "")
            change = float(mv.get("odds_change", 0))

            if mv_market != market_type:
                continue

            # Check if this movement confirms our side.
            side_match = (
                side.lower() in mv_side.lower()
                or mv_side.lower() in side.lower()
            )
            if not side_match:
                continue

            # Odds shortening (negative change for favorites = shorter).
            if change < 0:
                confirming_books.add(mv.get("bookmaker", ""))

        num_confirming = len(confirming_books)
        if num_confirming >= 4:
            return 80
        elif num_confirming >= 3:
            return 60
        elif num_confirming >= 2:
            return 50
        elif num_confirming >= 1:
            return 30
        return 20

    # ------------------------------------------------------------------
    # Signal generation
    # ------------------------------------------------------------------

    def score_opportunity(
        self,
        opportunity: dict,
        player_projection: dict | None = None,
    ) -> dict | None:
        """Score a single betting opportunity through the confluence model.

        Returns a signal dict if it meets the threshold, else None.
        """
        game_id = opportunity.get("game_id", "")
        market_type = opportunity.get("market_type", "")
        side = opportunity.get("side", "")
        ev_pct = float(opportunity.get("ev_percentage", 0))
        book_odds = opportunity.get("book_odds", -110)
        sportsbook = opportunity.get("sportsbook", "")

        # Calculate individual scores.
        ev = self.ev_score(ev_pct)
        steam = self.steam_score(game_id, side, market_type)

        is_prop = market_type.startswith("player_")

        # Projection score (props only).
        proj = 0
        proj_data = None
        if is_prop and player_projection:
            # Parse line from side string (e.g., "LeBron James Over 28.5").
            import re
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

        consensus = self.market_consensus_score(game_id, side, market_type)

        # Select weights.
        weights = PROP_WEIGHTS if is_prop else GAME_LINE_WEIGHTS

        # Calculate signal strength.
        signal_strength = (
            ev * weights["ev"]
            + steam * weights["steam"]
            + proj * weights["projection"]
            + consensus * weights["consensus"]
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

        # Parse game info.
        game_info = opportunity.get("games", {}) or {}
        sport = game_info.get("sport", opportunity.get("sport", ""))
        home_team = game_info.get("home_team", "")
        away_team = game_info.get("away_team", "")

        # Parse player name from prop side.
        player_name = None
        prop_line = None
        if is_prop:
            import re
            m = re.match(r"^(.+?)\s+(over|under)\s+([\d.]+)$", side, re.IGNORECASE)
            if m:
                player_name = m.group(1).strip()
                prop_line = float(m.group(3))

        # Kelly sizing.
        true_prob = float(opportunity.get("true_prob", 0.5))
        decimal_odds = american_to_decimal(book_odds)
        b = decimal_odds - 1
        q = 1 - true_prob
        kelly = max(0, (true_prob * b - q) / b) if b > 0 else 0

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
            "fair_odds": None,  # Set if projection available
            "edge_percentage": ev_pct,
            "kelly_size": round(kelly * 100, 2),
            "home_team": home_team,
            "away_team": away_team,
            "game": f"{away_team} @ {home_team}" if home_team else "",
            "projection_data": proj_data,
            "commence_time": opportunity.get("commence_time"),
            "hours_until_start": opportunity.get("hours_until_start"),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

    def generate_signals(
        self,
        opportunities: list[dict],
        player_projections: dict[int, dict] | None = None,
    ) -> list[dict]:
        """Score all opportunities and return those meeting signal threshold.

        Args:
            opportunities: List of EV opportunity dicts.
            player_projections: Dict of player_id -> projection dict from
                ProjectionEngine.

        Returns list of signal dicts sorted by strength descending.
        """
        signals = []
        projections = player_projections or {}

        for opp in opportunities:
            # Find matching projection for props.
            proj = None
            if opp.get("market_type", "").startswith("player_"):
                # Try to match by parsing player name.
                import re
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

            signal = self.score_opportunity(opp, proj)
            if signal:
                signals.append(signal)

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
                "steam_moves",
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
        """Bulk-load steam and movement data for multiple games."""
        if self._db is None:
            self._steam_cache = {}
            self._movements_cache = {}
            return

        self._steam_cache = {}
        self._movements_cache = {}

        for gid in game_ids:
            try:
                steam = self._db._get(
                    "steam_moves",
                    filters={"game_id": f"eq.{gid}"},
                )
                self._steam_cache[gid] = steam
            except Exception:
                self._steam_cache[gid] = []

            try:
                movements = self._db._get(
                    "line_movements",
                    filters={"game_id": f"eq.{gid}"},
                )
                self._movements_cache[gid] = movements
            except Exception:
                self._movements_cache[gid] = []


def store_signals(db_client, signals: list[dict]) -> int:
    """Store signals in the rtm_signals Supabase table.

    Returns number of signals stored.
    """
    if not signals or db_client is None:
        return 0

    rows = []
    for s in signals:
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
            "fair_odds": s.get("fair_odds"),
            "edge_percentage": s["edge_percentage"],
            "kelly_size": s.get("kelly_size"),
            "status": "active",
        })

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
    return (
        f"\u26a1 RTM {tier} {stars} | "
        f"{signal['side']} at {signal['sportsbook']} {signal['book_odds']:+d} | "
        f"Strength: {signal['signal_strength']:.0f} | "
        f"EV:{signal['ev_score']} Steam:{signal['steam_score']} "
        f"Proj:{signal['projection_score']} Cons:{signal['consensus_score']}"
        f"{time_tag}"
    )
