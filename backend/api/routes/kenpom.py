"""KenPom Edge Finder API — projections vs Pinnacle odds with performance tracking."""

from datetime import date, datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from db import get_supabase

router = APIRouter()


def _table_missing_error(err: Exception) -> bool:
    """Check if an exception indicates a missing table."""
    s = str(err).lower()
    return "does not exist" in s or "relation" in s or "404" in s


def _get_snapshots_for_date(db: Any, target_date: date) -> list[dict]:
    """Fetch all KenPom snapshots for a specific date, sorted by absolute spread edge."""
    try:
        rows = db._get(
            "kenpom_snapshots",
            filters={"snapshot_date": f"eq.{target_date.isoformat()}"},
            order="created_at.desc",
        )
    except Exception as e:
        if _table_missing_error(e):
            return []  # Table not yet created
        raise

    now = datetime.now(timezone.utc)
    for r in rows:
        if r.get("graded"):
            r["status"] = "final"
        else:
            ct = r.get("commence_time")
            if ct:
                try:
                    start = datetime.fromisoformat(ct.replace("Z", "+00:00"))
                    if start <= now:
                        r["status"] = "live"
                    else:
                        hours_until = (start - now).total_seconds() / 3600
                        r["status"] = "upcoming"
                        r["hours_until_start"] = round(hours_until, 1)
                except Exception:
                    r["status"] = "upcoming"
            else:
                r["status"] = "upcoming"

    rows.sort(key=lambda r: abs(r.get("spread_edge") or 0), reverse=True)
    return rows


@router.get("/today")
def get_today() -> dict:
    """All KenPom snapshots for today's games."""
    try:
        db = get_supabase()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    today = date.today()
    snapshots = _get_snapshots_for_date(db, today)
    return {
        "date": today.isoformat(),
        "snapshots": snapshots,
        "message": "Waiting for scanner to run — snapshots populate after KenPom + Pinnacle data loads" if not snapshots else None,
    }


@router.get("/tomorrow")
def get_tomorrow() -> dict:
    """All KenPom snapshots for tomorrow's games."""
    try:
        db = get_supabase()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    tomorrow = date.today() + timedelta(days=1)
    snapshots = _get_snapshots_for_date(db, tomorrow)
    message = None
    if not snapshots:
        message = "Waiting for Pinnacle to open tomorrow's lines"
    return {"date": tomorrow.isoformat(), "snapshots": snapshots, "message": message}


@router.get("/edges")
def get_edges(
    target_date: str = Query(None, alias="date", description="YYYY-MM-DD"),
) -> dict:
    """Games for a specific date, separated into spread and total edge arrays."""
    try:
        db = get_supabase()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    dt = date.fromisoformat(target_date) if target_date else date.today()
    all_snaps = _get_snapshots_for_date(db, dt)

    spread_edges = sorted(
        [s for s in all_snaps if s.get("spread_edge") is not None],
        key=lambda s: abs(s["spread_edge"]),
        reverse=True,
    )
    total_edges = sorted(
        [s for s in all_snaps if s.get("total_edge") is not None],
        key=lambda s: abs(s["total_edge"]),
        reverse=True,
    )

    return {
        "date": dt.isoformat(),
        "spread_edges": spread_edges,
        "total_edges": total_edges,
    }


def _count_results(rows: list[dict]) -> dict:
    """Count wins/losses and sum units from raw graded snapshot rows.

    W/L counts come from result_spread_correct / result_total_correct flags.
    Rows where those flags are None (ungraded or missing Pinnacle data) are
    naturally excluded by the ``is True`` / ``is False`` checks — no extra
    Pinnacle-presence gate is needed.

    Unit sums are returned whenever at least one non-null unit result exists,
    decoupled from whether Pinnacle columns are populated on the row.
    """
    sw = sl = tw = tl = mw = ml = 0
    s_units = t_units = m_units = 0.0
    has_s_units = has_t_units = False
    for r in rows:
        # W/L — None results are excluded naturally.
        if r.get("result_spread_correct") is True:
            sw += 1
        elif r.get("result_spread_correct") is False:
            sl += 1
        if r.get("result_total_correct") is True:
            tw += 1
        elif r.get("result_total_correct") is False:
            tl += 1
        if r.get("result_ml_correct") is True:
            mw += 1
        elif r.get("result_ml_correct") is False:
            ml += 1
        # Sum unit results.
        su = r.get("spread_unit_result")
        tu = r.get("total_unit_result")
        mu = r.get("ml_unit_result")
        if su is not None:
            s_units += su
            has_s_units = True
        if tu is not None:
            t_units += tu
            has_t_units = True
        if mu is not None:
            m_units += mu
    return {
        "spread_wins": sw, "spread_losses": sl,
        "spread_pct": round(sw / (sw + sl) * 100, 1) if (sw + sl) > 0 else 0,
        "spread_units": round(s_units, 2) if has_s_units else None,
        "total_wins": tw, "total_losses": tl,
        "total_pct": round(tw / (tw + tl) * 100, 1) if (tw + tl) > 0 else 0,
        "total_units": round(t_units, 2) if has_t_units else None,
        "ml_wins": mw, "ml_losses": ml,
        "ml_pct": round(mw / (mw + ml) * 100, 1) if (mw + ml) > 0 else 0,
        "ml_units": round(m_units, 2),
    }


