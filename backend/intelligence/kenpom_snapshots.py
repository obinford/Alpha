"""KenPom snapshot storage and grading.

Persists daily KenPom projections alongside Pinnacle odds so we can
track edge accuracy over time.  Called from the scanner after KenPom
projections and Pinnacle odds are loaded.

Grading is run when final scores arrive — compares KenPom's edges
against actual results.

Edge sign conventions:
    spread_edge = kp_projected_spread - pinnacle_spread_home
        positive → KP sees more home advantage than Pinnacle
    total_edge = kp_projected_total - pinnacle_total
        positive → KP projects higher scoring than Pinnacle
    ml_edge = kp_home_win_prob - pinnacle_home_implied_prob
        positive → KP more bullish on home than Pinnacle

ATS grading formula:
    ats_margin = actual_spread + pinnacle_spread_home
    ats_margin > 0 → home covers
    ats_margin < 0 → away covers
    ats_margin == 0 → push
"""

from __future__ import annotations

import os
import time
from datetime import date, datetime, timezone
from typing import Any

from models.ev_calculator import american_to_implied_prob

# ---------------------------------------------------------------------------
# Auto-table creation
# ---------------------------------------------------------------------------

_TABLE_VERIFIED = False

_CREATE_TABLE_DDL = [
    """CREATE TABLE IF NOT EXISTS kenpom_snapshots (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    snapshot_date DATE NOT NULL,
    game_id TEXT NOT NULL,
    sport TEXT DEFAULT 'basketball_ncaab',
    home_team TEXT NOT NULL,
    away_team TEXT NOT NULL,
    commence_time TIMESTAMPTZ,
    kp_home_score REAL,
    kp_away_score REAL,
    kp_home_win_prob REAL,
    kp_projected_total REAL,
    kp_projected_spread REAL,
    pinnacle_spread_home REAL,
    pinnacle_total REAL,
    pinnacle_home_ml INTEGER,
    pinnacle_away_ml INTEGER,
    pinnacle_home_implied_prob REAL,
    spread_edge REAL,
    total_edge REAL,
    ml_edge REAL,
    result_home_score INTEGER,
    result_away_score INTEGER,
    result_spread_correct BOOLEAN,
    result_total_correct BOOLEAN,
    result_ml_correct BOOLEAN,
    graded BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(snapshot_date, game_id)
)""",
    "CREATE INDEX IF NOT EXISTS idx_kenpom_snapshots_date ON kenpom_snapshots(snapshot_date DESC)",
    "CREATE INDEX IF NOT EXISTS idx_kenpom_snapshots_game ON kenpom_snapshots(game_id)",
    "CREATE INDEX IF NOT EXISTS idx_kenpom_snapshots_graded ON kenpom_snapshots(graded)",
]


def _ensure_table(db_client: Any) -> bool:
    """Verify kenpom_snapshots table exists; auto-create if missing.

    Uses a module-level flag so we only probe once per process lifetime.
    Returns True if the table is ready, False otherwise.
    """
    global _TABLE_VERIFIED
    if _TABLE_VERIFIED:
        return True

    # Probe: try a lightweight query.
    try:
        db_client._get("kenpom_snapshots", select="id", limit=1)
        _TABLE_VERIFIED = True
        return True
    except Exception as probe_err:
        err_str = str(probe_err).lower()
        # If it's not a "table missing" error, assume the table exists
        # but there's some transient issue.
        if "does not exist" not in err_str and "relation" not in err_str and "404" not in err_str:
            print(f"  [KENPOM SNAPSHOT] Probe query failed (non-fatal): {probe_err}")
            _TABLE_VERIFIED = True
            return True

    # Table missing — attempt auto-creation via the Supabase SDK.
    print("  [KENPOM SNAPSHOT] Table 'kenpom_snapshots' not found — auto-creating...")
    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        print(
            "  [KENPOM SNAPSHOT] ERROR: Cannot auto-create table — "
            "SUPABASE_URL and SUPABASE_SERVICE_KEY env vars required. "
            "Run: python scripts/create_kenpom_table.py"
        )
        return False

    try:
        from supabase import create_client
        sdk_client = create_client(url, key)
        for i, ddl in enumerate(_CREATE_TABLE_DDL, 1):
            preview = ddl[:80].replace("\n", " ")
            print(f"    [{i}/{len(_CREATE_TABLE_DDL)}] {preview}...")
            try:
                sdk_client.postgrest.rpc("exec_sql", {"query": ddl}).execute()
            except Exception as stmt_err:
                if "already exists" in str(stmt_err).lower():
                    print(f"    (already exists, OK)")
                else:
                    raise stmt_err
        _TABLE_VERIFIED = True
        print("  [KENPOM SNAPSHOT] Table created successfully.")
        return True
    except Exception as e:
        print(
            f"  [KENPOM SNAPSHOT] ERROR: Auto-create failed: {e}\n"
            f"  → Create the table manually: run 'python scripts/create_kenpom_table.py'\n"
            f"  → Or paste scripts/008_kenpom_snapshots.sql into the Supabase SQL Editor."
        )
        return False


