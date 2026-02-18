#!/usr/bin/env python3
"""Backfill and repair KenPom snapshots.

Two modes:
  1. REPAIR: Fix spread_edge sign convention and add projection_source for
     existing snapshots in the DB.
  2. BACKFILL: Create new snapshots for historical dates from games table +
     KenPom fanmatch + Pinnacle odds (from line_movements table).

Safe to run multiple times (idempotent).

Usage:
    python scripts/backfill_kenpom_history.py                # repair + backfill last 30 days
    python scripts/backfill_kenpom_history.py --full          # repair + full season backfill (Nov 2025)
    python scripts/backfill_kenpom_history.py --days 7        # repair + backfill last 7 days
    python scripts/backfill_kenpom_history.py --start-date 2025-12-01  # custom start date
    python scripts/backfill_kenpom_history.py --repair-only   # only fix existing data
    python scripts/backfill_kenpom_history.py --dry-run       # show what would change
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "shared"))

from datetime import date, datetime, timedelta, timezone

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

# CBB season start date — first games of the 2025-26 season.
CBB_SEASON_START = date(2025, 11, 1)


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


def _fetch_pinnacle_from_line_movements(
    db,
    game_ids: list[str],
    home_team_by_gid: dict[str, str],
) -> dict[str, dict]:
    """Fetch latest Pinnacle odds from the line_movements table.

    Uses the most recent line movement per game/market for Pinnacle.
    Properly identifies home vs away sides using the home_team mapping.

    Returns {game_id: {spread_home, total, home_ml, away_ml, home_implied_prob}}.
    """
    from models.ev_calculator import american_to_implied_prob

    pin_data: dict[str, dict] = {}
    for i in range(0, len(game_ids), 50):
        chunk = game_ids[i : i + 50]
        id_list = ",".join(chunk)
        try:
            rows = db._get(
                "line_movements",
                select="game_id,market_type,side,odds",
                filters={
                    "game_id": f"in.({id_list})",
                    "bookmaker": "eq.pinnacle",
                },
                order="timestamp.desc",
            )
        except Exception:
            continue

        for row in rows:
            gid = row["game_id"]
            pin_data.setdefault(gid, {})
            d = pin_data[gid]
            mkt = row.get("market_type", "")
            side = row.get("side", "")
            odds = row.get("odds")
            if odds is None:
                continue

            home_team = home_team_by_gid.get(gid, "")

            if mkt == "spreads" and "spread_home" not in d:
                # side format: "Team Name -5.5"
                parts = side.rsplit(" ", 1)
                if len(parts) == 2:
                    team_name = parts[0]
                    try:
                        spread_val = float(parts[1])
                    except ValueError:
                        continue
                    if team_name == home_team:
                        d["spread_home"] = spread_val
                    else:
                        # Away team spread — negate to get home spread.
                        d["spread_home"] = -spread_val

            elif mkt == "totals" and "total" not in d:
                if side.lower().startswith("over"):
                    parts = side.rsplit(" ", 1)
                    if len(parts) == 2:
                        try:
                            d["total"] = float(parts[1])
                        except ValueError:
                            pass

            elif mkt == "h2h":
                if side == home_team and "home_ml" not in d:
                    d["home_ml"] = int(odds)
                    d["home_implied_prob"] = american_to_implied_prob(int(odds))
                elif side != home_team and "away_ml" not in d:
                    d["away_ml"] = int(odds)

    return pin_data


def backfill_new_snapshots(
    db,
    start_date: date,
    dry_run: bool = False,
) -> tuple[int, int]:
    """Backfill KenPom snapshots for historical dates.

    Uses KenPom fanmatch API (only — no ratings fallback) for each past
    date, plus Pinnacle odds from the line_movements table.  Grades
    against final scores from the games table.

    Returns (total_saved, total_graded).
    """
    from models.ev_calculator import american_to_implied_prob

    today = date.today()
    total_days = (today - start_date).days
    print(f"\n=== BACKFILLING NEW SNAPSHOTS ({start_date} to {today}, {total_days} days) ===\n")

    total_saved = 0
    total_graded = 0
    days_processed = 0

    # Track skipped dates for summary.
    dates_no_games: list[str] = []
    dates_no_fanmatch: list[str] = []
    dates_no_pinnacle: list[str] = []
    games_missing_pinnacle: int = 0

    target_date = start_date
    while target_date <= today:
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
            target_date += timedelta(days=1)
            continue

        if not games:
            target_date += timedelta(days=1)
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
            target_date += timedelta(days=1)
            continue

        # Fetch KenPom fanmatch for this specific date (fanmatch only, no
        # ratings fallback — ratings reflect current state, not historical).
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
            # Teams + name map needed for team name resolution.
            kp.fetch_teams()
            kp.build_name_map(teams)

            for g in new_games:
                # Use get_fanmatch_prediction (NOT get_projection) to ensure
                # we only use fanmatch data.  Ratings-based fallback would use
                # current-day ratings which are invalid for historical dates.
                proj = kp.get_fanmatch_prediction(g["home_team"], g["away_team"])
                if proj:
                    kp_projections[g["game_id"]] = proj
        except Exception as e:
            print(f"  {target_str}: KenPom fetch failed ({e})")
            dates_no_fanmatch.append(target_str)
            target_date += timedelta(days=1)
            continue

        if not kp_projections:
            dates_no_fanmatch.append(target_str)
            target_date += timedelta(days=1)
            continue

        # Get Pinnacle odds from line_movements table.
        home_team_by_gid = {g["game_id"]: g["home_team"] for g in games}
        pinnacle_data = _fetch_pinnacle_from_line_movements(db, game_ids, home_team_by_gid)

        # Track which games on this date have no Pinnacle data.
        games_without_pin_today = 0
        for gid in kp_projections:
            if gid not in pinnacle_data or not pinnacle_data[gid]:
                games_without_pin_today += 1

        if games_without_pin_today > 0:
            games_missing_pinnacle += games_without_pin_today
            if games_without_pin_today == len(kp_projections):
                # ALL games on this date are missing Pinnacle — log prominently.
                dates_no_pinnacle.append(target_str)
                print(
                    f"  {target_str}: SKIPPED — {games_without_pin_today}/{len(kp_projections)} games "
                    f"have no Pinnacle odds in line_movements"
                )

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
                pin_count = sum(1 for r in rows if r.get("pinnacle_spread_home") is not None)
                print(
                    f"  {target_str}: {len(rows)} snapshots saved "
                    f"({src_str}, {pin_count}/{len(rows)} with Pinnacle)"
                )
            except Exception as e:
                print(f"  {target_str}: save failed ({e})")
        elif rows:
            pin_count = sum(1 for r in rows if r.get("pinnacle_spread_home") is not None)
            print(
                f"  [DRY RUN] {target_str}: would save {len(rows)} snapshots "
                f"({pin_count}/{len(rows)} with Pinnacle)"
            )

        target_date += timedelta(days=1)

    # Print backfill summary.
    prefix = "[DRY RUN] " if dry_run else ""
    print(f"\n  {prefix}Backfill: {days_processed} days, {total_saved} saved, {total_graded} graded.")

    # Print skipped-dates summary.
    if dates_no_fanmatch or dates_no_pinnacle or games_missing_pinnacle:
        print(f"\n  --- Skipped / Missing Data Summary ---")
        if dates_no_fanmatch:
            print(f"  Dates with no KenPom fanmatch data ({len(dates_no_fanmatch)}):")
            for d in dates_no_fanmatch[:20]:
                print(f"    {d}")
            if len(dates_no_fanmatch) > 20:
                print(f"    ... and {len(dates_no_fanmatch) - 20} more")
        if dates_no_pinnacle:
            print(f"  Dates with NO Pinnacle data in line_movements ({len(dates_no_pinnacle)}):")
            for d in dates_no_pinnacle[:20]:
                print(f"    {d}")
            if len(dates_no_pinnacle) > 20:
                print(f"    ... and {len(dates_no_pinnacle) - 20} more")
        if games_missing_pinnacle:
            print(f"  Total individual games missing Pinnacle odds: {games_missing_pinnacle}")
            print(
                f"  (These snapshots were saved with NULL Pinnacle/edge fields. "
                f"They'll be updated if Pinnacle data becomes available.)"
            )

    return total_saved, total_graded


def backfill_pinnacle_odds_history(db) -> None:
    """Backfill pinnacle_odds_history from existing line_movements data.

    Finds all CBB games in the games table and populates opening/closing
    Pinnacle snapshots from historical line_movements rows.
    """
    print("\n=== BACKFILLING PINNACLE ODDS HISTORY ===\n")

    try:
        games = db._get(
            "games",
            select="game_id,sport,home_team,away_team,start_time",
            filters={"sport": "eq.basketball_ncaab"},
        )
    except Exception as e:
        print(f"  Failed to fetch games: {e}")
        return

    if not games:
        print("  No CBB games in database.")
        return

    game_ids = [g["game_id"] for g in games]
    home_team_by_gid = {g["game_id"]: g["home_team"] for g in games}
    game_info = {
        g["game_id"]: {
            "sport": g["sport"],
            "home_team": g["home_team"],
            "away_team": g["away_team"],
            "start_time": g.get("start_time"),
        }
        for g in games
    }

    try:
        from intelligence.pinnacle_history import backfill_from_line_movements

        opening, closing = backfill_from_line_movements(
            db, game_ids, home_team_by_gid, game_info
        )
        print(
            f"  Pinnacle history backfill: {opening} opening lines, "
            f"{closing} closing lines from {len(game_ids)} games."
        )
    except Exception as e:
        print(f"  Pinnacle history backfill failed: {e}")


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
            f"\n  Season record ({len(graded)} graded games):"
        )
        print(f"    Spread ATS: {sw}-{sl} ({sp})")
        print(f"    Totals O/U: {tw}-{tl} ({tp})")
        print(f"    Moneyline:  {mw}-{ml_} ({mp})")
    else:
        print("\n  No graded snapshots yet.")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Backfill and repair KenPom snapshots")
    parser.add_argument("--days", type=int, default=30, help="Days to look back for backfill (default: 30)")
    parser.add_argument(
        "--full", action="store_true",
        help="Full season backfill starting from November 2025",
    )
    parser.add_argument(
        "--start-date", type=str, default=None,
        help="Custom start date for backfill (YYYY-MM-DD format)",
    )
    parser.add_argument("--repair-only", action="store_true", help="Only repair existing data")
    parser.add_argument("--dry-run", action="store_true", help="Show plan without changing data")
    args = parser.parse_args()

    from db import get_supabase

    db = get_supabase()

    # Step 1: Always repair existing data first.
    repaired = repair_existing_snapshots(db, dry_run=args.dry_run)

    # Step 2: Backfill new snapshots (unless repair-only).
    if not args.repair_only:
        # Determine start date.
        if args.start_date:
            start = date.fromisoformat(args.start_date)
        elif args.full:
            start = CBB_SEASON_START
        else:
            start = date.today() - timedelta(days=args.days)

        saved, graded = backfill_new_snapshots(db, start, dry_run=args.dry_run)
    else:
        print("\n  --repair-only: Skipping backfill.")

    # Step 3: Backfill Pinnacle odds history from line_movements.
    if not args.repair_only and not args.dry_run:
        backfill_pinnacle_odds_history(db)

    # Step 4: Print verification summary.
    if not args.dry_run:
        print_verification_summary(db)

    print("\nDone.")


if __name__ == "__main__":
    main()
