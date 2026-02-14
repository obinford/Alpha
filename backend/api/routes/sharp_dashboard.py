from fastapi import APIRouter, HTTPException

from db import get_supabase, get_recent_steam_alerts, get_biggest_recent_moves

from datetime import datetime, timedelta, timezone

router = APIRouter()


@router.get("/")
def sharp_dashboard() -> dict:
    """Combined sharp money dashboard.

    Returns:
        - latest_alerts: top 10 steam alerts from last 24h
        - biggest_moves: top 10 line movements from last 6h
        - summary: total alerts today, most active sport, most moved game
    """
    try:
        db = get_supabase()
        now = datetime.now(timezone.utc)

        # Steam alerts from last 24 hours.
        alerts_since = (now - timedelta(hours=24)).isoformat()
        all_alerts = get_recent_steam_alerts(db, alerts_since)
        latest_alerts = all_alerts[:10]

        # Biggest moves from last 6 hours.
        moves_since = (now - timedelta(hours=6)).isoformat()
        biggest_moves = get_biggest_recent_moves(db, moves_since, limit=10)

        # Summary stats.
        total_alerts_today = len(all_alerts)

        most_active_sport = None
        most_moved_game = None

        if all_alerts:
            # Count alerts per sport.
            sport_counts: dict[str, int] = {}
            for a in all_alerts:
                s = a.get("sport", "unknown")
                sport_counts[s] = sport_counts.get(s, 0) + 1
            most_active_sport = max(sport_counts, key=sport_counts.get)  # type: ignore[arg-type]

        if biggest_moves:
            # Game with the largest single move.
            top = biggest_moves[0]
            games_info = top.get("games") or {}
            home = games_info.get("home_team", "")
            away = games_info.get("away_team", "")
            most_moved_game = {
                "game_id": top.get("game_id"),
                "label": f"{away} @ {home}" if away and home else top.get("game_id"),
                "odds_change": top.get("odds_change"),
            }

        return {
            "latest_alerts": latest_alerts,
            "biggest_moves": biggest_moves,
            "summary": {
                "total_alerts_today": total_alerts_today,
                "most_active_sport": most_active_sport,
                "most_moved_game": most_moved_game,
            },
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
