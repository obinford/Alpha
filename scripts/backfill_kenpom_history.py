#!/usr/bin/env python3
"""Backfill and repair KenPom snapshots.

Two modes:
  1. REPAIR: Fix spread_edge sign convention and add projection_source for
     existing snapshots in the DB.
  2. BACKFILL: Create new snapshots for historical dates from games table +
     KenPom fanmatch + Pinnacle odds.

Safe to run multiple times (idempotent).

Usage:
    python scripts/backfill_kenpom_history.py                # repair + backfill last 30 days
    python scripts/backfill_kenpom_history.py --days 7       # repair + backfill last 7 days
    python scripts/backfill_kenpom_history.py --repair-only  # only fix existing data
    python scripts/backfill_kenpom_history.py --dry-run      # show what would change
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "shared"))

from datetime import date, datetime, timedelta, timezone

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))


def repair_existing_snapshots(db, dry_run: bool = False) -> int:
    """Repair spread_edge sign convention for all existing snapshots.

    The old formula was: spread_edge = kp_projected_spread - pinnacle_spread_home
    The correct formula: spread_edge = kp_projected_spread + pinnacle_spread_home

    Because kp_projected_spread uses margin convention (positive = home scores more)
    while pinnacle_spread_home uses betting convention (negative = home favored).

    Also re-grades spread_correct based on the corrected spread_edge.
    """
    print("\n=== REPAIRING EXISTING SNAPSHOTS ===\n")

    try:
        all_rows = db._get(
            "kenpom_snapshots",
            select="id,game_id,snapshot_date,kp_projected_spread,kp_projected_total,"
                   "kp_home_win_prob,pinnacle_spread_home,pinnacle_total,"
                   "pinnacle_home_implied_prob,spread_edge,total_edge,ml_edge,"
                   "result_home_score,result_away_score,graded,projection_source",
        )
    except Exception as e:
        print(f"  Failed to fetch snapshots: {e}")
        return 0

    if not all_rows:
        print("  No existing snapshots to repair.")
        return 0

    print(f"  Found {len(all_rows)} existing snapshots.")

    repaired = 0
    regrade_count = 0
    sample_fixes = []

    for row in all_rows:
        row_id = row.get("id")
        if not row_id:
            continue

        kp_spread = row.get("kp_projected_spread")
        pin_spread = row.get("pinnacle_spread_home")
        old_spread_edge = row.get("spread_edge")

        if kp_spread is None or pin_spread is None:
            continue

        # Correct formula: kp_spread + pin_spread (opposite sign conventions)
        new_spread_edge = round(kp_spread + pin_spread, 2)

        # Check if it actually needs repair.
        if old_spread_edge is not None and abs(old_spread_edge - new_spread_edge) < 0.01:
            continue

        update: dict = {
            "spread_edge": new_spread_edge,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

        # Re-grade spread_correct if the game is graded and has scores.
        if row.get("graded") and row.get("result_home_score") is not None:
            hs = int(row["result_home_score"])
            aws = int(row["result_away_score"])
            actual_spread = hs - aws
            ats_margin = actual_spread + pin_spread

            if new_spread_edge != 0 and ats_margin != 0:
                if new_spread_edge > 0:
                    update["result_spread_correct"] = ats_margin > 0
                else:
                    update["result_spread_correct"] = ats_margin < 0
                regrade_count += 1

        # Collect a few samples for the summary.
        if len(sample_fixes) < 5:
            sample_fixes.append({
                "game_id": row.get("game_id", "?")[:30],
                "date": row.get("snapshot_date", "?"),
                "kp_spread": kp_spread,
                "pin_spread": pin_spread,
                "old_edge": old_spread_edge,
                "new_edge": new_spread_edge,
            })

        if not dry_run:
            try:
                db._http.patch(
                    f"{db.base_url}/kenpom_snapshots",
                    headers={**db.headers, "Prefer": "return=minimal"},
                    params={"id": f"eq.{row_id}"},
                    json=update,
                    timeout=15,
                )
            except Exception as e:
                print(f"  PATCH failed for {row_id}: {e}")
                continue

        repaired += 1

    # Print sample fixes.
    if sample_fixes:
        print(f"\n  Sample fixes (first {len(sample_fixes)}):")
        for s in sample_fixes:
            print(
                f"    {s['date']} | {s['game_id']:<30} | "
                f"KP={s['kp_spread']:+.1f} PIN={s['pin_spread']:+.1f} | "
                f"OLD edge={s['old_edge']} -> NEW edge={s['new_edge']:+.1f}"
            )

    prefix = "[DRY RUN] " if dry_run else ""
    print(f"\n  {prefix}Repaired {repaired} snapshots, re-graded {regrade_count}.")
    return repaired


def backfill_new_snapshots(db, days: int, dry_run: bool = False) -> tuple[int, int]:
    """Backfill KenPom snapshots for historical dates.

    Uses KenPom fanmatch API for the actual game date, plus Pinnacle odds
    from odds_snapshots table. Grades against final scores.

    Returns (total_saved, total_graded).
    """
    print(f"\n=== BACKFILLING NEW SNAPSHOTS (last {days} days) ===\n")

    from models.ev_calculator import american_to_implied_prob

    today = date.today()
    total_saved = 0
    total_graded = 0
    days_processed = 0

    for days_ago in range(days, -1, -1):
        target_date = today - timedelta(days=days_ago)
        target_str = target_date.isoformat()

        # Get CBB games for this date.
        try:
            games = db._get(
                "games",
                select="game_id,sport,home_team,away_team,start_time,status,home_score,away_score",
                filters={
                    "sport": "eq.basketball_ncaab",
                    "start_time": f"gte.{target_str}T00:00:00Z",
                },
            )
            games = [g for g in games if g.get("start_time", "")[:10] == target_str]
        except Exception:
            continue

        if not games:
            continue

        # Check which already have snapshots.
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

        # Fetch KenPom fanmatch for this specific date.
        kp_projections: dict[str, dict] = {}
        try:
            from intelligence.kenpom import KenPomClient, fetch_fanmatch

            teams = []
            for g in new_games:
                if g["home_team"] not in teams:
                    teams.append(g["home_team"])
                if g["away_team"] not in teams:
                    teams.append(g["away_team"])

            kp = KenPomClient(odds_api_teams=teams)

            # Fetch fanmatch for the specific historical date (populates cache).
            fetch_fanmatch(target_date)
            # Also ensure ratings and name map are loaded.
            kp.fetch_ratings()
            kp.fetch_teams()
            kp.build_name_map(teams)

            for g in new_games:
                proj = kp.get_projection(g["home_team"], g["away_team"])
                if proj:
                    kp_projections[g["game_id"]] = proj
        except Exception as e:
            print(f"  {target_str}: KenPom fetch failed ({e})")
            continue

        if not kp_projections:
            continue

        # Get Pinnacle odds from odds_snapshots.
        pinnacle_data: dict[str, dict] = {}
        for i in range(0, len(game_ids), 50):
            chunk = game_ids[i : i + 50]
            id_list = ",".join(chunk)
            try:
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
                            pinnacle_data[gid]["home_implied_prob"] = american_to_implied_prob(s["home_odds"])
            except Exception:
                pass

        # Build snapshot rows.
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

            # CORRECT formula: kp_spread + pin_spread (opposite sign conventions)
            spread_edge = (kp_spread + pin_spread) if pin_spread is not None else None
            total_edge = (kp_total - pin_total) if pin_total is not None else None
            ml_edge = (kp_wp - pin_home_ip) if pin_home_ip is not None else None

            source = proj.get("source", "unknown")

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
                "projection_source": source,
            }

            # Grade if final scores exist.
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
                        row["result_spread_correct"] = None
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

        if rows and not dry_run:
            try:
                db._upsert_many(
                    "kenpom_snapshots", rows, on_conflict="snapshot_date,game_id"
                )
                total_saved += len(rows)
                days_processed += 1
                source_counts: dict[str, int] = {}
                for r in rows:
                    src = r.get("projection_source", "unknown")
                    source_counts[src] = source_counts.get(src, 0) + 1
                src_str = ", ".join(f"{k}={v}" for k, v in source_counts.items())
                print(f"  {target_str}: {len(rows)} snapshots saved ({src_str})")
            except Exception as e:
                print(f"  {target_str}: save failed ({e})")
        elif rows:
            print(f"  [DRY RUN] {target_str}: would save {len(rows)} snapshots")

    prefix = "[DRY RUN] " if dry_run else ""
    print(f"\n  {prefix}Backfill: {days_processed} days, {total_saved} saved, {total_graded} graded.")
    return total_saved, total_graded


def print_verification_summary(db) -> None:
    """Print a summary of snapshot data for verification."""
    print("\n=== VERIFICATION SUMMARY ===\n")

    try:
        all_rows = db._get(
            "kenpom_snapshots",
            select="snapshot_date,kp_projected_spread,kp_projected_total,"
                   "pinnacle_spread_home,pinnacle_total,spread_edge,total_edge,"
                   "home_team,away_team,projection_source,graded,"
                   "result_spread_correct,result_total_correct,result_ml_correct",
        )
    except Exception as e:
        print(f"  Query failed: {e}")
        return

    if not all_rows:
        print("  No snapshots in database.")
        return

    print(f"  Total snapshots: {len(all_rows)}")

    # Source breakdown.
    sources: dict[str, int] = {}
    for r in all_rows:
        src = r.get("projection_source") or "unknown"
        sources[src] = sources.get(src, 0) + 1
    print(f"  Sources: {sources}")

    # Verify spread_edge formula on a few samples.
    print("\n  Spot-check (spread_edge = kp_spread + pin_spread):")
    samples = [r for r in all_rows if r.get("pinnacle_spread_home") is not None][:5]
    for s in samples:
        kp_sp = s.get("kp_projected_spread", 0)
        pin_sp = s.get("pinnacle_spread_home", 0)
        stored_edge = s.get("spread_edge")
        expected = round(kp_sp + pin_sp, 2)
        match = "OK" if stored_edge is not None and abs(stored_edge - expected) < 0.01 else "MISMATCH"
        print(
            f"    {s.get('away_team', '?')[:20]} @ {s.get('home_team', '?')[:20]} | "
            f"KP={kp_sp:+.1f} PIN={pin_sp:+.1f} | "
            f"edge={stored_edge} (expected {expected:+.1f}) [{match}]"
        )

    # Grading summary.
    graded = [r for r in all_rows if r.get("graded")]
    if graded:
        sw = sum(1 for r in graded if r.get("result_spread_correct") is True)
        sl = sum(1 for r in graded if r.get("result_spread_correct") is False)
        tw = sum(1 for r in graded if r.get("result_total_correct") is True)
        tl = sum(1 for r in graded if r.get("result_total_correct") is False)
        mw = sum(1 for r in graded if r.get("result_ml_correct") is True)
        ml_ = sum(1 for r in graded if r.get("result_ml_correct") is False)
        sp = f"{sw / (sw + sl) * 100:.1f}%" if (sw + sl) > 0 else "N/A"
        tp = f"{tw / (tw + tl) * 100:.1f}%" if (tw + tl) > 0 else "N/A"
        mp = f"{mw / (mw + ml_) * 100:.1f}%" if (mw + ml_) > 0 else "N/A"
        print(
            f"\n  Graded: {len(graded)} games | "
            f"Spread: {sw}-{sl} ({sp}), Total: {tw}-{tl} ({tp}), ML: {mw}-{ml_} ({mp})"
        )
    else:
        print("\n  No graded snapshots yet.")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Backfill and repair KenPom snapshots")
    parser.add_argument("--days", type=int, default=30, help="Days to look back for backfill")
    parser.add_argument("--repair-only", action="store_true", help="Only repair existing data")
    parser.add_argument("--dry-run", action="store_true", help="Show plan without changing data")
    args = parser.parse_args()

    from db import get_supabase

    db = get_supabase()

    # Step 1: Always repair existing data first.
    repaired = repair_existing_snapshots(db, dry_run=args.dry_run)

    # Step 2: Backfill new snapshots (unless repair-only).
    if not args.repair_only:
        saved, graded = backfill_new_snapshots(db, args.days, dry_run=args.dry_run)
    else:
        print("\n  --repair-only: Skipping backfill.")

    # Step 3: Print verification summary.
    if not args.dry_run:
        print_verification_summary(db)

    print("\nDone.")


if __name__ == "__main__":
    main()
