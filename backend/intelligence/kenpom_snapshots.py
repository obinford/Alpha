"""KenPom snapshot storage and grading.

Persists daily KenPom projections alongside Pinnacle odds so we can
track edge accuracy over time.  Called from the scanner after KenPom
projections and Pinnacle odds are loaded.

Grading is run when final scores arrive — compares KenPom's edges
against actual results.

Sign conventions:
    kp_projected_spread: positive = home projects to win by that many points
        (margin convention, like a final score diff)
    pinnacle_spread_home: negative = home is favored by that many points
        (betting convention, as displayed by sportsbooks)

Edge calculation:
    spread_edge = kp_projected_spread + pinnacle_spread_home
        Both conventions must be combined (not subtracted) because they
        use OPPOSITE signs for the same direction.
        Example: KP projects home -6 (kp_spread=+6), Pinnacle has home
        at -5.5 (pin_spread=-5.5) → edge = 6 + (-5.5) = +0.5
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
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

_ET = ZoneInfo("America/New_York")

from models.ev_calculator import american_to_implied_prob


def _game_date_from_commence(commence_time: str | None, fallback: date | None = None) -> date:
    """Derive the game's calendar date in US Eastern from its commence_time.

    NCAAB games at e.g. 8 PM ET on Feb 19 have commence_time "2026-02-20T01:00:00Z"
    in UTC.  Without this conversion, they'd be bucketed as Feb 20 games.
    """
    if commence_time:
        try:
            dt = datetime.fromisoformat(commence_time.replace("Z", "+00:00"))
            return dt.astimezone(_ET).date()
        except Exception:
            pass
    return fallback or date.today()


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
                    result["spread_home_odds"] = o.price
                elif getattr(o, "name", "") != home_team:
                    result["spread_away_odds"] = getattr(o, "price", None)
            # Fallback: first outcome's point
            if "spread_home" not in result and outcomes[0].point is not None:
                result["spread_home"] = outcomes[0].point
                result["spread_home_odds"] = getattr(outcomes[0], "price", None)
                if len(outcomes) > 1:
                    result["spread_away_odds"] = getattr(outcomes[1], "price", None)

        elif mkt_key == "totals" and len(outcomes) >= 2:
            for o in outcomes:
                oname = getattr(o, "name", "").lower()
                if oname == "over" and o.point is not None:
                    result["total"] = o.point
                    result["over_odds"] = o.price
                elif oname == "under":
                    result["under_odds"] = getattr(o, "price", None)

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

    # Build game lookup (CBB only) — needed early for date derivation.
    game_map = {g.id: g for g in all_games if getattr(g, "sport_key", "") == "basketball_ncaab"}

    # Helper: snapshot_date is the game's calendar date in US Eastern,
    # so an 8 PM ET game on Feb 19 (01:00 UTC Feb 20) is bucketed as Feb 19.
    # If the caller overrides via snapshot_dt, all games share that date.
    def _snap_date(game_id: str) -> str:
        if snapshot_dt:
            return snapshot_dt.isoformat()
        game = game_map.get(game_id)
        ct = getattr(game, "commence_time", None) if game else None
        return _game_date_from_commence(ct).isoformat()

    # Classify projections by source AND date.
    fanmatch_by_date: dict[str, list[str]] = {}
    ratings_by_date: dict[str, list[str]] = {}
    game_date_cache: dict[str, str] = {}  # game_id -> date string
    for gid, p in game_projections.items():
        d = _snap_date(gid)
        game_date_cache[gid] = d
        if "fanmatch" in p.get("source", ""):
            fanmatch_by_date.setdefault(d, []).append(gid)
        else:
            ratings_by_date.setdefault(d, []).append(gid)

    all_dates = sorted(set(fanmatch_by_date) | set(ratings_by_date))
    total_fanmatch = sum(len(v) for v in fanmatch_by_date.values())
    total_ratings = sum(len(v) for v in ratings_by_date.values())
    print(
        f"  [KENPOM SNAPSHOT] Projections: {total_fanmatch} fanmatch, "
        f"{total_ratings} ratings across dates {all_dates}"
    )

    # -----------------------------------------------------------------------
    # PURGE: For each date with fanmatch data, DELETE non-fanmatch rows.
    # This guarantees stale ratings rows can never block fanmatch insertion.
    # -----------------------------------------------------------------------
    for dt_str, fm_ids in fanmatch_by_date.items():
        purged = 0
        for source_filter in ["is.null", "neq.kenpom_fanmatch"]:
            try:
                resp = db_client._http.delete(
                    f"{db_client.base_url}/kenpom_snapshots",
                    headers={**db_client.headers, "Prefer": "return=representation"},
                    params={
                        "snapshot_date": f"eq.{dt_str}",
                        "projection_source": source_filter,
                    },
                    timeout=15,
                )
                if resp.status_code < 400:
                    body = resp.json() if resp.text.strip() else []
                    purged += len(body)
            except Exception as e:
                print(f"  [KENPOM SNAPSHOT] Purge failed ({source_filter}) for {dt_str}: {e}")
        if purged:
            print(f"  [KENPOM SNAPSHOT] Purged {purged} non-fanmatch snapshots for {dt_str}")

    # For ratings-only projections, check which games already have ANY
    # snapshot for that date (fanmatch rows we want to keep).
    existing_snapshot_ids: set[str] = set()
    for dt_str, rat_ids in ratings_by_date.items():
        for i in range(0, len(rat_ids), 50):
            chunk = rat_ids[i : i + 50]
            id_list = ",".join(chunk)
            try:
                existing_rows = db_client._get(
                    "kenpom_snapshots",
                    select="game_id",
                    filters={
                        "snapshot_date": f"eq.{dt_str}",
                        "game_id": f"in.({id_list})",
                    },
                )
                existing_snapshot_ids.update(r["game_id"] for r in existing_rows)
            except Exception:
                pass
    if existing_snapshot_ids:
        print(
            f"  [KENPOM SNAPSHOT] {len(existing_snapshot_ids)} ratings games already have "
            f"snapshots (fanmatch), skipping those"
        )

    rows: list[dict] = []
    pin_found = 0
    pin_missing = 0
    no_game = 0
    save_count_fanmatch = 0
    save_count_ratings = 0

    # Build rows: fanmatch ALWAYS upserts, ratings only fill gaps.
    games_needing_pin: list[str] = []
    debug_count = 0
    for game_id, proj in game_projections.items():
        new_source = proj.get("source", "unknown")
        is_fanmatch = "fanmatch" in new_source

        # Ratings only upsert if NO snapshot exists for this game's date.
        if not is_fanmatch and game_id in existing_snapshot_ids:
            continue

        # Debug: log first 3 games for source chain verification.
        if debug_count < 3:
            kp_h = proj.get("home_score") or proj.get("home_pred", 0)
            kp_a = proj.get("away_score") or proj.get("away_pred", 0)
            print(
                f"  [KENPOM SNAPSHOT DEBUG] Game {game_id[:30]}: "
                f"source={new_source}, home={kp_h:.1f}, away={kp_a:.1f}"
            )
            debug_count += 1

        if is_fanmatch:
            save_count_fanmatch += 1
        else:
            save_count_ratings += 1

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

        spread_edge = (kp_spread + pin_spread) if pin_spread is not None else None
        total_edge = (kp_total - pin_total) if pin_total is not None else None
        ml_edge = (kp_wp - pin_home_ip) if pin_home_ip is not None else None

        rows.append({
            "snapshot_date": game_date_cache.get(game_id, date.today().isoformat()),
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
            "pinnacle_spread_home_odds": int(pin.get("spread_home_odds")) if pin and pin.get("spread_home_odds") is not None else None,
            "pinnacle_spread_away_odds": int(pin.get("spread_away_odds")) if pin and pin.get("spread_away_odds") is not None else None,
            "pinnacle_over_odds": int(pin.get("over_odds")) if pin and pin.get("over_odds") is not None else None,
            "pinnacle_under_odds": int(pin.get("under_odds")) if pin and pin.get("under_odds") is not None else None,
            "spread_edge": round(spread_edge, 2) if spread_edge is not None else None,
            "total_edge": round(total_edge, 2) if total_edge is not None else None,
            "ml_edge": round(ml_edge, 4) if ml_edge is not None else None,
            "projection_source": proj.get("source", "unknown"),
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
                row["spread_edge"] = round(row["kp_projected_spread"] + pin_spread, 2)
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
        f"  [KENPOM SNAPSHOT] Saving {save_count_fanmatch} fanmatch + "
        f"{save_count_ratings} ratings projections | "
        f"{pin_found} with Pinnacle, {pin_missing} without"
        + (f", {no_game} not in all_games" if no_game else "")
    )

    if not rows:
        print(f"  [KENPOM SNAPSHOT] Nothing new to save for {all_dates}.")
        return 0

    # Log first 3 rows being saved.
    for i, row in enumerate(rows[:3]):
        print(
            f"  [KENPOM SNAPSHOT] Saved: "
            f"{row['away_team']} @ {row['home_team']} "
            f"date={row['snapshot_date']} source={row['projection_source']} "
            f"home={row['kp_home_score']} away={row['kp_away_score']}"
        )

    try:
        db_client._upsert_many(
            "kenpom_snapshots", rows, on_conflict="snapshot_date,game_id"
        )
        elapsed = time.time() - t0
        print(
            f"  [KENPOM SNAPSHOT] Saved {len(rows)} snapshots across {all_dates} ({elapsed:.1f}s)"
        )
    except Exception as e:
        print(f"  [KENPOM SNAPSHOT] ERROR saving snapshots: {e}")
        traceback.print_exc()
        return 0

    # Verify: query back source counts per date.
    for verify_dt in all_dates:
        try:
            verify_rows = db_client._get(
                "kenpom_snapshots",
                select="projection_source",
                filters={"snapshot_date": f"eq.{verify_dt}"},
            )
            source_counts: dict[str, int] = {}
            for vr in verify_rows:
                src = vr.get("projection_source") or "null"
                source_counts[src] = source_counts.get(src, 0) + 1
            print(
                f"  [KENPOM SNAPSHOT] Verify: {len(verify_rows)} snapshots for {verify_dt} — "
                + ", ".join(f"{src}={cnt}" for src, cnt in sorted(source_counts.items()))
            )
        except Exception as e:
            print(f"  [KENPOM SNAPSHOT] Verify query failed for {verify_dt}: {e}")

    return len(rows)


# ---------------------------------------------------------------------------
# Purge stale ratings-only snapshots
# ---------------------------------------------------------------------------

def purge_stale_ratings_snapshots(
    db_client: Any,
    target_date: date | None = None,
) -> int:
    """Delete snapshots where projection_source is NULL or 'kenpom_ratings'.

    These will be re-populated with fanmatch data on the next scan cycle
    (if fanmatch is available), or left empty if only ratings exist.

    Args:
        db_client: Supabase client.
        target_date: Date to purge (defaults to today UTC).

    Returns number of rows deleted.
    """
    if not db_client:
        return 0

    today_str = (target_date or date.today()).isoformat()
    deleted = 0

    for source_filter in ["is.null", "eq.kenpom_ratings", "eq.unknown"]:
        try:
            resp = db_client._http.delete(
                f"{db_client.base_url}/kenpom_snapshots",
                headers={**db_client.headers, "Prefer": "return=representation"},
                params={
                    "snapshot_date": f"eq.{today_str}",
                    "projection_source": source_filter,
                },
                timeout=15,
            )
            if resp.status_code < 400:
                rows = resp.json() if resp.text else []
                deleted += len(rows)
        except Exception as e:
            print(f"  [KENPOM PURGE] Delete failed for source={source_filter}: {e}")

    if deleted:
        print(f"  [KENPOM PURGE] Deleted {deleted} stale ratings/null snapshots for {today_str}")
    else:
        print(f"  [KENPOM PURGE] No stale snapshots to purge for {today_str}")
    return deleted


# ---------------------------------------------------------------------------
# Unit P/L calculation
# ---------------------------------------------------------------------------

def _calc_unit_result(odds: int | None, correct: bool | None) -> float | None:
    """Calculate unit profit/loss for a 1-unit bet at American odds.

    WIN at -110: profit = 100/110 = +0.91
    WIN at +150: profit = 150/100 = +1.50
    LOSS: always -1.0
    PUSH (correct=None): None (excluded from sums)
    """
    if correct is None or odds is None:
        return None
    if correct:
        if odds > 0:
            return round(odds / 100.0, 4)
        elif odds < 0:
            return round(100.0 / abs(odds), 4)
        return 0.0
    return -1.0


# ---------------------------------------------------------------------------
# Backfill missing Pinnacle data from pinnacle_odds_history
# ---------------------------------------------------------------------------

def _backfill_pinnacle_for_grading(
    db_client: Any,
    snapshots: list[dict],
) -> int:
    """Backfill missing pinnacle_spread_home / pinnacle_total from history tables.

    Tries pinnacle_odds_history first (closing lines), then line_movements.
    Updates snapshot rows in-place AND patches the DB.

    Returns count of snapshots backfilled.
    """
    missing_ids = list({
        s["game_id"] for s in snapshots
        if s.get("pinnacle_spread_home") is None or s.get("pinnacle_total") is None
    })
    if not missing_ids:
        return 0

    # Try pinnacle_odds_history first (closing lines have odds).
    pin_by_game: dict[str, dict] = {}
    for i in range(0, len(missing_ids), 50):
        chunk = missing_ids[i : i + 50]
        id_list = ",".join(chunk)
        try:
            rows = db_client._get(
                "pinnacle_odds_history",
                select="game_id,market_type,line_value,home_odds,away_odds,over_odds,under_odds,home_prob",
                filters={
                    "game_id": f"in.({id_list})",
                    "snapshot_type": "eq.closing",
                },
            )
            for r in rows:
                gid = r["game_id"]
                if gid not in pin_by_game:
                    pin_by_game[gid] = {}
                d = pin_by_game[gid]
                mkt = r.get("market_type", "")
                if mkt == "spreads" and "spread_home" not in d:
                    d["spread_home"] = r.get("line_value")
                    d["spread_home_odds"] = r.get("home_odds")
                    d["spread_away_odds"] = r.get("away_odds")
                elif mkt == "totals" and "total" not in d:
                    d["total"] = r.get("line_value")
                    d["over_odds"] = r.get("over_odds")
                    d["under_odds"] = r.get("under_odds")
                elif mkt == "h2h" and "home_ml" not in d:
                    d["home_ml"] = r.get("home_odds")
                    d["away_ml"] = r.get("away_odds")
                    d["home_prob"] = r.get("home_prob")
        except Exception as e:
            print(f"  [KENPOM GRADING] pinnacle_odds_history query failed: {e}")

    # For games still missing, try line_movements.
    still_missing = [gid for gid in missing_ids if gid not in pin_by_game]
    if still_missing:
        lm_data = _fetch_pinnacle_from_db(db_client, still_missing)
        for gid, d in lm_data.items():
            if gid not in pin_by_game and d:
                pin_by_game[gid] = d

    if not pin_by_game:
        return 0

    # PATCH each snapshot with the backfilled data.
    now_iso = datetime.now(timezone.utc).isoformat()
    backfilled = 0
    for snap in snapshots:
        gid = snap["game_id"]
        row_id = snap.get("id")
        if gid not in pin_by_game or row_id is None:
            continue
        pin = pin_by_game[gid]
        update: dict[str, Any] = {}

        if snap.get("pinnacle_spread_home") is None and pin.get("spread_home") is not None:
            spread_val = pin["spread_home"]
            update["pinnacle_spread_home"] = spread_val
            kp_spread = snap.get("kp_projected_spread", 0)
            update["spread_edge"] = round(kp_spread + spread_val, 2)
            snap["pinnacle_spread_home"] = spread_val
            snap["spread_edge"] = update["spread_edge"]

        if snap.get("pinnacle_total") is None and pin.get("total") is not None:
            total_val = pin["total"]
            update["pinnacle_total"] = total_val
            kp_total = snap.get("kp_projected_total", 0)
            update["total_edge"] = round(kp_total - total_val, 2)
            snap["pinnacle_total"] = total_val
            snap["total_edge"] = update["total_edge"]

        # Backfill odds columns.
        for src_key, db_key in [
            ("spread_home_odds", "pinnacle_spread_home_odds"),
            ("spread_away_odds", "pinnacle_spread_away_odds"),
            ("over_odds", "pinnacle_over_odds"),
            ("under_odds", "pinnacle_under_odds"),
        ]:
            if snap.get(db_key) is None and pin.get(src_key) is not None:
                update[db_key] = int(pin[src_key])
                snap[db_key] = update[db_key]

        # Backfill ML if missing.
        if snap.get("pinnacle_home_ml") is None and pin.get("home_ml") is not None:
            update["pinnacle_home_ml"] = int(pin["home_ml"])
            snap["pinnacle_home_ml"] = update["pinnacle_home_ml"]
            if pin.get("away_ml") is not None:
                update["pinnacle_away_ml"] = int(pin["away_ml"])
                snap["pinnacle_away_ml"] = update["pinnacle_away_ml"]
            ip = pin.get("home_prob") or american_to_implied_prob(pin["home_ml"])
            update["pinnacle_home_implied_prob"] = round(ip, 4)
            update["ml_edge"] = round(snap.get("kp_home_win_prob", 0.5) - ip, 4)
            snap["pinnacle_home_implied_prob"] = update["pinnacle_home_implied_prob"]
            snap["ml_edge"] = update["ml_edge"]

        if update:
            update["updated_at"] = now_iso
            try:
                db_client._http.patch(
                    f"{db_client.base_url}/kenpom_snapshots",
                    headers={**db_client.headers, "Prefer": "return=minimal"},
                    params={"id": f"eq.{row_id}"},
                    json=update,
                    timeout=15,
                )
                backfilled += 1
            except Exception as e:
                print(f"  [KENPOM GRADING] Backfill PATCH failed for {gid}: {e}")

    return backfilled


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
    - spread_unit_result / total_unit_result / ml_unit_result: P/L in units

    Returns dict with keys: graded, spread_wins, spread_losses,
    total_wins, total_losses, ml_wins, ml_losses,
    spread_units, total_units, ml_units.
    """
    result: dict[str, Any] = {
        "graded": 0,
        "spread_wins": 0, "spread_losses": 0,
        "total_wins": 0, "total_losses": 0,
        "ml_wins": 0, "ml_losses": 0,
        "spread_units": 0.0, "total_units": 0.0, "ml_units": 0.0,
    }
    if db_client is None:
        return result

    # Ensure table exists before querying.
    if not _ensure_table(db_client):
        return result

    # Fetch ungraded snapshots — include all fields needed for grading + units.
    try:
        ungraded = db_client._get(
            "kenpom_snapshots",
            select="id,game_id,snapshot_date,home_team,away_team,"
                   "kp_projected_spread,kp_projected_total,kp_home_win_prob,"
                   "pinnacle_spread_home,pinnacle_total,spread_edge,total_edge,ml_edge,"
                   "pinnacle_spread_home_odds,pinnacle_spread_away_odds,"
                   "pinnacle_over_odds,pinnacle_under_odds,"
                   "pinnacle_home_ml,pinnacle_away_ml",
            filters={"graded": "eq.false"},
        )
    except Exception as e:
        print(f"  [KENPOM GRADING] Failed to fetch ungraded snapshots: {e}")
        return result

    if not ungraded:
        return result

    print(f"  [KENPOM GRADING] {len(ungraded)} ungraded snapshots found")

    # Debug: sample game_ids and snapshot dates.
    sample_ids = [s["game_id"] for s in ungraded[:3]]
    snap_dates = sorted({s.get("snapshot_date", "")[:10] for s in ungraded})
    print(f"  [KENPOM GRADING] Snapshot dates: {snap_dates}")
    print(f"  [KENPOM GRADING] Sample game_ids: {sample_ids}")

    # Step 1: backfill missing Pinnacle data from history tables.
    missing_pin_spread = sum(1 for s in ungraded if s.get("pinnacle_spread_home") is None)
    missing_pin_total = sum(1 for s in ungraded if s.get("pinnacle_total") is None)
    if missing_pin_spread or missing_pin_total:
        print(
            f"  [KENPOM GRADING] {missing_pin_spread} missing Pinnacle spread, "
            f"{missing_pin_total} missing Pinnacle total — backfilling..."
        )
        backfilled = _backfill_pinnacle_for_grading(db_client, ungraded)
        if backfilled:
            print(f"  [KENPOM GRADING] Backfilled Pinnacle data for {backfilled} games")
        recovered_spread = missing_pin_spread - sum(1 for s in ungraded if s.get("pinnacle_spread_home") is None)
        recovered_total = missing_pin_total - sum(1 for s in ungraded if s.get("pinnacle_total") is None)
        print(
            f"  [KENPOM GRADING] Recovered: {recovered_spread} spread, {recovered_total} total"
        )

    # Step 2: fetch final scores.
    # Try matching by game_id first, then fallback to team names.
    game_ids = list({s["game_id"] for s in ungraded})
    final_scores: dict[str, dict] = {}

    # Build a team-name index for fallback matching.
    # Key: (normalized_home, normalized_away, date) -> snapshot game_id
    def _norm(name: str) -> str:
        return name.strip().lower()

    snap_team_index: dict[tuple[str, str, str], str] = {}
    for s in ungraded:
        ht = _norm(s.get("home_team", ""))
        at = _norm(s.get("away_team", ""))
        sd = s.get("snapshot_date", "")[:10]
        snap_team_index[(ht, at, sd)] = s["game_id"]

    # Determine date range: today + yesterday to handle timezone mismatches.
    today_utc = date.today()
    yesterday_utc = today_utc - timedelta(days=1)

    # --- Primary: match by game_id from 'games' table ---
    for i in range(0, len(game_ids), 50):
        chunk = game_ids[i : i + 50]
        id_list = ",".join(chunk)
        try:
            games = db_client._get(
                "games",
                select="game_id,home_team,away_team,home_score,away_score,status,commence_time",
                filters={
                    "game_id": f"in.({id_list})",
                    "status": "eq.final",
                },
            )
            for g in games:
                if g.get("home_score") is not None and g.get("away_score") is not None:
                    final_scores[g["game_id"]] = g
        except Exception as e:
            if "does not exist" in str(e).lower() or "404" in str(e):
                print(f"  [KENPOM GRADING] 'games' table not found: {e}")
            break

    print(
        f"  [KENPOM GRADING] {len(final_scores)} final scores from 'games' table "
        f"(of {len(game_ids)} game_ids) via game_id match"
    )

    # --- Fallback: try 'scores' / 'game_results' tables if many missing ---
    if len(final_scores) < len(game_ids) * 0.5:
        remaining_ids = [gid for gid in game_ids if gid not in final_scores]
        for i in range(0, len(remaining_ids), 50):
            chunk = remaining_ids[i : i + 50]
            id_list = ",".join(chunk)
            for table_name in ["scores", "game_results"]:
                try:
                    rows = db_client._get(
                        table_name,
                        select="game_id,home_team,away_team,home_score,away_score,status",
                        filters={
                            "game_id": f"in.({id_list})",
                            "status": "eq.final",
                        },
                    )
                    for g in rows:
                        if g.get("home_score") is not None and g.get("away_score") is not None:
                            final_scores[g["game_id"]] = g
                    if rows:
                        print(f"  [KENPOM GRADING] Found {len(rows)} more scores in '{table_name}'")
                except Exception:
                    pass  # table may not exist

    # --- Fallback: fetch finished games for today AND yesterday by date ---
    # This catches games where snapshot game_id doesn't exactly match the
    # games table game_id (timezone mismatch: game stored with yesterday's date).
    if len(final_scores) < len(game_ids):
        team_matched = 0
        for target_date in [today_utc, yesterday_utc]:
            try:
                date_games = db_client._get(
                    "games",
                    select="game_id,home_team,away_team,home_score,away_score,status,commence_time",
                    filters={
                        "status": "eq.final",
                        "commence_time": f"gte.{target_date.isoformat()}T00:00:00Z",
                    },
                )
                for g in date_games:
                    gid = g.get("game_id", "")
                    if gid in final_scores:
                        continue
                    if g.get("home_score") is None or g.get("away_score") is None:
                        continue
                    # Direct game_id match (may already be there).
                    if gid in game_ids:
                        final_scores[gid] = g
                        continue
                    # Team-name fallback: try matching against snapshot team names.
                    ht = _norm(g.get("home_team", ""))
                    at = _norm(g.get("away_team", ""))
                    for snap_date in snap_dates:
                        key = (ht, at, snap_date)
                        if key in snap_team_index:
                            snap_gid = snap_team_index[key]
                            if snap_gid not in final_scores:
                                final_scores[snap_gid] = g
                                team_matched += 1
                            break
            except Exception:
                pass  # table/filter may not be supported

        if team_matched:
            print(f"  [KENPOM GRADING] Team-name fallback matched {team_matched} additional games")

    total_finished = len(final_scores)
    total_ungraded = len(game_ids)
    print(
        f"  [KENPOM GRADING] Matched {total_finished} of {total_ungraded} finished games"
    )

    if not final_scores:
        print(
            f"  [KENPOM GRADING] No final scores found for any of {len(game_ids)} game_ids. "
            f"Check that finished games are stored in 'games' table with status='final'."
        )
        return result

    # Step 3: Grade each snapshot.
    graded_ids: list[str] = []
    grade_data_by_id: dict[str, dict] = {}
    examples: list[str] = []

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
        home_team = snap.get("home_team", "Home")
        away_team = snap.get("away_team", "Away")

        # --- Spread grading (ATS coverage) ---
        # "If I bet 1 unit on KP's recommended side at Pinnacle's spread, did I win?"
        spread_correct = None
        if spread_edge is not None and pin_spread is not None and spread_edge != 0:
            ats_margin = actual_spread + pin_spread
            if ats_margin == 0:
                spread_correct = None  # push
            elif spread_edge > 0:
                # KP says take home ATS
                spread_correct = ats_margin > 0
            else:
                # KP says take away ATS
                spread_correct = ats_margin < 0

        # --- Total grading ---
        total_correct = None
        if total_edge is not None and pin_total is not None and total_edge != 0:
            if actual_total == pin_total:
                total_correct = None  # push
            elif total_edge > 0:
                total_correct = actual_total > pin_total
            else:
                total_correct = actual_total < pin_total

        # --- ML grading ---
        ml_correct = None
        if kp_wp is not None and kp_wp != 0.5:
            if actual_spread == 0:
                ml_correct = None
            elif kp_wp > 0.5:
                ml_correct = actual_spread > 0
            else:
                ml_correct = actual_spread < 0

        # --- Unit P/L ---
        # Spread: bet on the side KP recommends, at that side's Pinnacle odds.
        if spread_edge is not None and spread_edge > 0:
            s_odds = snap.get("pinnacle_spread_home_odds") or -110
        elif spread_edge is not None and spread_edge < 0:
            s_odds = snap.get("pinnacle_spread_away_odds") or -110
        else:
            s_odds = None
        spread_units = _calc_unit_result(s_odds, spread_correct)

        # Total: over or under at those odds.
        if total_edge is not None and total_edge > 0:
            t_odds = snap.get("pinnacle_over_odds") or -110
        elif total_edge is not None and total_edge < 0:
            t_odds = snap.get("pinnacle_under_odds") or -110
        else:
            t_odds = None
        total_units = _calc_unit_result(t_odds, total_correct)

        # ML: home or away ML.
        if kp_wp is not None and kp_wp > 0.5:
            ml_odds = snap.get("pinnacle_home_ml")
        elif kp_wp is not None and kp_wp < 0.5:
            ml_odds = snap.get("pinnacle_away_ml")
        else:
            ml_odds = None
        ml_units = _calc_unit_result(ml_odds, ml_correct)

        graded_ids.append(row_id)
        grade_data_by_id[row_id] = {
            "result_home_score": home_score,
            "result_away_score": away_score,
            "result_spread_correct": spread_correct,
            "result_total_correct": total_correct,
            "result_ml_correct": ml_correct,
            "spread_unit_result": spread_units,
            "total_unit_result": total_units,
            "ml_unit_result": ml_units,
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
        if spread_units is not None:
            result["spread_units"] += spread_units
        if total_units is not None:
            result["total_units"] += total_units
        if ml_units is not None:
            result["ml_units"] += ml_units

        # Collect verification examples (first 3 graded games).
        if len(examples) < 3 and spread_correct is not None:
            kp_spr = snap.get("kp_projected_spread", 0)
            pick_team = home_team if (spread_edge or 0) > 0 else away_team
            pick_line = pin_spread if (spread_edge or 0) > 0 else (-pin_spread if pin_spread else 0)
            result_str = "WIN" if spread_correct else "LOSS"
            examples.append(
                f"{away_team} @ {home_team}: "
                f"KP spread={kp_spr:+.1f}, PIN={pin_spread}, "
                f"Pick=Take {pick_team} {pick_line:+.1f}, "
                f"Actual={home_score}-{away_score} (margin={actual_spread:+d}), "
                f"ATS margin={actual_spread + (pin_spread or 0):+.1f} → {result_str}"
                + (f" ({spread_units:+.2f}u)" if spread_units is not None else "")
            )

    # Print verification examples.
    for ex in examples:
        print(f"  [KENPOM GRADING EXAMPLE] {ex}")

    # Batch PATCH — UPDATE-only, never INSERT.
    if graded_ids:
        now_iso = datetime.now(timezone.utc).isoformat()
        try:
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

    # Round unit totals.
    result["spread_units"] = round(result["spread_units"], 2)
    result["total_units"] = round(result["total_units"], 2)
    result["ml_units"] = round(result["ml_units"], 2)

    # Log summary.
    sw, sl = result["spread_wins"], result["spread_losses"]
    tw, tl = result["total_wins"], result["total_losses"]
    mw, ml_ = result["ml_wins"], result["ml_losses"]
    sp = f"{sw / (sw + sl) * 100:.0f}%" if (sw + sl) > 0 else "N/A"
    tp = f"{tw / (tw + tl) * 100:.0f}%" if (tw + tl) > 0 else "N/A"
    mp = f"{mw / (mw + ml_) * 100:.0f}%" if (mw + ml_) > 0 else "N/A"
    su = f"{result['spread_units']:+.2f}u"
    tu = f"{result['total_units']:+.2f}u"
    mu = f"{result['ml_units']:+.2f}u"
    print(
        f"  [KENPOM GRADING] Graded {result['graded']} games — "
        f"Spread: {sw}-{sl} ({sp}, {su}), Total: {tw}-{tl} ({tp}, {tu}), ML: {mw}-{ml_} ({mp}, {mu})"
    )

    return result


# ---------------------------------------------------------------------------
# Startup repair — fix graded rows with missing unit results
# ---------------------------------------------------------------------------

def repair_kenpom_units(db_client: Any) -> dict[str, Any]:
    """Repair graded kenpom_snapshots that have NULL or zero unit results.

    Called ONCE at scanner startup. Backfills missing Pinnacle data first,
    then recalculates unit P/L for every graded row where units are missing.

    Steps:
        1. Backfill missing Pinnacle data from pinnacle_odds_history / line_movements.
        2. Recalculate spread_unit_result, total_unit_result, ml_unit_result.
        3. PATCH each row in the DB.

    Returns summary dict with counts and total units.
    """
    summary: dict[str, Any] = {
        "pinnacle_backfilled": 0,
        "units_repaired": 0,
        "spread_units_total": 0.0,
        "total_units_total": 0.0,
        "ml_units_total": 0.0,
        "examples": [],
    }

    if db_client is None:
        print("  [KENPOM REPAIR] Skipped — no DB client.")
        return summary

    if not _ensure_table(db_client):
        print("  [KENPOM REPAIR] Skipped — table not found.")
        return summary

    # -----------------------------------------------------------------------
    # Step 1: Fetch all graded rows that might need repair.
    # -----------------------------------------------------------------------
    try:
        all_graded = db_client._get(
            "kenpom_snapshots",
            select="id,game_id,snapshot_date,home_team,away_team,"
                   "kp_projected_spread,kp_projected_total,kp_home_win_prob,"
                   "pinnacle_spread_home,pinnacle_total,spread_edge,total_edge,ml_edge,"
                   "pinnacle_spread_home_odds,pinnacle_spread_away_odds,"
                   "pinnacle_over_odds,pinnacle_under_odds,"
                   "pinnacle_home_ml,pinnacle_away_ml,"
                   "result_home_score,result_away_score,"
                   "result_spread_correct,result_total_correct,result_ml_correct,"
                   "spread_unit_result,total_unit_result,ml_unit_result",
            filters={"graded": "eq.true"},
        )
    except Exception as e:
        print(f"  [KENPOM REPAIR] Failed to fetch graded snapshots: {e}")
        return summary

    if not all_graded:
        print("  [KENPOM REPAIR] No graded snapshots found.")
        return summary

    # Filter to rows needing repair: any unit result is NULL or 0.
    needs_repair = [
        r for r in all_graded
        if (r.get("spread_unit_result") is None or r.get("spread_unit_result") == 0)
        or (r.get("total_unit_result") is None or r.get("total_unit_result") == 0)
        or (r.get("ml_unit_result") is None or r.get("ml_unit_result") == 0)
    ]

    print(
        f"  [KENPOM REPAIR] {len(all_graded)} graded total, "
        f"{len(needs_repair)} need unit repair"
    )

    if not needs_repair:
        return summary

    # -----------------------------------------------------------------------
    # Step 2: Backfill missing Pinnacle data BEFORE calculating units.
    # -----------------------------------------------------------------------
    missing_pin = [r for r in needs_repair if r.get("pinnacle_spread_home") is None]
    if missing_pin:
        print(f"  [KENPOM REPAIR] {len(missing_pin)} rows missing Pinnacle spread — backfilling...")
        backfilled = _backfill_pinnacle_for_grading(db_client, missing_pin)
        summary["pinnacle_backfilled"] = backfilled
        if backfilled:
            print(f"  [KENPOM REPAIR] Backfilled Pinnacle data for {backfilled} games")

    # -----------------------------------------------------------------------
    # Step 3: Recalculate unit results and PATCH each row.
    # -----------------------------------------------------------------------
    now_iso = datetime.now(timezone.utc).isoformat()
    examples_collected = 0

    for snap in needs_repair:
        row_id = snap.get("id")
        if row_id is None:
            continue

        spread_edge = snap.get("spread_edge")
        total_edge = snap.get("total_edge")
        kp_wp = snap.get("kp_home_win_prob")
        spread_correct = snap.get("result_spread_correct")
        total_correct = snap.get("result_total_correct")
        ml_correct = snap.get("result_ml_correct")

        # Spread unit: bet on the side KP recommends.
        if spread_edge is not None and spread_edge > 0:
            s_odds = snap.get("pinnacle_spread_home_odds") or -110
        elif spread_edge is not None and spread_edge < 0:
            s_odds = snap.get("pinnacle_spread_away_odds") or -110
        else:
            s_odds = None
        spread_units = _calc_unit_result(s_odds, spread_correct)

        # Total unit: over or under at those odds.
        if total_edge is not None and total_edge > 0:
            t_odds = snap.get("pinnacle_over_odds") or -110
        elif total_edge is not None and total_edge < 0:
            t_odds = snap.get("pinnacle_under_odds") or -110
        else:
            t_odds = None
        total_units = _calc_unit_result(t_odds, total_correct)

        # ML unit: home or away ML — no default, skip if NULL.
        if kp_wp is not None and kp_wp > 0.5:
            ml_odds = snap.get("pinnacle_home_ml")
        elif kp_wp is not None and kp_wp < 0.5:
            ml_odds = snap.get("pinnacle_away_ml")
        else:
            ml_odds = None
        ml_units = _calc_unit_result(ml_odds, ml_correct)

        update: dict[str, Any] = {"updated_at": now_iso}
        changed = False

        # Only update fields that were NULL or 0.
        old_su = snap.get("spread_unit_result")
        if (old_su is None or old_su == 0) and spread_units is not None:
            update["spread_unit_result"] = spread_units
            changed = True

        old_tu = snap.get("total_unit_result")
        if (old_tu is None or old_tu == 0) and total_units is not None:
            update["total_unit_result"] = total_units
            changed = True

        old_mu = snap.get("ml_unit_result")
        if (old_mu is None or old_mu == 0) and ml_units is not None:
            update["ml_unit_result"] = ml_units
            changed = True

        if not changed:
            continue

        try:
            db_client._http.patch(
                f"{db_client.base_url}/kenpom_snapshots",
                headers={**db_client.headers, "Prefer": "return=minimal"},
                params={"id": f"eq.{row_id}"},
                json=update,
                timeout=15,
            )
            summary["units_repaired"] += 1
        except Exception as e:
            print(f"  [KENPOM REPAIR] PATCH failed for {snap.get('game_id')}: {e}")
            continue

        # Track totals.
        if spread_units is not None:
            summary["spread_units_total"] += spread_units
        if total_units is not None:
            summary["total_units_total"] += total_units
        if ml_units is not None:
            summary["ml_units_total"] += ml_units

        # Log first 3 examples.
        if examples_collected < 3:
            home = snap.get("home_team", "Home")
            away = snap.get("away_team", "Away")
            su_str = f"{spread_units:+.2f}u" if spread_units is not None else "N/A"
            tu_str = f"{total_units:+.2f}u" if total_units is not None else "N/A"
            mu_str = f"{ml_units:+.2f}u" if ml_units is not None else "N/A"
            ex = (
                f"{away} @ {home}: "
                f"spread={spread_correct} @{s_odds}→{su_str}, "
                f"total={total_correct} @{t_odds}→{tu_str}, "
                f"ml={ml_correct} @{ml_odds}→{mu_str}"
            )
            summary["examples"].append(ex)
            print(f"  [KENPOM REPAIR EXAMPLE] {ex}")
            examples_collected += 1

    # Round totals.
    summary["spread_units_total"] = round(summary["spread_units_total"], 2)
    summary["total_units_total"] = round(summary["total_units_total"], 2)
    summary["ml_units_total"] = round(summary["ml_units_total"], 2)

    print(
        f"  [KENPOM REPAIR] Repaired {summary['units_repaired']} rows — "
        f"Spread: {summary['spread_units_total']:+.2f}u, "
        f"Total: {summary['total_units_total']:+.2f}u, "
        f"ML: {summary['ml_units_total']:+.2f}u"
    )

    return summary
