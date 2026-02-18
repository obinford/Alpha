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
import traceback
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from models.ev_calculator import american_to_implied_prob

# ---------------------------------------------------------------------------
# Table auto-creation via RPC — uses the same db_client the scanner uses.
# ---------------------------------------------------------------------------

_TABLE_VERIFIED = False

# Path to the migration SQL that defines kenpom_snapshots.
_SQL_PATH = Path(__file__).resolve().parent.parent.parent / "scripts" / "008_kenpom_snapshots.sql"


def _try_create_table_via_rpc(db_client: Any) -> bool:
    """Attempt to create kenpom_snapshots via PostgREST RPC exec_sql.

    Uses the same httpx client and service-role credentials that the scanner
    uses for ev_opportunities, signals, etc.  Requires an ``exec_sql(query)``
    Postgres function on the Supabase instance (common in many setups).

    Returns True if the table was successfully created (or already exists).
    """
    if not _SQL_PATH.exists():
        print(f"  [KENPOM SNAPSHOT] SQL migration not found at {_SQL_PATH}")
        return False

    sql_text = _SQL_PATH.read_text()
    statements = [
        s.strip()
        for s in sql_text.split(";")
        if s.strip() and not s.strip().startswith("--")
    ]
    if not statements:
        return False

    rpc_url = f"{db_client.base_url}/rpc/exec_sql"
    print(f"  [KENPOM SNAPSHOT] Attempting auto-create via RPC ({len(statements)} statements)...")

    for i, stmt in enumerate(statements, 1):
        preview = stmt[:80].replace("\n", " ")
        try:
            resp = db_client._http.post(
                rpc_url,
                headers=db_client.headers,
                json={"query": stmt},
                timeout=15,
            )
            if resp.status_code < 400:
                print(f"    [{i}/{len(statements)}] OK: {preview}")
                continue
            body = resp.text.lower()
            if "already exists" in body:
                print(f"    [{i}/{len(statements)}] Already exists (OK)")
                continue
            # RPC function doesn't exist or other error — bail out.
            print(f"    [{i}/{len(statements)}] Failed (HTTP {resp.status_code}): {resp.text[:200]}")
            return False
        except Exception as e:
            print(f"    [{i}/{len(statements)}] Exception: {e}")
            return False

    print("  [KENPOM SNAPSHOT] Table created successfully via RPC.")
    return True


def _ensure_table(db_client: Any) -> bool:
    """Verify kenpom_snapshots table exists; auto-create if missing.

    Uses a module-level flag so we only probe once per process lifetime.
    The db_client is the same SupabaseClient used by the rest of the scanner
    (created via get_supabase() in odds_scraper.py).

    If the table is missing, attempts to create it via PostgREST RPC
    using the same credentials.  Falls back to clear manual instructions
    if auto-creation fails.

    Returns True if the table is ready, False otherwise.
    """
    global _TABLE_VERIFIED
    if _TABLE_VERIFIED:
        return True

    # Probe: try a lightweight query against PostgREST.
    try:
        db_client._get("kenpom_snapshots", select="id", limit=1)
        _TABLE_VERIFIED = True
        return True
    except Exception as probe_err:
        err_str = str(probe_err).lower()
        # If it's not a "table missing" error, assume transient issue and proceed.
        if "does not exist" not in err_str and "relation" not in err_str and "404" not in err_str:
            _TABLE_VERIFIED = True
            return True

    # Table is missing — try to auto-create it.
    print("  [KENPOM SNAPSHOT] Table 'kenpom_snapshots' not found — attempting auto-create...")
    if _try_create_table_via_rpc(db_client):
        # Verify the table is now queryable.
        try:
            db_client._get("kenpom_snapshots", select="id", limit=1)
            _TABLE_VERIFIED = True
            return True
        except Exception:
            pass

    # Auto-creation failed — give clear instructions.
    print(
        f"  [KENPOM SNAPSHOT] Auto-create failed. Create the table manually:\n"
        f"  → Paste scripts/008_kenpom_snapshots.sql into Supabase SQL Editor\n"
        f"  → Or run: python scripts/create_kenpom_table.py"
    )
    return False


# ---------------------------------------------------------------------------
# Pinnacle odds extraction
# ---------------------------------------------------------------------------

