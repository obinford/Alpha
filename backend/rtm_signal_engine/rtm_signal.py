"""RTM Signal — confluence model for high-confidence betting signals.

Combines up to four independent systems:
  1. +EV from devigged sharp books (top-down)
  2. Steam detection / line movement confirmation
  3. In-house player projections + simulation (bottom-up, NBA only)
  4. Market consensus — how many books show +EV on the same side

Sport-adaptive weights:
  NBA (4 components): ev=0.30, steam=0.25, projection=0.25, consensus=0.20
  Other sports (3 components): ev=0.45, steam=0.30, consensus=0.25

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

# NBA uses all 4 components including projections.
NBA_WEIGHTS = {
    "ev": 0.30,
    "steam": 0.25,
    "projection": 0.25,
    "consensus": 0.20,
}

# All other sports use 3 components (no projection data available).
DEFAULT_WEIGHTS = {
    "ev": 0.45,
    "steam": 0.30,
    "projection": 0.00,
    "consensus": 0.25,
}

# NBA prop weights (projection is more important for props).
NBA_PROP_WEIGHTS = {
    "ev": 0.25,
    "steam": 0.20,
    "projection": 0.35,
    "consensus": 0.20,
}

# Signal tier thresholds.
TIER_STRONG = 70
TIER_SIGNAL = 55
TIER_LEAN = 40

# Star ratings.
STAR_RATINGS = {5: TIER_STRONG, 4: TIER_SIGNAL, 3: TIER_LEAN}

# Sports that have projection support.
_PROJECTION_SPORTS = {"basketball_nba"}


def _get_weights(sport: str, is_prop: bool) -> dict[str, float]:
    """Return the appropriate weight set for a sport and market type.

    Only NBA props use 4-component weights (with projections).
    All game lines and non-NBA props use 3-component weights
    so that the full 100% of weight is distributed across active components.
    """
    if is_prop and sport in _PROJECTION_SPORTS:
        return NBA_PROP_WEIGHTS
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

    def market_consensus_score(
        self,
        game_id: str,
        side: str,
        market_type: str,
    ) -> int:
        """Score based on how many sportsbooks show +EV on the same side.

        Counts distinct sportsbooks from the current EV opportunities.
        1 book → 15, 2 → 35, 3 → 55, 4+ → 75.
        +15 bonus if a steam alert confirms this side.
        """
        num_books = 0
        if self._consensus_map is not None:
            key = (game_id, market_type, _normalize_side(side))
            books = self._consensus_map.get(key, set())
            num_books = len(books)

        if num_books >= 4:
            base = 75
        elif num_books >= 3:
            base = 55
        elif num_books >= 2:
            base = 35
        elif num_books >= 1:
            base = 15
        else:
            base = 10

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

        return base

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

        # Determine sport.
        game_info = opportunity.get("games", {}) or {}
        sport = game_info.get("sport", opportunity.get("sport", ""))

        is_prop = market_type.startswith("player_")

        # Calculate individual scores.
        ev = self.ev_score(ev_pct)
        steam = self.steam_score(game_id, side, market_type)

        # Projection score (NBA props only).
        proj = 0
        proj_data = None
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

        consensus = self.market_consensus_score(game_id, side, market_type)

        # Select sport-adaptive weights.
        weights = _get_weights(sport, is_prop)

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

        Builds a consensus map from all opportunities first, then scores each.
        Deduplicates by (game_id, market_type, side) keeping highest strength.

        Args:
            opportunities: List of EV opportunity dicts.
            player_projections: Dict of player_id -> projection dict.

        Returns list of signal dicts sorted by strength descending.
        """
        # Build consensus map: count distinct sportsbooks per (game, market, side).
        self._consensus_map = {}
        for opp in opportunities:
            gid = opp.get("game_id", "")
            mkt = opp.get("market_type", "")
            side_raw = opp.get("side", "")
            book = opp.get("sportsbook", "")
            key = (gid, mkt, _normalize_side(side_raw))
            self._consensus_map.setdefault(key, set()).add(book)

        projections = player_projections or {}
        all_signals: list[dict] = []

        for opp in opportunities:
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

            signal = self.score_opportunity(opp, proj)
            if signal:
                all_signals.append(signal)

        # Deduplicate: keep the strongest signal per (game_id, market_type, side).
        dedup: dict[tuple[str, str, str], dict] = {}
        for sig in all_signals:
            key = (sig["game_id"], sig["market_type"], _normalize_side(sig["side"]))
            existing = dedup.get(key)
            if existing is None or sig["signal_strength"] > existing["signal_strength"]:
                dedup[key] = sig

        signals = list(dedup.values())

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
                    "steam_alerts",
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize_side(side: str) -> str:
    """Normalize a side string for dedup/consensus grouping.

    Strips sportsbook-specific variations so the same logical bet
    (e.g. "Team A -3.5" from different books) groups together.
    """
    return side.strip().lower()


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
