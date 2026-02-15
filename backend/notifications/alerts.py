"""Alert manager — tracks which opportunities have been alerted and sends new ones.

Designed to be called after each scan cycle. Keeps an in-memory set of already-
alerted opportunity IDs to avoid duplicate Discord messages.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "shared"))

from config import MIN_ALERT_EV_THRESHOLD


class AlertManager:
    """Manages Discord alert deduplication and dispatch."""

    def __init__(self, min_ev: float = MIN_ALERT_EV_THRESHOLD) -> None:
        self.min_ev = min_ev
        self._alerted_ev_keys: set[str] = set()
        self._alerted_steam_keys: set[str] = set()

    @staticmethod
    def _ev_key(opp: dict) -> str:
        """Build a unique key for an EV opportunity to prevent duplicate alerts."""
        return f"{opp.get('game_id', '')}|{opp.get('book_key', opp.get('sportsbook', ''))}|{opp.get('market', opp.get('market_type', ''))}|{opp.get('selection', opp.get('side', ''))}"

    @staticmethod
    def _steam_key(alert: dict) -> str:
        return f"{alert.get('game_id', '')}|{alert.get('market_type', '')}|{alert.get('side', '')}|{alert.get('direction', '')}"

    def check_and_alert(self, opportunities: list[dict]) -> int:
        """Check for new +EV opportunities above threshold and send Discord alerts.

        Args:
            opportunities: List of EVOpportunity-like dicts (can be dataclass or DB row).

        Returns:
            Number of alerts sent.
        """
        from notifications.discord import send_ev_alert

        new_opps = []
        for opp in opportunities:
            # Support both EVOpportunity dataclass attrs and DB dict keys.
            ev = opp.get("ev_pct", opp.get("ev_percentage", 0))
            if isinstance(ev, str):
                ev = float(ev)
            if ev < self.min_ev:
                continue

            key = self._ev_key(opp)
            if key in self._alerted_ev_keys:
                continue

            self._alerted_ev_keys.add(key)
            new_opps.append(opp)

        if not new_opps:
            return 0

        # Send in batches of 5 to keep embeds readable.
        sent = 0
        for i in range(0, len(new_opps), 5):
            batch = new_opps[i:i + 5]
            if send_ev_alert(batch):
                sent += len(batch)

        return sent

    def check_steam_alerts(self, alerts: list[dict]) -> int:
        """Send Discord alerts for new steam moves.

        Args:
            alerts: List of steam alert dicts from detect_steam_moves.

        Returns:
            Number of alerts sent.
        """
        from notifications.discord import send_steam_alert

        sent = 0
        for alert in alerts:
            key = self._steam_key(alert)
            if key in self._alerted_steam_keys:
                continue
            self._alerted_steam_keys.add(key)
            if send_steam_alert(alert):
                sent += 1

        return sent


# Module-level singleton so the scanner can import and use it.
alert_manager = AlertManager()