def _extract_pinnacle_odds(game: Any, debug: bool = False) -> dict[str, Any] | None:
    """Extract Pinnacle's spread, total, and ML from a game's bookmakers.

    Handles games where Pinnacle only has some markets (e.g. h2h only)
    and where markets have alternate lines (>2 outcomes).

    Args:
        game: Game object from odds_api (has .bookmakers list).
        debug: If True, print bookmaker keys for diagnostics.

    Returns dict with available Pinnacle data, or None if Pinnacle not present.
    """
    bookmakers = getattr(game, "bookmakers", None)
    if bookmakers is None:
        if debug:
            print(f"    [PIN DEBUG] Game {getattr(game, 'id', '?')} has no 'bookmakers' attribute (type={type(game).__name__})")
        return None

    if debug:
        bk_keys = [bk.key for bk in bookmakers]
        print(f"    [PIN DEBUG] {game.away_team} @ {game.home_team}: {len(bookmakers)} bookmakers, keys={bk_keys}")

    pin_bk = None
    for bk in bookmakers:
        bk_key = getattr(bk, "key", "") or ""
        if bk_key.lower() == "pinnacle":
            pin_bk = bk
            break
    if pin_bk is None:
        if debug:
            print(f"    [PIN DEBUG] No 'pinnacle' bookmaker found")
        return None

    result: dict[str, Any] = {}
    home_team = game.home_team
    markets = getattr(pin_bk, "markets", []) or []

    if debug:
        mkt_info = [(getattr(m, "key", "?"), len(getattr(m, "outcomes", []))) for m in markets]
        print(f"    [PIN DEBUG] Pinnacle markets: {mkt_info}")

    for mkt in markets:
        mkt_key = getattr(mkt, "key", "") or ""
        outcomes = getattr(mkt, "outcomes", []) or []

        if mkt_key == "spreads" and len(outcomes) >= 2:
            for o in outcomes:
                if getattr(o, "name", "") == home_team and o.point is not None:
                    result["spread_home"] = o.point
                    break
            # Fallback: first outcome's point
            if "spread_home" not in result and outcomes[0].point is not None:
                result["spread_home"] = outcomes[0].point

        elif mkt_key == "totals" and len(outcomes) >= 2:
            for o in outcomes:
                if getattr(o, "name", "").lower() == "over" and o.point is not None:
                    result["total"] = o.point
                    break

        elif mkt_key == "h2h" and len(outcomes) >= 2:
            for o in outcomes:
                if getattr(o, "name", "") == home_team:
                    result["home_ml"] = o.price
                    result["home_implied_prob"] = american_to_implied_prob(o.price)
                else:
                    result["away_ml"] = o.price

    # Return any data we found — even ML-only is useful for ml_edge.
    if not result:
        if debug:
            print(f"    [PIN DEBUG] Pinnacle found but no extractable data")
        return None
    return result