def _safe_get_graded(db: Any, extra_filters: dict | None = None) -> list[dict]:
    """Fetch graded snapshots, returning [] if table is missing."""
    filters: dict[str, str] = {"graded": "eq.true"}
    if extra_filters:
        filters.update(extra_filters)
    try:
        return db._get(
            "kenpom_snapshots",
            filters=filters,
            order="snapshot_date.asc",
        )
    except Exception as e:
        if _table_missing_error(e):
            return []
        raise


@router.get("/performance")
def get_performance(
    days: int = Query(30, ge=1, le=365),
) -> dict:
    """Aggregated daily performance stats for graded games over the last N days."""
    try:
        db = get_supabase()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    since = (date.today() - timedelta(days=days)).isoformat()

    rows = _safe_get_graded(db, {"snapshot_date": f"gte.{since}"})

    daily: dict[str, list[dict]] = {}
    for r in rows:
        d = r.get("snapshot_date", "")[:10]
        daily.setdefault(d, []).append(r)

    daily_stats = []
    for dt_str in sorted(daily.keys()):
        day_rows = daily[dt_str]
        stats = _count_results(day_rows)
        stats["date"] = dt_str
        stats["games_graded"] = len(day_rows)

        spread_winner_edges = [
            abs(r.get("spread_edge", 0))
            for r in day_rows if r.get("result_spread_correct") is True
        ]
        total_winner_edges = [
            abs(r.get("total_edge", 0))
            for r in day_rows if r.get("result_total_correct") is True
        ]
        stats["avg_spread_edge_winners"] = (
            round(sum(spread_winner_edges) / len(spread_winner_edges), 2)
            if spread_winner_edges else 0
        )
        stats["avg_total_edge_winners"] = (
            round(sum(total_winner_edges) / len(total_winner_edges), 2)
            if total_winner_edges else 0
        )
        # Units are already in stats from _count_results (spread_units, total_units, ml_units).
        daily_stats.append(stats)

    season = _count_results(rows)
    season["total_games_graded"] = len(rows)
    season["last_updated"] = datetime.now(timezone.utc).isoformat()

    return {"season": season, "daily": daily_stats}


@router.get("/performance/season")
def get_performance_season() -> dict:
    """Full season aggregated stats with edge bucket analysis and rolling accuracy."""
    try:
        db = get_supabase()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    rows = _safe_get_graded(db)

    season = _count_results(rows)
    season["total_games_graded"] = len(rows)
    sw, sl = season["spread_wins"], season["spread_losses"]
    tw, tl = season["total_wins"], season["total_losses"]
    mw, ml_ = season["ml_wins"], season["ml_losses"]
    season["spread_record"] = f"{sw}-{sl}" if (sw + sl) > 0 else None
    season["total_record"] = f"{tw}-{tl}" if (tw + tl) > 0 else None
    season["ml_record"] = f"{mw}-{ml_}" if (mw + ml_) > 0 else None
    season["last_updated"] = datetime.now(timezone.utc).isoformat()

    buckets_def = [
        (0, 1, "0-1"),
        (1, 3, "1-3"),
        (3, 5, "3-5"),
        (5, 7, "5-7"),
        (7, 999, "7+"),
    ]

    edge_buckets = []
    for lo, hi, label in buckets_def:
        bucket_rows = [
            r for r in rows
            if lo <= abs(r.get("spread_edge") or 0) < hi
        ]
        b_stats = _count_results(bucket_rows)
        edge_buckets.append({
            "bucket": label,
            "games": len(bucket_rows),
            "spread_accuracy": b_stats["spread_pct"],
            "total_accuracy": b_stats["total_pct"],
            "spread_units": b_stats["spread_units"],
            "total_units": b_stats["total_units"],
        })

    daily_map: dict[str, list[dict]] = {}
    for r in rows:
        d = r.get("snapshot_date", "")[:10]
        daily_map.setdefault(d, []).append(r)

    sorted_dates = sorted(daily_map.keys())
    rolling_spread: list[dict] = []
    rolling_total: list[dict] = []
    rolling_ml: list[dict] = []

    for i, dt_str in enumerate(sorted_dates):
        window_start = max(0, i - 6)
        window_rows = []
        for j in range(window_start, i + 1):
            window_rows.extend(daily_map[sorted_dates[j]])

        w = _count_results(window_rows)
        rolling_spread.append({"date": dt_str, "accuracy": w["spread_pct"]})
        rolling_total.append({"date": dt_str, "accuracy": w["total_pct"]})
        rolling_ml.append({"date": dt_str, "accuracy": w["ml_pct"]})

    return {
        "season": season,
        "edge_buckets": edge_buckets,
        "rolling_7day": {
            "spread": rolling_spread,
            "total": rolling_total,
            "ml": rolling_ml,
        },
    }