# ---------------------------------------------------------------------------
# Pinnacle odds extraction
# ---------------------------------------------------------------------------

def _extract_pinnacle_odds(game: Any) -> dict[str, Any] | None:
    """Extract Pinnacle's spread, total, and ML from a game's bookmakers.

    Args:
        game: Game object from odds_api (has .bookmakers list).

    Returns dict with keys:
        spread_home: float (e.g. -5.5)
        total: float (e.g. 148.5)
        home_ml: int (e.g. -200)
        away_ml: int (e.g. +170)
        home_implied_prob: float (0-1)
    Or None if Pinnacle is not present.
    """
    pin_bk = None
    for bk in game.bookmakers:
        if bk.key == "pinnacle":
            pin_bk = bk
            break
    if pin_bk is None:
        return None

    result: dict[str, Any] = {}
    home_team = game.home_team

    for mkt in pin_bk.markets:
        if mkt.key == "spreads" and len(mkt.outcomes) == 2:
            for o in mkt.outcomes:
                if o.name == home_team:
                    result["spread_home"] = o.point
                    break
            # Fallback: first outcome with negative point is usually home fav
            if "spread_home" not in result:
                result["spread_home"] = mkt.outcomes[0].point

        elif mkt.key == "totals" and len(mkt.outcomes) == 2:
            for o in mkt.outcomes:
                if o.name == "Over":
                    result["total"] = o.point
                    break

        elif mkt.key == "h2h" and len(mkt.outcomes) == 2:
            for o in mkt.outcomes:
                if o.name == home_team:
                    result["home_ml"] = o.price
                    result["home_implied_prob"] = american_to_implied_prob(o.price)
                else:
                    result["away_ml"] = o.price

    # Must have at least spread OR total to be useful.
    if "spread_home" not in result and "total" not in result:
        return None
    return result


# ---------------------------------------------------------------------------
# Snapshot persistence
# ---------------------------------------------------------------------------

