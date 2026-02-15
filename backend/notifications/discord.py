"""Discord webhook integration for RTM Picks alerts.

Sends formatted embeds for +EV plays, steam moves, and daily recaps.
If DISCORD_WEBHOOK_URL is not configured, all functions are no-ops.
"""

import os
import time
from datetime import datetime, timezone
from typing import Any

import httpx

WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")

# Rate limit: minimum seconds between Discord messages.
_RATE_LIMIT_SECONDS = 2.0
_last_send_time: float = 0.0


def _is_enabled() -> bool:
    """Check if Discord notifications are configured."""
    url = os.environ.get("DISCORD_WEBHOOK_URL", "") or WEBHOOK_URL
    return bool(url)


def _get_url() -> str:
    return os.environ.get("DISCORD_WEBHOOK_URL", "") or WEBHOOK_URL


def _rate_limit() -> None:
    """Enforce minimum delay between Discord messages."""
    global _last_send_time
    now = time.monotonic()
    elapsed = now - _last_send_time
    if elapsed < _RATE_LIMIT_SECONDS:
        time.sleep(_RATE_LIMIT_SECONDS - elapsed)
    _last_send_time = time.monotonic()


def _send_webhook(payload: dict[str, Any]) -> bool:
    """Send a payload to the Discord webhook. Returns True on success."""
    url = _get_url()
    if not url:
        return False
    _rate_limit()
    try:
        resp = httpx.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        return True
    except Exception:
        return False


def _ev_color(ev_pct: float) -> int:
    """Return embed color based on EV percentage."""
    if ev_pct >= 15:
        return 0xFF4444  # red/fire for 15%+
    if ev_pct >= 10:
        return 0xFFD700  # gold for 10-15%
    return 0x00FF88  # green for 5-10%


def _format_odds(odds: int | float) -> str:
    odds = int(odds)
    return f"+{odds}" if odds > 0 else str(odds)


def _sport_label(sport_key: str) -> str:
    """Convert API sport key to short display name."""
    labels = {
        "baseball_mlb": "MLB", "basketball_nba": "NBA",
        "americanfootball_nfl": "NFL", "icehockey_nhl": "NHL",
        "americanfootball_ncaaf": "CFB", "basketball_ncaab": "CBB",
        "basketball_wnba": "WNBA",
    }
    return labels.get(sport_key, sport_key)


