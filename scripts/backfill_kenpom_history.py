#!/usr/bin/env python3
"""Backfill KenPom snapshots from historical data.

Attempts to build kenpom_snapshots for past CBB games by:
1. Fetching KenPom fanmatch predictions for each historical date.
2. Looking up Pinnacle odds from true_lines or odds_snapshots tables.
3. Grading against final game scores.

Safe to run multiple times (idempotent — uses upserts).

Usage:
    python scripts/backfill_kenpom_history.py          # last 30 days
    python scripts/backfill_kenpom_history.py --days 7  # last 7 days
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "shared"))

from datetime import date, datetime, timedelta, timezone

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Backfill KenPom snapshots")
    parser.add_argument("--days", type=int, default=30, help="Days to look back")
    args = parser.parse_args()

    from db import get_supabase

    db = get_supabase()

    # Check if historical Pinnacle odds are available.
    has_historical_odds = False
    try:
        check = db._get(
            "odds_snapshots",
            select="id",
            filters={"sportsbook": "eq.pinnacle"},
            limit=1,
        )
        has_historical_odds = bool(check)
    except Exception:
        pass

    if not has_historical_odds:
        # Check true_lines as alternative source.
        try:
            check = db._get("true_lines", select="id", limit=1)
            has_historical_odds = bool(check)
        except Exception:
            pass

    if not has_historical_odds:
        today_str = date.today().isoformat()
        print(
            f"Historical Pinnacle odds not available. "
            f"KP tracking starts from {today_str}. "
            f"Full season data will build over time."
        )
        print("You can still run this script after a few days of scanner operation.")
        return

    today = date.today()
    total_saved = 0
    total_graded = 0
    days_processed = 0

    print(f"Backfilling KenPom snapshots for the last {args.days} days...")

    for days_ago in range(args.days, -1, -1):
        target_date = today - timedelta(days=days_ago)
        target_str = target_date.isoformat()

        # Get CBB games for this date from the games table.
        try:
            games = db._get(
                "games",
                select="game_id,sport,home_team,away_team,start_time,status,home_score,away_score",
                filters={
                    "sport": "eq.basketball_ncaab",
                    "start_time": f"gte.{target_str}T00:00:00Z",
                },
            )
            # Filter to games on this specific date.
            games = [
                g for g in games
                if g.get("start_time", "")[:10] == target_str
            ]
        except Exception:
            continue

        if not games:
            continue

        # Check which games already have snapshots.
        game_ids = [g["game_id"] for g in games]
        existing: set[str] = set()
        for i in range(0, len(game_ids), 50):
            chunk = game_ids[i : i + 50]
            id_list = ",".join(chunk)
            try:
                rows = db._get(
                    "kenpom_snapshots",
                    select="game_id",
                    filters={
                        "snapshot_date": f"eq.{target_str}",
                        "game_id": f"in.({id_list})",
                    },
                )
                existing.update(r["game_id"] for r in rows)
            except Exception:
                pass

        new_games = [g for g in games if g["game_id"] not in existing]
        if not new_games:
            continue

        # Try to fetch KenPom fanmatch for this date.
        kp_projections: dict[str, dict] = {}
        try:
            from intelligence.kenpom import KenPomClient

            teams = []
            for g in new_games:
                if g["home_team"] not in teams:
                    teams.append(g["home_team"])
                if g["away_team"] not in teams:
                    teams.append(g["away_team"])

            kp = KenPomClient(odds_api_teams=teams)
            kp.refresh(target_date=target_date)

            for g in new_games:
                proj = kp.get_projection(g["home_team"], g["away_team"])
                if proj:
                    kp_projections[g["game_id"]] = proj
        except Exception as e:
            # Fanmatch may not work for this date — try ratings fallback.
            try:
                from intelligence.kenpom import KenPomClient

                teams = []
                for g in new_games:
                    if g["home_team"] not in teams:
                        teams.append(g["home_team"])
                    if g["away_team"] not in teams:
                        teams.append(g["away_team"])

                kp = KenPomClient(odds_api_teams=teams)
                kp.refresh_ratings_only()

                for g in new_games:
                    proj = kp.get_projection(g["home_team"], g["away_team"])
                    if proj:
                        kp_projections[g["game_id"]] = proj
            except Exception:
                pass

        if not kp_projections:
            continue

        # Get Pinnacle odds from odds_snapshots or true_lines.
        pinnacle_data: dict[str, dict] = {}
        for i in range(0, len(game_ids), 50):
            chunk = game_ids[i : i + 50]
            id_list = ",".join(chunk)
            try:
                # Try odds_snapshots first (has actual Pinnacle lines).
                snaps = db._get(
                    "odds_snapshots",
                    select="game_id,market_type,home_odds,away_odds,spread_value,total_value",
                    filters={
                        "game_id": f"in.({id_list})",
                        "sportsbook": "eq.pinnacle",
                    },
                )
                for s in snaps:
                    gid = s["game_id"]
                    pinnacle_data.setdefault(gid, {})
                    mt = s.get("market_type", "")
                    if mt == "spreads" and s.get("spread_value") is not None:
                        pinnacle_data[gid]["spread_home"] = s["spread_value"]
                    elif mt == "totals" and s.get("total_value") is not None:
                        pinnacle_data[gid]["total"] = s["total_value"]
                    elif mt == "h2h":
                        pinnacle_data[gid]["home_ml"] = s.get("home_odds")
                        pinnacle_data[gid]["away_ml"] = s.get("away_odds")
                        if s.get("home_odds"):
                            from models.ev_calculator import american_to_implied_prob
                            pinnacle_data[gid]["home_implied_prob"] = american_to_implied_prob(s["home_odds"])
            except Exception:
                pass

        # Build and save snapshots.
        rows: list[dict] = []
        for g in new_games:
            gid = g["game_id"]
            proj = kp_projections.get(gid)
            pin = pinnacle_data.get(gid, {})
            if not proj:
                continue

            kp_home = proj.get("home_score") or proj.get("home_pred", 0)
            kp_away = proj.get("away_score") or proj.get("away_pred", 0)
            kp_wp = proj.get("home_win_prob") or proj.get("home_wp", 0.5)
            kp_total = kp_home + kp_away
            kp_spread = kp_home - kp_away

            pin_spread = pin.get("spread_home")
            pin_total = pin.get("total")
            pin_home_ml = pin.get("home_ml")
            pin_away_ml = pin.get("away_ml")
            pin_home_ip = pin.get("home_implied_prob")

            spread_edge = (kp_spread - pin_spread) if pin_spread is not None else None
            total_edge = (kp_total - pin_total) if pin_total is not None else None
            ml_edge = (kp_wp - pin_home_ip) if pin_home_ip is not None else None

            row: dict = {
                "snapshot_date": target_str,
                "game_id": gid,
                "sport": "basketball_ncaab",
                "home_team": g["home_team"],
                "away_team": g["away_team"],
                "commence_time": g.get("start_time"),
                "kp_home_score": round(kp_home, 1),
                "kp_away_score": round(kp_away, 1),
                "kp_home_win_prob": round(kp_wp, 4),
                "kp_projected_total": round(kp_total, 1),
                "kp_projected_spread": round(kp_spread, 1),
                "pinnacle_spread_home": pin_spread,
                "pinnacle_total": pin_total,
                "pinnacle_home_ml": int(pin_home_ml) if pin_home_ml else None,
                "pinnacle_away_ml": int(pin_away_ml) if pin_away_ml else None,
                "pinnacle_home_implied_prob": round(pin_home_ip, 4) if pin_home_ip else None,
                "spread_edge": round(spread_edge, 2) if spread_edge is not None else None,
                "total_edge": round(total_edge, 2) if total_edge is not None else None,
                "ml_edge": round(ml_edge, 4) if ml_edge is not None else None,
            }

            # Grade if we have final scores.
            if g.get("status") == "final" and g.get("home_score") is not None:
                hs = int(g["home_score"])
                aws = int(g["away_score"])
                actual_spread = hs - aws
                actual_total = hs + aws

                row["result_home_score"] = hs
                row["result_away_score"] = aws
                row["graded"] = True

                if spread_edge is not None and pin_spread is not None and spread_edge != 0:
                    ats_margin = actual_spread + pin_spread
                    if ats_margin == 0:
                        row["result_spread_correct"] = None  # push
                    elif spread_edge > 0:
                        row["result_spread_correct"] = ats_margin > 0
                    else:
                        row["result_spread_correct"] = ats_margin < 0

                if total_edge is not None and pin_total is not None and total_edge != 0:
                    if total_edge > 0:
                        row["result_total_correct"] = actual_total > pin_total
                    else:
                        row["result_total_correct"] = actual_total < pin_total
                    if actual_total == pin_total:
                        row["result_total_correct"] = None

                if kp_wp and kp_wp != 0.5:
                    if kp_wp > 0.5:
                        row["result_ml_correct"] = actual_spread > 0
                    else:
                        row["result_ml_correct"] = actual_spread < 0
                    if actual_spread == 0:
                        row["result_ml_correct"] = None

                total_graded += 1

            rows.append(row)

        if rows:
            try:
                db._upsert_many(
                    "kenpom_snapshots", rows, on_conflict="snapshot_date,game_id"
                )
                total_saved += len(rows)
                days_processed += 1
                print(f"  {target_str}: {len(rows)} snapshots saved")
            except Exception as e:
                print(f"  {target_str}: failed ({e})")

    print(
        f"\nBackfill complete: {days_processed} days, {total_saved} total games, "
        f"{total_graded} graded"
    )


if __name__ == "__main__":
    main()
