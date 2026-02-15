"""Player props API — dedicated endpoint for prop market EV opportunities."""

import re

from fastapi import APIRouter, HTTPException, Query

from db import get_supabase

router = APIRouter()

PROP_MARKET_LABELS = {
    "player_points": "Points",
    "player_rebounds": "Rebounds",
    "player_assists": "Assists",
    "player_threes": "Threes",
    "player_blocks": "Blocks",
    "player_steals": "Steals",
    "player_points_rebounds_assists": "PRA",
    "player_pass_tds": "Pass TDs",
    "player_pass_yds": "Pass Yds",
    "player_rush_yds": "Rush Yds",
    "player_receptions": "Receptions",
    "player_reception_yds": "Rec Yds",
    "player_anytime_td": "Anytime TD",
}

# Regex to split "Player Name Over 28.5" or "Player Name Under 220.5"
_SIDE_RE = re.compile(r"^(.+?)\s+(Over|Under)\s+([\d.]+)$", re.IGNORECASE)


def _parse_prop_side(side: str) -> dict:
    """Parse a prop side string into player, direction, line."""
    m = _SIDE_RE.match(side or "")
    if m:
        return {
            "player": m.group(1).strip(),
            "direction": m.group(2).capitalize(),
            "line": float(m.group(3)),
        }
    return {"player": side or "", "direction": "", "line": None}


def _normalize_prop(row: dict, new_keys: set[str] | None = None) -> dict:
    """Flatten an ev_opportunities row into a prop-friendly dict."""
    game = row.get("games", {}) or {}
    parsed = _parse_prop_side(row.get("side", ""))
    market = row.get("market_type", "")
    commence = row.get("commence_time") or game.get("start_time")

    # Unique key for new-line detection.
    key = f"{parsed['player']}|{market}|{parsed['direction']}|{parsed['line']}"
    is_new = key in new_keys if new_keys else False

    return {
        "id": row.get("id"),
        "game_id": row.get("game_id"),
        "sport": game.get("sport", row.get("sport", "")),
        "home_team": game.get("home_team", ""),
        "away_team": game.get("away_team", ""),
        "game": f"{game.get('away_team', '')} @ {game.get('home_team', '')}",
        "start_time": game.get("start_time"),
        "commence_time": commence,
        "player": parsed["player"],
        "prop_type": market,
        "prop_label": PROP_MARKET_LABELS.get(market, market),
        "direction": parsed["direction"],
        "line": parsed["line"],
        "sportsbook": row.get("sportsbook", ""),
        "odds": row.get("book_odds"),
        "book_implied_prob": row.get("book_implied_prob"),
        "true_prob": row.get("true_prob"),
        "ev_pct": row.get("ev_percentage"),
        "kelly": row.get("kelly_fraction"),
        "units": row.get("recommended_units"),
        "timestamp": row.get("timestamp"),
        "selection": row.get("side", ""),
        "is_new_line": is_new,
    }


@router.get("/")
def list_props(
    sport: str | None = Query(None, description="Filter by sport key"),
    prop_type: str | None = Query(None, description="Filter by prop market type"),
    player: str | None = Query(None, description="Filter by player name (partial match)"),
    sportsbook: str | None = Query(None, description="Filter by sportsbook"),
    min_ev: float | None = Query(None, ge=0, description="Minimum EV%"),
) -> dict:
    """Return player prop EV opportunities from the latest scan."""
    try:
        return _list_props_impl(sport, prop_type, player, sportsbook, min_ev)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _list_props_impl(sport, prop_type, player, sportsbook, min_ev) -> dict:
    db = get_supabase()

    # Find latest scan timestamp.
    latest = db._get(
        "ev_opportunities",
        select="timestamp",
        order="timestamp.desc",
        limit=1,
    )
    if not latest:
        return {"count": 0, "props": [], "by_player": {}, "by_type": {}}

    latest_ts = latest[0]["timestamp"]

    # Find previous scan timestamp to detect new lines.
    prev_scans = db._get(
        "ev_opportunities",
        select="timestamp",
        filters={"timestamp": f"lt.{latest_ts}", "market_type": "like.player_*"},
        order="timestamp.desc",
        limit=1,
    )
    prev_keys: set[str] = set()
    if prev_scans:
        prev_ts = prev_scans[0]["timestamp"]
        prev_rows = db._get(
            "ev_opportunities",
            select="side,market_type",
            filters={"timestamp": f"eq.{prev_ts}", "market_type": "like.player_*"},
        )
        for r in prev_rows:
            m = _SIDE_RE.match(r.get("side", ""))
            if m:
                prev_keys.add(
                    f"{m.group(1).strip()}|{r['market_type']}|"
                    f"{m.group(2).capitalize()}|{float(m.group(3))}"
                )

    # Keys in current scan but NOT in prev scan = new lines.
    filters: dict[str, str] = {
        "timestamp": f"eq.{latest_ts}",
        "market_type": f"like.player_*",
    }
    if min_ev is not None:
        filters["ev_percentage"] = f"gte.{min_ev}"
    if sportsbook is not None:
        filters["sportsbook"] = f"eq.{sportsbook}"
    if prop_type is not None:
        filters["market_type"] = f"eq.{prop_type}"

    rows = db._get(
        "ev_opportunities",
        select="*,games(game_id,sport,home_team,away_team,start_time)",
        filters=filters,
        order="ev_percentage.desc",
    )

    # Build set of current keys, then find new ones.
    current_keys: set[str] = set()
    for row in rows:
        parsed = _parse_prop_side(row.get("side", ""))
        key = (
            f"{parsed['player']}|{row.get('market_type', '')}|"
            f"{parsed['direction']}|{parsed['line']}"
        )
        current_keys.add(key)
    new_keys = current_keys - prev_keys

    # Client-side filtering for sport and player.
    props = []
    new_line_count = 0
    for row in rows:
        p = _normalize_prop(row, new_keys)
        if sport and p["sport"] != sport:
            continue
        if player and player.lower() not in p["player"].lower():
            continue
        props.append(p)
        if p["is_new_line"]:
            new_line_count += 1

    # Group by player.
    by_player: dict[str, list[dict]] = {}
    for p in props:
        name = p["player"] or "Unknown"
        by_player.setdefault(name, []).append(p)

    # Group by prop type.
    by_type: dict[str, int] = {}
    for p in props:
        label = p["prop_label"]
        by_type[label] = by_type.get(label, 0) + 1

    return {
        "count": len(props),
        "new_line_count": new_line_count,
        "props": props,
        "by_player": {k: len(v) for k, v in by_player.items()},
        "by_type": by_type,
        "scan_time": latest_ts,
    }


@router.get("/types")
def prop_types() -> dict:
    """Return available prop market types and their labels."""
    return {"types": PROP_MARKET_LABELS}