def save_kenpom_snapshots(
    db_client: Any,
    game_projections: dict[str, dict],
    all_games: list[Any],
    snapshot_dt: date | None = None,
) -> int:
    """Persist daily KenPom projections + Pinnacle odds as snapshots.

    Only saves once per day per game (uses upsert on snapshot_date+game_id).

    Args:
        db_client: Supabase client.
        game_projections: dict of game_id -> KenPom projection dict.
        all_games: list of Game objects (has bookmakers with Pinnacle).
        snapshot_dt: Override snapshot date (defaults to today UTC).

    Returns number of snapshots saved.
    """
    print(
        f"  [KENPOM SNAPSHOT] Starting snapshot save... "
        f"({len(game_projections)} KP projections, {len(all_games)} total games)"
    )

    if not db_client or not game_projections:
        print("  [KENPOM SNAPSHOT] Skipped — no DB client or no projections.")
        return 0

    # Ensure table exists (auto-create on first run).
    if not _ensure_table(db_client):
        print("  [KENPOM SNAPSHOT] Aborted — table does not exist.")
        return 0

    t0 = time.time()
    today = snapshot_dt or date.today()
    today_str = today.isoformat()

    # Check which games already have snapshots for today.
    game_ids = list(game_projections.keys())
    existing_ids: set[str] = set()
    for i in range(0, len(game_ids), 50):
        chunk = game_ids[i : i + 50]
        id_list = ",".join(chunk)
        try:
            existing_rows = db_client._get(
                "kenpom_snapshots",
                select="game_id",
                filters={
                    "snapshot_date": f"eq.{today_str}",
                    "game_id": f"in.({id_list})",
                },
            )
            existing_ids.update(r["game_id"] for r in existing_rows)
        except Exception as e:
            print(f"  [KENPOM SNAPSHOT] Warning: existing-check failed ({e})")

    if existing_ids:
        print(f"  [KENPOM SNAPSHOT] {len(existing_ids)} games already have snapshots for {today_str}, skipping those.")

    # Build game lookup (CBB only).
    game_map = {g.id: g for g in all_games if g.sport_key == "basketball_ncaab"}
    print(f"  [KENPOM SNAPSHOT] {len(game_map)} CBB games in all_games.")

    rows: list[dict] = []
    pin_found = 0
    pin_missing = 0
    no_game = 0

    for game_id, proj in game_projections.items():
        if game_id in existing_ids:
            continue

        game = game_map.get(game_id)
        if game is None:
            no_game += 1
            continue

        # KenPom data.
        kp_home = proj.get("home_score") or proj.get("home_pred", 0)
        kp_away = proj.get("away_score") or proj.get("away_pred", 0)
        kp_wp = proj.get("home_win_prob") or proj.get("home_wp", 0.5)
        kp_total = kp_home + kp_away
        # Positive = home favored (home scores more).
        kp_spread = kp_home - kp_away

        # Pinnacle data.
        pin = _extract_pinnacle_odds(game)
        if pin:
            pin_found += 1
        else:
            pin_missing += 1
        pin_spread = pin.get("spread_home") if pin else None
        pin_total = pin.get("total") if pin else None
        pin_home_ml = pin.get("home_ml") if pin else None
        pin_away_ml = pin.get("away_ml") if pin else None
        pin_home_ip = pin.get("home_implied_prob") if pin else None

        # Edge calculations.
        spread_edge = (kp_spread - pin_spread) if pin_spread is not None else None
        total_edge = (kp_total - pin_total) if pin_total is not None else None
        ml_edge = (kp_wp - pin_home_ip) if pin_home_ip is not None else None

        # Debug first 3 games.
        if len(rows) < 3:
            ip_str = f"{pin_home_ip:.3f}" if pin_home_ip else "N/A"
            se_str = f"{spread_edge:+.1f}" if spread_edge is not None else "N/A"
            te_str = f", total={total_edge:+.1f}" if total_edge is not None else ""
            me_str = f", ml={ml_edge:+.3f}" if ml_edge is not None else ""
            print(
                f"  [KENPOM SNAPSHOT DEBUG {len(rows)+1}/3] "
                f"{game.away_team} @ {game.home_team} | "
                f"KP: {kp_away:.0f}-{kp_home:.0f} (spread={kp_spread:+.1f}, total={kp_total:.1f}, WP={kp_wp:.1%}) | "
                f"PIN: spread={pin_spread}, total={pin_total}, ML={pin_home_ml}/{pin_away_ml} (IP={ip_str}) | "
                f"Edges: spread={se_str}{te_str}{me_str}"
            )

        rows.append({
            "snapshot_date": today_str,
            "game_id": game_id,
            "sport": "basketball_ncaab",
            "home_team": game.home_team,
            "away_team": game.away_team,
            "commence_time": game.commence_time,
            "kp_home_score": round(kp_home, 1),
            "kp_away_score": round(kp_away, 1),
            "kp_home_win_prob": round(kp_wp, 4),
            "kp_projected_total": round(kp_total, 1),
            "kp_projected_spread": round(kp_spread, 1),
            "pinnacle_spread_home": pin_spread,
            "pinnacle_total": pin_total,
            "pinnacle_home_ml": int(pin_home_ml) if pin_home_ml is not None else None,
            "pinnacle_away_ml": int(pin_away_ml) if pin_away_ml is not None else None,
            "pinnacle_home_implied_prob": round(pin_home_ip, 4) if pin_home_ip else None,
            "spread_edge": round(spread_edge, 2) if spread_edge is not None else None,
            "total_edge": round(total_edge, 2) if total_edge is not None else None,
            "ml_edge": round(ml_edge, 4) if ml_edge is not None else None,
        })

    print(
        f"  [KENPOM SNAPSHOT] Found {len(game_projections)} games with KP data, "
        f"{pin_found} with Pinnacle odds, {pin_missing} without Pinnacle"
        + (f", {no_game} KP games not in all_games" if no_game else "")
        + (f", {len(existing_ids)} already saved" if existing_ids else "")
    )

    if not rows:
        print(f"  [KENPOM SNAPSHOT] Nothing new to save for {today_str}.")
        return 0

    try:
        db_client._upsert_many(
            "kenpom_snapshots", rows, on_conflict="snapshot_date,game_id"
        )
        elapsed = time.time() - t0
        print(
            f"  [KENPOM SNAPSHOT] Saved {len(rows)} snapshots for {today_str} ({elapsed:.1f}s)"
        )
        return len(rows)
    except Exception as e:
        err_str = str(e).lower()
        if "does not exist" in err_str or "relation" in err_str:
            print(
                f"  [KENPOM SNAPSHOT] ERROR: Table 'kenpom_snapshots' does not exist!\n"
                f"  → Run: python scripts/create_kenpom_table.py\n"
                f"  → Or paste scripts/008_kenpom_snapshots.sql into the Supabase SQL Editor."
            )
        else:
            print(f"  [KENPOM SNAPSHOT] ERROR: Save failed: {e}")
        return 0