def send_ev_alert(opportunities: list[dict]) -> bool:
    """Send a Discord embed for new +EV opportunities.

    Each opportunity dict should have: sport_key, game, selection, book,
    book_odds, ev_pct, true_prob, kelly_pct, market, point.
    """
    if not _is_enabled() or not opportunities:
        return False

    count = len(opportunities)
    title = f"\U0001f525 NEW +EV PLAY" if count == 1 else f"\U0001f525 {count} NEW +EV PLAYS"

    # Use the highest EV for the embed color.
    max_ev = max(o.get("ev_pct", 0) for o in opportunities)
    color = _ev_color(max_ev)

    fields = []
    for opp in opportunities[:10]:  # Cap at 10 fields per embed
        sport = _sport_label(opp.get("sport_key", ""))
        game = opp.get("game", "")
        selection = opp.get("selection", "")
        book = opp.get("book", "")
        odds_str = _format_odds(opp.get("book_odds", 0))
        ev = opp.get("ev_pct", 0)
        true_prob = opp.get("true_prob", 0)
        kelly = opp.get("kelly_pct", 0)
        units = round(kelly * 100, 2)

        fields.append({
            "name": f"{sport} | {game}",
            "value": (
                f"**Pick:** {selection}\n"
                f"**Book:** {book} | **Odds:** {odds_str}\n"
                f"**EV:** {ev:+.1f}% | **True Prob:** {true_prob * 100:.1f}% | "
                f"**Kelly:** {kelly * 100:.2f}% | **Units:** {units}"
            ),
            "inline": False,
        })

    embed = {
        "title": title,
        "color": color,
        "fields": fields,
        "footer": {"text": "RTM Picks | Systems Over Opinions"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    return _send_webhook({"embeds": [embed]})


def send_steam_alert(alert: dict) -> bool:
    """Send a Discord embed for a steam move detection.

    alert dict should have: game_id, sport, side, direction, books_moved,
    magnitude, market_type, and optionally games (nested with home/away teams).
    """
    if not _is_enabled():
        return False

    game_info = alert.get("games", {}) or {}
    game_name = (
        f"{game_info.get('away_team', '?')} @ {game_info.get('home_team', '?')}"
        if game_info else alert.get("game_id", "Unknown")
    )
    direction = alert.get("direction", "")
    is_on = direction == "shortened"
    dir_label = "SHARP MONEY ON" if is_on else "SHARP MONEY AGAINST"
    color = 0xFF4444 if is_on else 0x42A5F5

    books = alert.get("books_moved", [])
    if isinstance(books, list):
        books_str = ", ".join(books)
        book_count = len(books)
    else:
        books_str = str(books)
        book_count = 1

    side = alert.get("side", "")
    magnitude = alert.get("magnitude", 0)
    sport = _sport_label(alert.get("sport", ""))

    embed = {
        "title": "\U0001f6a8 STEAM MOVE DETECTED",
        "description": f"**{book_count}** books moved **{direction}** on **{side}** in {game_name}",
        "color": color,
        "fields": [
            {"name": "Sport", "value": sport, "inline": True},
            {"name": "Direction", "value": dir_label, "inline": True},
            {"name": "Magnitude", "value": str(magnitude), "inline": True},
            {"name": "Market", "value": alert.get("market_type", ""), "inline": True},
            {"name": "Books", "value": books_str or "—", "inline": False},
        ],
        "footer": {"text": "RTM Picks | Systems Over Opinions"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    return _send_webhook({"embeds": [embed]})


def send_daily_recap(recap: dict) -> bool:
    """Send a Discord embed for the daily performance recap.

    recap dict should have: date, record, units, roi, total_bets,
    best_bet, steam_alerts, avg_clv, by_sport, alltime_record, alltime_roi.
    """
    if not _is_enabled():
        return False

    date_str = recap.get("date", "")
    units = recap.get("units", 0)
    color = 0x00FF88 if units >= 0 else 0xFF4444

    record = recap.get("record", "0-0-0")
    roi = recap.get("roi", 0)
    total = recap.get("total_bets", 0)
    best = recap.get("best_bet", "—")
    steam = recap.get("steam_alerts", 0)
    avg_clv = recap.get("avg_clv", 0)
    alltime_rec = recap.get("alltime_record", "—")
    alltime_roi = recap.get("alltime_roi", 0)

    fields = [
        {"name": "Record", "value": record, "inline": True},
        {"name": "Units", "value": f"{units:+.2f}", "inline": True},
        {"name": "ROI", "value": f"{roi:+.1f}%", "inline": True},
        {"name": "Total Bets", "value": str(total), "inline": True},
        {"name": "Avg CLV", "value": f"{avg_clv:+.2f}%", "inline": True},
        {"name": "Steam Alerts", "value": str(steam), "inline": True},
        {"name": "Best Bet", "value": str(best), "inline": False},
        {"name": "All-Time Record", "value": str(alltime_rec), "inline": True},
        {"name": "All-Time ROI", "value": f"{alltime_roi:+.1f}%", "inline": True},
    ]

    # Sport breakdown.
    by_sport = recap.get("by_sport", {})
    if by_sport:
        lines = []
        for sport, stats in sorted(by_sport.items()):
            lines.append(f"**{sport}:** {stats.get('record', '—')} | {stats.get('units', 0):+.1f}u")
        fields.append({"name": "By Sport", "value": "\n".join(lines), "inline": False})

    embed = {
        "title": f"\U0001f4ca RTM DAILY RECAP | {date_str}",
        "color": color,
        "fields": fields,
        "footer": {"text": "RTM Picks | Systems Over Opinions"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    return _send_webhook({"embeds": [embed]})


def build_ev_payload(opportunities: list[dict]) -> dict:
    """Build the Discord webhook JSON payload without sending it (for testing)."""
    count = len(opportunities)
    title = "\U0001f525 NEW +EV PLAY" if count == 1 else f"\U0001f525 {count} NEW +EV PLAYS"
    max_ev = max((o.get("ev_pct", 0) for o in opportunities), default=0)
    color = _ev_color(max_ev)

    fields = []
    for opp in opportunities[:10]:
        sport = _sport_label(opp.get("sport_key", ""))
        odds_str = _format_odds(opp.get("book_odds", 0))
        ev = opp.get("ev_pct", 0)
        true_prob = opp.get("true_prob", 0)
        kelly = opp.get("kelly_pct", 0)
        units = round(kelly * 100, 2)
        fields.append({
            "name": f"{sport} | {opp.get('game', '')}",
            "value": (
                f"**Pick:** {opp.get('selection', '')}\n"
                f"**Book:** {opp.get('book', '')} | **Odds:** {odds_str}\n"
                f"**EV:** {ev:+.1f}% | **True Prob:** {true_prob * 100:.1f}% | "
                f"**Kelly:** {kelly * 100:.2f}% | **Units:** {units}"
            ),
            "inline": False,
        })

    return {
        "embeds": [{
            "title": title,
            "color": color,
            "fields": fields,
            "footer": {"text": "RTM Picks | Systems Over Opinions"},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }]
    }


def send_signal_alert(signal: dict) -> bool:
    """Send a Discord embed for an RTM Signal alert.

    Signal dict should have: star_rating, signal_strength, side, sportsbook,
    book_odds, edge_percentage, ev_score, steam_score, projection_score,
    consensus_score, kelly_size, sport, game, player_name.
    """
    if not _is_enabled():
        return False

    stars = signal.get("star_rating", 3)
    strength = signal.get("signal_strength", 0)

    if stars >= 5:
        title = "\u26a1 RTM SIGNAL \u2014 STRONG"
        color = 0x00FF88
    elif stars >= 4:
        title = "\U0001f525 RTM SIGNAL"
        color = 0xFFD700
    else:
        title = "\U0001f4ca RTM LEAN"
        color = 0x42A5F5

    star_str = "\u2b50" * stars
    sport = _sport_label(signal.get("sport", ""))
    game = signal.get("game", "")
    side = signal.get("side", "")
    odds_str = _format_odds(signal.get("book_odds", 0))
    book = signal.get("sportsbook", "")
    edge = signal.get("edge_percentage", 0)
    kelly = signal.get("kelly_size", 0)

    fields = [
        {"name": "Play", "value": f"**{side}**", "inline": False},
        {"name": "Rating", "value": f"{star_str} ({strength:.0f}/100)", "inline": True},
        {"name": "Sport", "value": sport, "inline": True},
        {"name": "Game", "value": game or "\u2014", "inline": True},
        {"name": "Book", "value": book, "inline": True},
        {"name": "Odds", "value": odds_str, "inline": True},
        {"name": "Edge", "value": f"{edge:+.1f}%", "inline": True},
        {"name": "\u200b", "value": "**Signal Components**", "inline": False},
        {"name": "EV Score", "value": str(signal.get("ev_score", 0)), "inline": True},
        {"name": "Steam Score", "value": str(signal.get("steam_score", 0)), "inline": True},
        {"name": "Proj Score", "value": str(signal.get("projection_score", 0)), "inline": True},
        {"name": "Consensus", "value": str(signal.get("consensus_score", 0)), "inline": True},
    ]

    if kelly > 0:
        fields.append({"name": "Kelly Size", "value": f"{kelly:.1f}%", "inline": True})

    embed = {
        "title": title,
        "color": color,
        "fields": fields,
        "footer": {"text": "RTM Signal | Systems Over Opinions"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    return _send_webhook({"embeds": [embed]})
