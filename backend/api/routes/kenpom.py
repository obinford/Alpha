"""KenPom Edge Finder API — projections vs Pinnacle odds with performance tracking."""

from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Query

from db import get_supabase, SupabaseClient

router = APIRouter()


def _get_snapshots_for_date(client: SupabaseClient, target_date: date) -> list[dict]:
    """Fetch all KenPom snapshots for a specific date, sorted by absolute spread edge."""
    rows = client._get(
        "kenpom_snapshots",
        filters={"snapshot_date": f"eq.{target_date.isoformat()}"},
        order="created_at.desc",
    )

    now = datetime.now(timezone.utc)
    for r in rows:
        # Compute status from commence_time and graded flag.
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

    # Sort by absolute spread edge descending.
    rows.sort(key=lambda r: abs(r.get("spread_edge") or 0), reverse=True)
    return rows


@router.get("/today")
def get_today() -> dict:
    """All KenPom snapshots for today's games."""
    client = get_supabase()
    today = date.today()
    snapshots = _get_snapshots_for_date(client, today)
    return {"date": today.isoformat(), "snapshots": snapshots}


@router.get("/tomorrow")
def get_tomorrow() -> dict:
    """All KenPom snapshots for tomorrow's games."""
    client = get_supabase()
    tomorrow = date.today() + timedelta(days=1)
    snapshots = _get_snapshots_for_date(client, tomorrow)
    message = None
    if not snapshots:
        message = "Waiting for Pinnacle to open tomorrow's lines"
    return {"date": tomorrow.isoformat(), "snapshots": snapshots, "message": message}


@router.get("/edges")
def get_edges(
    target_date: str = Query(None, alias="date", description="YYYY-MM-DD"),
) -> dict:
    """Games for a specific date, separated into spread and total edge arrays."""
    client = get_supabase()
    dt = date.fromisoformat(target_date) if target_date else date.today()
    all_snaps = _get_snapshots_for_date(client, dt)

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
    """Count wins/losses from raw graded snapshot rows. Method B (manual count)."""
    sw = sl = tw = tl = mw = ml = 0
    for r in rows:
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
    return {
        "spread_wins": sw, "spread_losses": sl,
        "spread_pct": round(sw / (sw + sl) * 100, 1) if (sw + sl) > 0 else 0,
        "total_wins": tw, "total_losses": tl,
        "total_pct": round(tw / (tw + tl) * 100, 1) if (tw + tl) > 0 else 0,
        "ml_wins": mw, "ml_losses": ml,
        "ml_pct": round(mw / (mw + ml) * 100, 1) if (mw + ml) > 0 else 0,
    }


@router.get("/performance")
def get_performance(
    days: int = Query(30, ge=1, le=365),
) -> dict:
    """Aggregated daily performance stats for graded games over the last N days."""
    client = get_supabase()
    since = (date.today() - timedelta(days=days)).isoformat()

    rows = client._get(
        "kenpom_snapshots",
        filters={
            "graded": "eq.true",
            "snapshot_date": f"gte.{since}",
        },
        order="snapshot_date.asc",
    )

    # Group by date.
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

        # Average edge on winners.
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

        daily_stats.append(stats)

    # Season totals from manual count (Method B — most trustworthy).
    season = _count_results(rows)
    season["total_games_graded"] = len(rows)
    season["last_updated"] = datetime.now(timezone.utc).isoformat()

    return {"season": season, "daily": daily_stats}


@router.get("/performance/season")
def get_performance_season() -> dict:
    """Full season aggregated stats with edge bucket analysis and rolling accuracy."""
    client = get_supabase()

    rows = client._get(
        "kenpom_snapshots",
        filters={"graded": "eq.true"},
        order="snapshot_date.asc",
    )

    # Method B: manual count (trustworthy).
    season = _count_results(rows)
    season["total_games_graded"] = len(rows)

    # Verify W + L = total games that had non-null results.
    spread_total = season["spread_wins"] + season["spread_losses"]
    total_total = season["total_wins"] + season["total_losses"]
    ml_total = season["ml_wins"] + season["ml_losses"]

    season["spread_record"] = f"{season['spread_wins']}-{season['spread_losses']}"
    season["total_record"] = f"{season['total_wins']}-{season['total_losses']}"
    season["ml_record"] = f"{season['ml_wins']}-{season['ml_losses']}"
    season["last_updated"] = datetime.now(timezone.utc).isoformat()

    # Edge bucket analysis: [0-1, 1-3, 3-5, 5-7, 7+]
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
        })

    # Rolling 7-day accuracy for charting.
    daily_map: dict[str, list[dict]] = {}
    for r in rows:
        d = r.get("snapshot_date", "")[:10]
        daily_map.setdefault(d, []).append(r)

    sorted_dates = sorted(daily_map.keys())
    rolling_spread: list[dict] = []
    rolling_total: list[dict] = []
    rolling_ml: list[dict] = []

    for i, dt_str in enumerate(sorted_dates):
        # Get the last 7 days of data (inclusive of this date).
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