# ---------------------------------------------------------------------------
# Grading
# ---------------------------------------------------------------------------

def grade_kenpom_snapshots(db_client: Any) -> dict[str, int]:
    """Grade ungraded KenPom snapshots against final game scores.

    Looks up final scores from the games table and evaluates:
    - result_spread_correct: Did KP's spread edge predict ATS correctly?
    - result_total_correct: Did KP's total edge predict O/U correctly?
    - result_ml_correct: Did KP's home win prob predict the winner?

    Returns dict with keys: graded, spread_wins, spread_losses,
    total_wins, total_losses, ml_wins, ml_losses.
    """
    result = {
        "graded": 0,
        "spread_wins": 0, "spread_losses": 0,
        "total_wins": 0, "total_losses": 0,
        "ml_wins": 0, "ml_losses": 0,
    }
    if db_client is None:
        return result

    # Ensure table exists before querying.
    if not _ensure_table(db_client):
        return result

    # Fetch ungraded snapshots.
    try:
        ungraded = db_client._get(
            "kenpom_snapshots",
            select="id,game_id,snapshot_date,kp_projected_spread,kp_projected_total,kp_home_win_prob,"
                   "pinnacle_spread_home,pinnacle_total,spread_edge,total_edge,ml_edge",
            filters={"graded": "eq.false"},
        )
    except Exception as e:
        print(f"  [KENPOM GRADING] Failed to fetch ungraded snapshots: {e}")
        return result

    if not ungraded:
        return result

    # Get game_ids for lookup.
    game_ids = list({s["game_id"] for s in ungraded})

    # Batch-fetch final scores.
    final_scores: dict[str, dict] = {}
    for i in range(0, len(game_ids), 50):
        chunk = game_ids[i : i + 50]
        id_list = ",".join(chunk)
        try:
            games = db_client._get(
                "games",
                select="game_id,home_score,away_score,status",
                filters={
                    "game_id": f"in.({id_list})",
                    "status": "eq.final",
                },
            )
            for g in games:
                if g.get("home_score") is not None and g.get("away_score") is not None:
                    final_scores[g["game_id"]] = g
        except Exception:
            pass

    if not final_scores:
        return result

    # Grade each snapshot.
    update_rows: list[dict] = []
    for snap in ungraded:
        gid = snap["game_id"]
        game = final_scores.get(gid)
        if game is None:
            continue

        home_score = int(game["home_score"])
        away_score = int(game["away_score"])
        actual_spread = home_score - away_score  # positive = home won
        actual_total = home_score + away_score

        pin_spread = snap.get("pinnacle_spread_home")
        pin_total = snap.get("pinnacle_total")
        spread_edge = snap.get("spread_edge")
        total_edge = snap.get("total_edge")
        kp_wp = snap.get("kp_home_win_prob")

        # Spread grading (ATS coverage).
        # ATS margin = actual_spread + pin_spread_home.  Positive → home covers.
        # Example: home -5.5, wins by 7 → 7 + (-5.5) = +1.5 → home covers.
        # Example: home -5.5, wins by 3 → 3 + (-5.5) = -2.5 → home doesn't cover.
        spread_correct = None
        if spread_edge is not None and pin_spread is not None and spread_edge != 0:
            ats_margin = actual_spread + pin_spread
            if ats_margin == 0:
                spread_correct = None  # push, don't count
            elif spread_edge > 0:
                # KP favors home more → take home ATS.
                spread_correct = ats_margin > 0
            else:
                # KP favors away more → take away ATS.
                spread_correct = ats_margin < 0

        # Total grading.
        total_correct = None
        if total_edge is not None and pin_total is not None and total_edge != 0:
            if total_edge > 0:
                # KP projects higher → take over.
                total_correct = actual_total > pin_total
            else:
                # KP projects lower → take under.
                total_correct = actual_total < pin_total
            if actual_total == pin_total:
                total_correct = None  # push

        # ML grading.
        ml_correct = None
        if kp_wp is not None and kp_wp != 0.5:
            if kp_wp > 0.5:
                ml_correct = actual_spread > 0  # home won
            else:
                ml_correct = actual_spread < 0  # away won
            if actual_spread == 0:
                ml_correct = None  # tie

        update_rows.append({
            "snapshot_date": snap.get("snapshot_date") or gid,
            "game_id": gid,
            "result_home_score": home_score,
            "result_away_score": away_score,
            "result_spread_correct": spread_correct,
            "result_total_correct": total_correct,
            "result_ml_correct": ml_correct,
            "graded": True,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })

        result["graded"] += 1
        if spread_correct is True:
            result["spread_wins"] += 1
        elif spread_correct is False:
            result["spread_losses"] += 1
        if total_correct is True:
            result["total_wins"] += 1
        elif total_correct is False:
            result["total_losses"] += 1
        if ml_correct is True:
            result["ml_wins"] += 1
        elif ml_correct is False:
            result["ml_losses"] += 1

    # Batch update.
    if update_rows:
        try:
            db_client._upsert_many(
                "kenpom_snapshots", update_rows, on_conflict="snapshot_date,game_id"
            )
        except Exception as e:
            print(f"  [KENPOM GRADING] Update failed: {e}")
            return result

    # Log summary.
    sw, sl = result["spread_wins"], result["spread_losses"]
    tw, tl = result["total_wins"], result["total_losses"]
    mw, ml_ = result["ml_wins"], result["ml_losses"]
    sp = f"{sw / (sw + sl) * 100:.0f}%" if (sw + sl) > 0 else "N/A"
    tp = f"{tw / (tw + tl) * 100:.0f}%" if (tw + tl) > 0 else "N/A"
    mp = f"{mw / (mw + ml_) * 100:.0f}%" if (mw + ml_) > 0 else "N/A"
    print(
        f"  [KENPOM GRADING] Graded {result['graded']} games — "
        f"Spread: {sw}-{sl} ({sp}), Total: {tw}-{tl} ({tp}), ML: {mw}-{ml_} ({mp})"
    )

    return result
