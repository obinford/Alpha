"""Pinnacle Odds History — capture opening and closing lines for CLV analysis.

Stores three snapshot types per game+market:
  - "opening"  — First Pinnacle line we see.  Inserted once, never overwritten.
  - "closing"  — Updated every scan cycle until game tips off.  Frozen at tip-off.
  - "current"  — Same as closing, overwritten each cycle for real-time display.

Usage (scanner integration):
    from intelligence.pinnacle_history import store_pinnacle_history
    store_pinnacle_history(db, games)

Usage (CLV lookup):
    from intelligence.pinnacle_history import get_pinnacle_opening_closing
    data = get_pinnacle_opening_closing(db, game_id, "spreads")
    # -> {opening_line, opening_odds, closing_line, closing_odds, ...}
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from models.ev_calculator import calculate_no_vig_probability


def _parse_commence_time(ct: str) -> datetime:
    """Parse an ISO-8601 commence_time to a timezone-aware datetime."""
    ct = ct.replace("Z", "+00:00")
    return datetime.fromisoformat(ct)


def _game_has_started(commence_time: str) -> bool:
    """Return True if the game has already tipped off."""
    try:
        start = _parse_commence_time(commence_time)
        return datetime.now(timezone.utc) >= start
    except Exception:
        return False


def _build_pinnacle_rows(
    games: list,
    snapshot_type: str,
    today: str,
    now_iso: str,
) -> list[dict]:
    """Extract Pinnacle market data from Game objects into DB rows.

    Args:
        games: list of Game dataclass instances (from odds_api).
        snapshot_type: "opening", "closing", or "current".
        today: snapshot_date as ISO string (YYYY-MM-DD).
        now_iso: captured_at timestamp.

    Returns a list of row dicts ready for upsert.
    """
    rows: list[dict] = []

    for game in games:
        # Find the Pinnacle bookmaker.
        pin_bk = None
        for bk in game.bookmakers:
            if bk.key == "pinnacle":
                pin_bk = bk
                break
        if pin_bk is None:
            continue

        for mkt in pin_bk.markets:
            if mkt.key not in ("h2h", "spreads", "totals"):
                continue
            if len(mkt.outcomes) != 2:
                continue

            out_a, out_b = mkt.outcomes[0], mkt.outcomes[1]

            # Devig to get true probabilities.
            try:
                prob_a, prob_b = calculate_no_vig_probability(
                    out_a.price, out_b.price
                )
            except Exception:
                prob_a, prob_b = None, None

            row: dict[str, Any] = {
                "game_id": game.id,
                "sport": game.sport_key,
                "home_team": game.home_team,
                "away_team": game.away_team,
                "commence_time": game.commence_time,
                "market_type": mkt.key,
                "snapshot_type": snapshot_type,
                "snapshot_date": today,
                "captured_at": now_iso,
            }

            if mkt.key == "h2h":
                # Determine which outcome is home vs away.
                if out_a.name == game.home_team:
                    home_out, away_out = out_a, out_b
                    home_prob, away_prob = prob_a, prob_b
                else:
                    home_out, away_out = out_b, out_a
                    home_prob, away_prob = prob_b, prob_a

                row["line_value"] = None
                row["home_odds"] = home_out.price
                row["away_odds"] = away_out.price
                row["over_odds"] = None
                row["under_odds"] = None
                row["home_prob"] = round(home_prob, 6) if home_prob else None
                row["away_prob"] = round(away_prob, 6) if away_prob else None

            elif mkt.key == "spreads":
                # Identify which outcome is home.
                if out_a.name == game.home_team:
                    home_out, away_out = out_a, out_b
                    home_prob, away_prob = prob_a, prob_b
                else:
                    home_out, away_out = out_b, out_a
                    home_prob, away_prob = prob_b, prob_a

                row["line_value"] = home_out.point
                row["home_odds"] = home_out.price
                row["away_odds"] = away_out.price
                row["over_odds"] = None
                row["under_odds"] = None
                row["home_prob"] = round(home_prob, 6) if home_prob else None
                row["away_prob"] = round(away_prob, 6) if away_prob else None

            elif mkt.key == "totals":
                # Identify Over vs Under.
                if out_a.name.lower() == "over":
                    over_out, under_out = out_a, out_b
                    over_prob, under_prob = prob_a, prob_b
                else:
                    over_out, under_out = out_b, out_a
                    over_prob, under_prob = prob_b, prob_a

                row["line_value"] = over_out.point
                row["home_odds"] = None
                row["away_odds"] = None
                row["over_odds"] = over_out.price
                row["under_odds"] = under_out.price
                row["home_prob"] = round(over_prob, 6) if over_prob else None
                row["away_prob"] = round(under_prob, 6) if under_prob else None

            rows.append(row)

    return rows


def store_pinnacle_history(db: Any, games: list) -> None:
    """Capture Pinnacle opening and closing lines from the current scan cycle.

    Called once per scan from odds_scraper after Pinnacle data is loaded.

    For every game where Pinnacle has odds:
      a. OPENING: Check if "opening" row exists. If not, insert it.
         Never overwrite opening lines.
      b. CLOSING: Upsert "closing" row for today.  Skip if game has started
         (closing line lock — the last pre-tip-off value is the true closing).

    Logs a summary: "[PINNACLE HISTORY] Stored X opening lines, updated Y
    closing lines across Z games"
    """
    now = datetime.now(timezone.utc)
    today = now.date().isoformat()
    now_iso = now.isoformat()

    # Separate games into started vs not-started for closing line lock.
    not_started_games = [
        g for g in games if not _game_has_started(g.commence_time)
    ]

    # Build rows for all games (opening check) and not-started (closing).
    all_rows = _build_pinnacle_rows(games, "opening", today, now_iso)
    closing_rows = _build_pinnacle_rows(not_started_games, "closing", today, now_iso)

    if not all_rows and not closing_rows:
        return

    # --- Opening lines: only insert if no opening row exists yet ---
    opening_inserted = 0
    if all_rows:
        # Batch-check which opening rows already exist.
        game_ids = list({r["game_id"] for r in all_rows})
        existing_openings: set[tuple[str, str]] = set()  # (game_id, market_type)
        for i in range(0, len(game_ids), 50):
            chunk = game_ids[i : i + 50]
            id_list = ",".join(chunk)
            try:
                rows = db._get(
                    "pinnacle_odds_history",
                    select="game_id,market_type",
                    filters={
                        "game_id": f"in.({id_list})",
                        "snapshot_type": "eq.opening",
                    },
                )
                for r in rows:
                    existing_openings.add((r["game_id"], r["market_type"]))
            except Exception:
                pass

        new_openings = [
            r for r in all_rows
            if (r["game_id"], r["market_type"]) not in existing_openings
        ]
        # Set snapshot_type to opening for insertion.
        for r in new_openings:
            r["snapshot_type"] = "opening"

        if new_openings:
            try:
                db._upsert_many(
                    "pinnacle_odds_history",
                    new_openings,
                    on_conflict="game_id,market_type,snapshot_type,snapshot_date",
                )
                opening_inserted = len(new_openings)
            except Exception as e:
                print(f"  [PINNACLE HISTORY] Opening insert failed: {e}")

    # --- Closing lines: upsert for not-started games ---
    closing_updated = 0
    if closing_rows:
        for r in closing_rows:
            r["snapshot_type"] = "closing"
        try:
            db._upsert_many(
                "pinnacle_odds_history",
                closing_rows,
                on_conflict="game_id,market_type,snapshot_type,snapshot_date",
            )
            closing_updated = len(closing_rows)
        except Exception as e:
            print(f"  [PINNACLE HISTORY] Closing upsert failed: {e}")

    games_with_pin = len({r["game_id"] for r in all_rows})
    print(
        f"  [PINNACLE HISTORY] Stored {opening_inserted} opening lines, "
        f"updated {closing_updated} closing lines across {games_with_pin} games"
    )


def get_pinnacle_opening_closing(
    db: Any,
    game_id: str,
    market_type: str,
) -> dict[str, Any] | None:
    """Retrieve Pinnacle opening and closing line data for CLV analysis.

    Returns:
        {
            "opening_line": float | None,
            "opening_home_odds": int | None,
            "opening_away_odds": int | None,
            "opening_home_prob": float | None,
            "closing_line": float | None,
            "closing_home_odds": int | None,
            "closing_away_odds": int | None,
            "closing_home_prob": float | None,
            "line_movement": float | None,  # closing - opening (for spreads/totals)
        }
        or None if no data found.
    """
    try:
        rows = db._get(
            "pinnacle_odds_history",
            select="snapshot_type,line_value,home_odds,away_odds,"
                   "over_odds,under_odds,home_prob,away_prob",
            filters={
                "game_id": f"eq.{game_id}",
                "market_type": f"eq.{market_type}",
                "snapshot_type": "in.(opening,closing)",
            },
        )
    except Exception:
        return None

    if not rows:
        return None

    opening = next((r for r in rows if r["snapshot_type"] == "opening"), None)
    closing = next((r for r in rows if r["snapshot_type"] == "closing"), None)

    result: dict[str, Any] = {
        "opening_line": None,
        "opening_home_odds": None,
        "opening_away_odds": None,
        "opening_home_prob": None,
        "closing_line": None,
        "closing_home_odds": None,
        "closing_away_odds": None,
        "closing_home_prob": None,
        "line_movement": None,
    }

    if opening:
        result["opening_line"] = opening.get("line_value")
        result["opening_home_odds"] = opening.get("home_odds") or opening.get("over_odds")
        result["opening_away_odds"] = opening.get("away_odds") or opening.get("under_odds")
        result["opening_home_prob"] = opening.get("home_prob")

    if closing:
        result["closing_line"] = closing.get("line_value")
        result["closing_home_odds"] = closing.get("home_odds") or closing.get("over_odds")
        result["closing_away_odds"] = closing.get("away_odds") or closing.get("under_odds")
        result["closing_home_prob"] = closing.get("home_prob")

    # Line movement (for spreads/totals only).
    if (
        result["opening_line"] is not None
        and result["closing_line"] is not None
    ):
        result["line_movement"] = round(
            result["closing_line"] - result["opening_line"], 1
        )

    return result


def backfill_from_line_movements(
    db: Any,
    game_ids: list[str],
    home_team_by_gid: dict[str, str],
    game_info: dict[str, dict],
) -> tuple[int, int]:
    """Backfill pinnacle_odds_history from the line_movements table.

    For each game, finds the earliest and latest Pinnacle entries in
    line_movements and stores them as "opening" and "closing" snapshots.

    Args:
        game_ids: game IDs to backfill.
        home_team_by_gid: {game_id: home_team_name} for side identification.
        game_info: {game_id: {sport, home_team, away_team, start_time}} metadata.

    Returns (opening_count, closing_count).
    """
    opening_count = 0
    closing_count = 0

    # Check which rows already exist.
    existing_keys: set[tuple[str, str, str]] = set()  # (game_id, market_type, snapshot_type)
    for i in range(0, len(game_ids), 50):
        chunk = game_ids[i : i + 50]
        id_list = ",".join(chunk)
        try:
            rows = db._get(
                "pinnacle_odds_history",
                select="game_id,market_type,snapshot_type",
                filters={
                    "game_id": f"in.({id_list})",
                    "snapshot_type": "in.(opening,closing)",
                },
            )
            for r in rows:
                existing_keys.add((r["game_id"], r["market_type"], r["snapshot_type"]))
        except Exception:
            pass

    # Fetch ALL Pinnacle line movements for these games.
    all_movements: list[dict] = []
    for i in range(0, len(game_ids), 50):
        chunk = game_ids[i : i + 50]
        id_list = ",".join(chunk)
        try:
            rows = db._get(
                "line_movements",
                select="game_id,market_type,side,odds,timestamp",
                filters={
                    "game_id": f"in.({id_list})",
                    "bookmaker": "eq.pinnacle",
                },
                order="timestamp.asc",
            )
            all_movements.extend(rows)
        except Exception:
            pass

    if not all_movements:
        return 0, 0

    # Group by (game_id, market_type) and find earliest/latest per side.
    # Structure: {(game_id, market_type): [movements_ordered_by_time]}
    grouped: dict[tuple[str, str], list[dict]] = {}
    for mv in all_movements:
        key = (mv["game_id"], mv["market_type"])
        grouped.setdefault(key, []).append(mv)

    opening_rows: list[dict] = []
    closing_rows: list[dict] = []

    for (gid, market_type), movements in grouped.items():
        info = game_info.get(gid, {})
        home_team = home_team_by_gid.get(gid, "")
        sport = info.get("sport", "basketball_ncaab")
        away_team = info.get("away_team", "")
        commence_time = info.get("start_time")

        # movements are ordered by timestamp asc (earliest first).
        earliest = movements[0]
        latest = movements[-1]

        # Collect all movements for this game+market to build opening/closing.
        # For h2h and spreads we need two sides (home and away).
        # For totals we need Over and Under.
        earliest_by_side: dict[str, dict] = {}
        latest_by_side: dict[str, dict] = {}
        for mv in movements:
            side = mv["side"]
            if side not in earliest_by_side:
                earliest_by_side[side] = mv
            latest_by_side[side] = mv  # last one wins since sorted asc

        def _build_row(
            side_data: dict[str, dict], snap_type: str, ts: str,
        ) -> dict | None:
            snap_date = ts[:10] if ts else date.today().isoformat()

            if market_type == "h2h":
                home_mv = None
                away_mv = None
                for side, mv in side_data.items():
                    if side == home_team:
                        home_mv = mv
                    else:
                        away_mv = mv
                if not home_mv or not away_mv:
                    return None
                home_odds = int(home_mv["odds"])
                away_odds = int(away_mv["odds"])
                try:
                    hp, ap = calculate_no_vig_probability(home_odds, away_odds)
                except Exception:
                    hp, ap = None, None
                return {
                    "game_id": gid, "sport": sport,
                    "home_team": home_team, "away_team": away_team,
                    "commence_time": commence_time,
                    "market_type": market_type,
                    "line_value": None,
                    "home_odds": home_odds, "away_odds": away_odds,
                    "over_odds": None, "under_odds": None,
                    "home_prob": round(hp, 6) if hp else None,
                    "away_prob": round(ap, 6) if ap else None,
                    "snapshot_type": snap_type,
                    "snapshot_date": snap_date,
                    "captured_at": ts,
                }

            elif market_type == "spreads":
                home_mv = None
                away_mv = None
                for side, mv in side_data.items():
                    parts = side.rsplit(" ", 1)
                    if len(parts) == 2 and parts[0] == home_team:
                        home_mv = mv
                    elif len(parts) == 2:
                        away_mv = mv
                if not home_mv or not away_mv:
                    return None
                home_odds = int(home_mv["odds"])
                away_odds = int(away_mv["odds"])
                # Extract spread from the side string.
                home_parts = home_mv["side"].rsplit(" ", 1)
                try:
                    line_val = float(home_parts[1])
                except (ValueError, IndexError):
                    line_val = None
                try:
                    hp, ap = calculate_no_vig_probability(home_odds, away_odds)
                except Exception:
                    hp, ap = None, None
                return {
                    "game_id": gid, "sport": sport,
                    "home_team": home_team, "away_team": away_team,
                    "commence_time": commence_time,
                    "market_type": market_type,
                    "line_value": line_val,
                    "home_odds": home_odds, "away_odds": away_odds,
                    "over_odds": None, "under_odds": None,
                    "home_prob": round(hp, 6) if hp else None,
                    "away_prob": round(ap, 6) if ap else None,
                    "snapshot_type": snap_type,
                    "snapshot_date": snap_date,
                    "captured_at": ts,
                }

            elif market_type == "totals":
                over_mv = None
                under_mv = None
                for side, mv in side_data.items():
                    if side.lower().startswith("over"):
                        over_mv = mv
                    elif side.lower().startswith("under"):
                        under_mv = mv
                if not over_mv or not under_mv:
                    return None
                over_odds = int(over_mv["odds"])
                under_odds = int(under_mv["odds"])
                # Extract total from Over side.
                over_parts = over_mv["side"].rsplit(" ", 1)
                try:
                    line_val = float(over_parts[1])
                except (ValueError, IndexError):
                    line_val = None
                try:
                    op, up = calculate_no_vig_probability(over_odds, under_odds)
                except Exception:
                    op, up = None, None
                return {
                    "game_id": gid, "sport": sport,
                    "home_team": home_team, "away_team": away_team,
                    "commence_time": commence_time,
                    "market_type": market_type,
                    "line_value": line_val,
                    "home_odds": None, "away_odds": None,
                    "over_odds": over_odds, "under_odds": under_odds,
                    "home_prob": round(op, 6) if op else None,
                    "away_prob": round(up, 6) if up else None,
                    "snapshot_type": snap_type,
                    "snapshot_date": snap_date,
                    "captured_at": ts,
                }

            return None

        # Build opening row (from earliest movements).
        if (gid, market_type, "opening") not in existing_keys:
            ts = earliest["timestamp"]
            row = _build_row(earliest_by_side, "opening", ts)
            if row:
                opening_rows.append(row)

        # Build closing row (from latest movements).
        if (gid, market_type, "closing") not in existing_keys:
            ts = latest["timestamp"]
            row = _build_row(latest_by_side, "closing", ts)
            if row:
                closing_rows.append(row)

    # Batch insert.
    if opening_rows:
        try:
            db._upsert_many(
                "pinnacle_odds_history",
                opening_rows,
                on_conflict="game_id,market_type,snapshot_type,snapshot_date",
            )
            opening_count = len(opening_rows)
        except Exception as e:
            print(f"  [PINNACLE BACKFILL] Opening insert failed: {e}")

    if closing_rows:
        try:
            db._upsert_many(
                "pinnacle_odds_history",
                closing_rows,
                on_conflict="game_id,market_type,snapshot_type,snapshot_date",
            )
            closing_count = len(closing_rows)
        except Exception as e:
            print(f"  [PINNACLE BACKFILL] Closing insert failed: {e}")

    return opening_count, closing_count