# ---------------------------------------------------------------------------
# Diagnostic / seed test data endpoint
# ---------------------------------------------------------------------------

@router.get("/diagnostic")
def diagnostic() -> dict:
    """Full diagnostic — checks DB connection, table existence, row count."""
    diag: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "db_connected": False,
        "table_exists": False,
        "row_count": 0,
        "today_count": 0,
        "errors": [],
    }

    try:
        db = get_supabase()
        diag["db_connected"] = True
    except Exception as e:
        diag["errors"].append(f"get_supabase() failed: {e}")
        return diag

    try:
        rows = db._get("kenpom_snapshots", select="id", limit=1)
        diag["table_exists"] = True
    except Exception as e:
        if _table_missing_error(e):
            diag["errors"].append(f"Table does not exist: {e}")
        else:
            diag["errors"].append(f"DB query error: {e}")
        return diag

    try:
        all_rows = db._get("kenpom_snapshots", select="id,snapshot_date")
        diag["row_count"] = len(all_rows)
        today_str = date.today().isoformat()
        diag["today_count"] = sum(1 for r in all_rows if r.get("snapshot_date", "")[:10] == today_str)
    except Exception as e:
        diag["errors"].append(f"Count query error: {e}")

    return diag


@router.post("/seed-test-data")
def seed_test_data() -> dict:
    """Insert 3 realistic test snapshots for today. For development testing only."""
    try:
        db = get_supabase()
    except Exception as e:
        return {"error": f"get_supabase() failed: {e}"}

    today_str = date.today().isoformat()
    two_hours = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()

    test_rows = [
        {
            "snapshot_date": today_str,
            "game_id": f"test_cbb_{today_str}_001",
            "sport": "basketball_ncaab",
            "home_team": "Duke Blue Devils",
            "away_team": "North Carolina Tar Heels",
            "commence_time": two_hours,
            "kp_home_score": 78.3,
            "kp_away_score": 72.1,
            "kp_home_win_prob": 0.72,
            "kp_projected_total": 150.4,
            "kp_projected_spread": 6.2,
            "pinnacle_spread_home": -3.5,
            "pinnacle_total": 147.5,
            "pinnacle_home_ml": -165,
            "pinnacle_away_ml": 140,
            "pinnacle_home_implied_prob": 0.6226,
            "spread_edge": 9.7,
            "total_edge": 2.9,
            "ml_edge": 0.0974,
            "graded": False,
        },
        {
            "snapshot_date": today_str,
            "game_id": f"test_cbb_{today_str}_002",
            "sport": "basketball_ncaab",
            "home_team": "Kansas Jayhawks",
            "away_team": "Kentucky Wildcats",
            "commence_time": two_hours,
            "kp_home_score": 74.8,
            "kp_away_score": 70.2,
            "kp_home_win_prob": 0.65,
            "kp_projected_total": 145.0,
            "kp_projected_spread": 4.6,
            "pinnacle_spread_home": -1.5,
            "pinnacle_total": 143.5,
            "pinnacle_home_ml": -125,
            "pinnacle_away_ml": 105,
            "pinnacle_home_implied_prob": 0.5556,
            "spread_edge": 6.1,
            "total_edge": 1.5,
            "ml_edge": 0.0944,
            "graded": False,
        },
        {
            "snapshot_date": today_str,
            "game_id": f"test_cbb_{today_str}_003",
            "sport": "basketball_ncaab",
            "home_team": "Gonzaga Bulldogs",
            "away_team": "UCLA Bruins",
            "commence_time": two_hours,
            "kp_home_score": 82.5,
            "kp_away_score": 76.0,
            "kp_home_win_prob": 0.70,
            "kp_projected_total": 158.5,
            "kp_projected_spread": 6.5,
            "pinnacle_spread_home": -5.5,
            "pinnacle_total": 155.0,
            "pinnacle_home_ml": -210,
            "pinnacle_away_ml": 175,
            "pinnacle_home_implied_prob": 0.6774,
            "spread_edge": 12.0,
            "total_edge": 3.5,
            "ml_edge": 0.0226,
            "graded": False,
        },
    ]

    try:
        db._upsert_many(
            "kenpom_snapshots", test_rows, on_conflict="snapshot_date,game_id"
        )
        return {
            "success": True,
            "message": f"Inserted {len(test_rows)} test snapshots for {today_str}",
            "rows": test_rows,
        }
    except Exception as e:
        err_str = str(e)
        if _table_missing_error(e):
            return {
                "error": "Table kenpom_snapshots does not exist",
                "fix": "Run: python scripts/create_kenpom_table.py — or paste scripts/008_kenpom_snapshots.sql into Supabase SQL Editor",
            }
        return {"error": err_str}