def _fetch_pinnacle_from_db(
    db_client: Any,
    game_ids: list[str],
) -> dict[str, dict[str, Any]]:
    """Fallback: fetch latest Pinnacle odds from line_movements table.

    Returns {game_id: {spread_home, total, home_ml, away_ml, home_implied_prob}}.
    Used when in-memory game objects don't contain bookmaker data.
    """
    pin_data: dict[str, dict[str, Any]] = {}
    for i in range(0, len(game_ids), 50):
        chunk = game_ids[i : i + 50]
        id_list = ",".join(chunk)
        try:
            rows = db_client._get(
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
            if gid not in pin_data:
                pin_data[gid] = {}
            d = pin_data[gid]
            mkt = row.get("market_type", "")
            side = row.get("side", "")
            odds = row.get("odds")
            if odds is None:
                continue

            # Parse spread from side like "Team Name -5.5"
            if mkt == "spreads" and "spread_home" not in d:
                parts = side.rsplit(" ", 1)
                if len(parts) == 2:
                    try:
                        d["spread_home"] = float(parts[1])
                    except ValueError:
                        pass

            # Parse total from side like "Over 148.5"
            elif mkt == "totals" and "total" not in d:
                if side.lower().startswith("over"):
                    parts = side.rsplit(" ", 1)
                    if len(parts) == 2:
                        try:
                            d["total"] = float(parts[1])
                        except ValueError:
                            pass

            # Parse ML — need to know which side is home
            elif mkt == "h2h":
                if "home_ml" not in d:
                    d["home_ml"] = int(odds)
                    d["home_implied_prob"] = american_to_implied_prob(int(odds))
                elif "away_ml" not in d:
                    d["away_ml"] = int(odds)

    return pin_data


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
        db_client: Supabase client (same one used by scanner for EV, signals, etc.).
        game_projections: dict of game_id -> KenPom projection dict.
        all_games: list of Game objects (has bookmakers with Pinnacle).
        snapshot_dt: Override snapshot date (defaults to today UTC).

    Returns number of snapshots saved.
    """
    print(
        f"  [KENPOM SNAPSHOT] save_kenpom_snapshots called — "
        f"db_client={type(db_client).__name__}, "
        f"{len(game_projections)} projections, "
        f"{len(all_games)} games"
    )

    if not db_client:
        print("  [KENPOM SNAPSHOT] Skipped — no DB client.")
        return 0
    if not game_projections:
        print("  [KENPOM SNAPSHOT] Skipped — game_projections is empty.")
        return 0

    # Ensure table exists (probe once per process).
    if not _ensure_table(db_client):
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
    game_map = {g.id: g for g in all_games if getattr(g, "sport_key", "") == "basketball_ncaab"}

    # Debug: inspect first CBB game to diagnose Pinnacle extraction issues.
    if game_map:
        g0_id = next(iter(game_map))
        g0 = game_map[g0_id]
        bks = getattr(g0, "bookmakers", None)
        print(
            f"  [KENPOM SNAPSHOT DEBUG] First CBB game: type={type(g0).__name__}, "
            f"id={g0_id}, has bookmakers={bks is not None}, "
            f"count={len(bks) if bks else 0}"
        )
        if bks:
            bk_keys = [getattr(bk, "key", "?") for bk in bks]
            print(f"  [KENPOM SNAPSHOT DEBUG] Bookmaker keys: {bk_keys}")
            pin_bks = [bk for bk in bks if (getattr(bk, "key", "") or "").lower() == "pinnacle"]
            if pin_bks:
                mkts = getattr(pin_bks[0], "markets", [])
                mkt_info = [(getattr(m, "key", "?"), len(getattr(m, "outcomes", []))) for m in mkts]
                print(f"  [KENPOM SNAPSHOT DEBUG] Pinnacle markets: {mkt_info}")
            else:
                print(f"  [KENPOM SNAPSHOT DEBUG] 'pinnacle' NOT in bookmaker keys")
        else:
            print(f"  [KENPOM SNAPSHOT DEBUG] Game has NO bookmakers — odds data not attached to game objects")

    rows: list[dict] = []
    pin_found = 0
    pin_missing = 0
    no_game = 0

    # First pass: extract Pinnacle from in-memory game objects.
    games_needing_pin: list[str] = []  # game_ids where extraction failed
    for game_id, proj in game_projections.items():
        if game_id in existing_ids:
            continue

        game = game_map.get(game_id)
        if game is None:
            no_game += 1
            continue

        # Debug first game's extraction in detail.
        debug_this = (pin_found == 0 and pin_missing == 0)
        pin = _extract_pinnacle_odds(game, debug=debug_this)
        if pin:
            pin_found += 1
        else:
            pin_missing += 1
            games_needing_pin.append(game_id)

        # KenPom data.
        kp_home = proj.get("home_score") or proj.get("home_pred", 0)
        kp_away = proj.get("away_score") or proj.get("away_pred", 0)
        kp_wp = proj.get("home_win_prob") or proj.get("home_wp", 0.5)
        kp_total = kp_home + kp_away
        kp_spread = kp_home - kp_away

        pin_spread = pin.get("spread_home") if pin else None
        pin_total = pin.get("total") if pin else None
        pin_home_ml = pin.get("home_ml") if pin else None
        pin_away_ml = pin.get("away_ml") if pin else None
        pin_home_ip = pin.get("home_implied_prob") if pin else None

        spread_edge = (kp_spread - pin_spread) if pin_spread is not None else None
        total_edge = (kp_total - pin_total) if pin_total is not None else None
        ml_edge = (kp_wp - pin_home_ip) if pin_home_ip is not None else None

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

    # Fallback: if in-memory extraction missed games, try the DB.
    if games_needing_pin and db_client:
        print(
            f"  [KENPOM SNAPSHOT] {len(games_needing_pin)} games missing Pinnacle in-memory, "
            f"trying line_movements DB fallback..."
        )
        db_pin = _fetch_pinnacle_from_db(db_client, games_needing_pin)
        backfilled = 0
        for row in rows:
            gid = row["game_id"]
            if gid not in db_pin or row["pinnacle_spread_home"] is not None:
                continue
            pin = db_pin[gid]
            if not pin:
                continue
            pin_spread = pin.get("spread_home")
            pin_total = pin.get("total")
            pin_home_ml = pin.get("home_ml")
            pin_away_ml = pin.get("away_ml")
            pin_home_ip = pin.get("home_implied_prob")

            if pin_spread is not None:
                row["pinnacle_spread_home"] = pin_spread
                row["spread_edge"] = round(row["kp_projected_spread"] - pin_spread, 2)
            if pin_total is not None:
                row["pinnacle_total"] = pin_total
                row["total_edge"] = round(row["kp_projected_total"] - pin_total, 2)
            if pin_home_ml is not None:
                row["pinnacle_home_ml"] = int(pin_home_ml)
            if pin_away_ml is not None:
                row["pinnacle_away_ml"] = int(pin_away_ml)
            if pin_home_ip is not None:
                row["pinnacle_home_implied_prob"] = round(pin_home_ip, 4)
                row["ml_edge"] = round(row["kp_home_win_prob"] - pin_home_ip, 4)
            backfilled += 1

        if backfilled:
            pin_found += backfilled
            pin_missing -= backfilled
            print(f"  [KENPOM SNAPSHOT] DB fallback filled Pinnacle data for {backfilled} games")

    print(
        f"  [KENPOM SNAPSHOT] {len(game_projections)} KP projections, "
        f"{pin_found} with Pinnacle, {pin_missing} without Pinnacle"
        + (f", {no_game} not in all_games" if no_game else "")
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
        print(f"  [KENPOM SNAPSHOT] ERROR saving snapshots: {e}")
        traceback.print_exc()
        return 0


# ---------------------------------------------------------------------------
# Grading — UPDATE-only, never INSERT new rows
# ---------------------------------------------------------------------------

def grade_kenpom_snapshots(db_client: Any) -> dict[str, int]:
    """Grade ungraded KenPom snapshots against final game scores.

    ONLY updates existing snapshot rows — never inserts new ones.
    Uses _patch_by_ids to guarantee UPDATE-only semantics.

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

    # Fetch ungraded snapshots — we need the row 'id' for PATCH.
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

    # Grade each snapshot — collect row IDs and grading data for PATCH.
    graded_ids: list[str] = []
    grade_data_by_id: dict[str, dict] = {}

    for snap in ungraded:
        gid = snap["game_id"]
        row_id = snap.get("id")
        if row_id is None:
            continue
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
        spread_correct = None
        if spread_edge is not None and pin_spread is not None and spread_edge != 0:
            ats_margin = actual_spread + pin_spread
            if ats_margin == 0:
                spread_correct = None  # push
            elif spread_edge > 0:
                spread_correct = ats_margin > 0
            else:
                spread_correct = ats_margin < 0

        # Total grading.
        total_correct = None
        if total_edge is not None and pin_total is not None and total_edge != 0:
            if total_edge > 0:
                total_correct = actual_total > pin_total
            else:
                total_correct = actual_total < pin_total
            if actual_total == pin_total:
                total_correct = None  # push

        # ML grading.
        ml_correct = None
        if kp_wp is not None and kp_wp != 0.5:
            if kp_wp > 0.5:
                ml_correct = actual_spread > 0
            else:
                ml_correct = actual_spread < 0
            if actual_spread == 0:
                ml_correct = None

        graded_ids.append(row_id)
        grade_data_by_id[row_id] = {
            "result_home_score": home_score,
            "result_away_score": away_score,
            "result_spread_correct": spread_correct,
            "result_total_correct": total_correct,
            "result_ml_correct": ml_correct,
        }

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

    # Batch PATCH — UPDATE-only, never INSERT.
    # Group by identical grade data to minimize PATCH calls.
    if graded_ids:
        now_iso = datetime.now(timezone.utc).isoformat()
        try:
            # PATCH each row individually by ID — ensures UPDATE-only.
            for row_id in graded_ids:
                update_data = {
                    **grade_data_by_id[row_id],
                    "graded": True,
                    "updated_at": now_iso,
                }
                db_client._http.patch(
                    f"{db_client.base_url}/kenpom_snapshots",
                    headers={**db_client.headers, "Prefer": "return=minimal"},
                    params={"id": f"eq.{row_id}"},
                    json=update_data,
                    timeout=30,
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
