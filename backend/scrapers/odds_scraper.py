#!/usr/bin/env python3
"""Multi-sport odds pipeline - fetches odds, calculates no-vig lines, finds +EV bets.

Iterates configured sports from ODDS_API_SPORT_KEYS, fetches odds for each,
stores every pull (games, odds_snapshots, true_lines, ev_opportunities) in
Supabase, and prints results to the console.

Usage:
    python backend/scrapers/odds_scraper.py              # all configured sports
    python backend/scrapers/odds_scraper.py NBA NFL       # specific sports only
"""

import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone

# Allow running as a standalone script from the repo root.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "shared"))

from dotenv import load_dotenv

from models.ev_calculator import (
    american_to_implied_prob,
    calculate_ev,
    calculate_no_vig_probability,
)
from models.kelly import kelly_fraction
from scrapers.odds.odds_api import Game, Market, fetch_odds

from config import ODDS_API_SPORT_KEYS, SHARP_BOOKS, SPORT_DISPLAY_NAMES

# Only surface bets with EV above this threshold.
MIN_EV_THRESHOLD = 1.0

# Default Kelly fraction (quarter Kelly).
DEFAULT_KELLY_FRACTION = 0.25

# Default bankroll units for recommended-units sizing.
DEFAULT_BANKROLL_UNITS = 100.0


@dataclass
class EVOpportunity:
    game_id: str
    sport_key: str
    game: str
    commence_time: str
    market: str
    selection: str
    point: float | None
    book: str
    book_key: str
    book_odds: int
    book_implied_prob: float
    true_prob: float
    ev_pct: float
    kelly_pct: float


def find_sharp_book(game: Game) -> str | None:
    """Return the key of the sharpest available bookmaker for a game."""
    book_keys = {bk.key for bk in game.bookmakers}
    for sharp in SHARP_BOOKS:
        if sharp in book_keys:
            return sharp
    return None


def get_market(bookmaker_markets: list[Market], market_key: str) -> Market | None:
    """Find a specific market from a bookmaker's market list."""
    for m in bookmaker_markets:
        if m.key == market_key:
            return m
    return None


def build_sharp_line_map(
    sharp_market: Market,
) -> dict[tuple[str, float | None], float]:
    """Build a map of (selection_name, point) -> true probability from sharp odds.

    For two-outcome markets the probabilities come from no-vig devigging.
    """
    outcomes = sharp_market.outcomes
    if len(outcomes) != 2:
        return {}

    true_a, true_b = calculate_no_vig_probability(
        outcomes[0].price, outcomes[1].price
    )
    return {
        (outcomes[0].name, outcomes[0].point): true_a,
        (outcomes[1].name, outcomes[1].point): true_b,
    }


def scan_game(game: Game) -> list[EVOpportunity]:
    """Scan a single game for +EV opportunities across all books and markets."""
    sharp_key = find_sharp_book(game)
    if sharp_key is None:
        return []

    sharp_bk = next(bk for bk in game.bookmakers if bk.key == sharp_key)
    game_label = f"{game.away_team} @ {game.home_team}"
    opportunities: list[EVOpportunity] = []

    for market_key in ("h2h", "spreads", "totals"):
        sharp_market = get_market(sharp_bk.markets, market_key)
        if sharp_market is None:
            continue

        true_probs = build_sharp_line_map(sharp_market)
        if not true_probs:
            continue

        for bk in game.bookmakers:
            if bk.key == sharp_key:
                continue

            book_market = get_market(bk.markets, market_key)
            if book_market is None:
                continue

            for outcome in book_market.outcomes:
                # For spreads/totals, only compare when the line matches.
                lookup_key = (outcome.name, outcome.point)
                true_prob = true_probs.get(lookup_key)
                if true_prob is None:
                    continue

                ev_pct = calculate_ev(outcome.price, true_prob)
                if ev_pct < MIN_EV_THRESHOLD:
                    continue

                kelly_pct = kelly_fraction(
                    true_prob, outcome.price, DEFAULT_KELLY_FRACTION
                )

                opportunities.append(
                    EVOpportunity(
                        game_id=game.id,
                        sport_key=game.sport_key,
                        game=game_label,
                        commence_time=game.commence_time,
                        market=market_key,
                        selection=outcome.name,
                        point=outcome.point,
                        book=bk.title,
                        book_key=bk.key,
                        book_odds=outcome.price,
                        book_implied_prob=american_to_implied_prob(outcome.price),
                        true_prob=true_prob,
                        ev_pct=ev_pct,
                        kelly_pct=kelly_pct,
                    )
                )

    return opportunities


# ---------------------------------------------------------------------------
# Database persistence
# ---------------------------------------------------------------------------

def store_games(db_client: object, games: list[Game]) -> None:
    """Upsert all games into the database."""
    from db import upsert_game

    for game in games:
        upsert_game(
            db_client,
            game_id=game.id,
            sport=game.sport_key,
            home_team=game.home_team,
            away_team=game.away_team,
            start_time=game.commence_time,
        )


def store_line_movements(db_client: object, games: list[Game]) -> None:
    """Record line movements for ALL bookmaker/game/market/side combos.

    Compares current odds to the most recent row for each combo.  If odds
    changed, insert with ``previous_odds`` / ``odds_change``.  If odds are
    the same, skip the insert to save space.
    """
    from db import get_latest_odds_for_game, bulk_insert_line_movements

    scan_ts = datetime.now(timezone.utc).isoformat()
    rows: list[dict] = []

    for game in games:
        # Fetch existing latest odds for this game (all combos).
        try:
            existing = get_latest_odds_for_game(db_client, game.id)
        except Exception:
            existing = []

        # Build lookup: (bookmaker, market_type, side) -> latest odds
        latest_map: dict[tuple[str, str, str], float] = {}
        seen: set[tuple[str, str, str]] = set()
        for row in existing:
            key = (row["bookmaker"], row["market_type"], row["side"])
            if key not in seen:
                latest_map[key] = float(row["odds"])
                seen.add(key)

        for bk in game.bookmakers:
            for mkt in bk.markets:
                for outcome in mkt.outcomes:
                    side = outcome.name + (
                        f" {outcome.point}" if outcome.point is not None else ""
                    )
                    key = (bk.key, mkt.key, side)
                    current_odds = float(outcome.price)
                    prev = latest_map.get(key)

                    # Skip if odds unchanged.
                    if prev is not None and prev == current_odds:
                        continue

                    row: dict = {
                        "game_id": game.id,
                        "sport": game.sport_key,
                        "bookmaker": bk.key,
                        "market_type": mkt.key,
                        "side": side,
                        "odds": current_odds,
                        "timestamp": scan_ts,
                    }
                    if prev is not None:
                        row["previous_odds"] = prev
                        row["odds_change"] = current_odds - prev
                    rows.append(row)

    if rows:
        bulk_insert_line_movements(db_client, rows)
        print(f"  Line movements: {len(rows)} changes recorded.")
    else:
        print("  Line movements: no changes detected.")


def store_odds_snapshots(db_client: object, games: list[Game]) -> None:
    """Store raw odds from every sportsbook/market combination."""
    from db import insert_odds_snapshot

    for game in games:
        for bk in game.bookmakers:
            for mkt in bk.markets:
                if len(mkt.outcomes) != 2:
                    continue
                home_out = mkt.outcomes[0]
                away_out = mkt.outcomes[1]
                insert_odds_snapshot(
                    db_client,
                    game_id=game.id,
                    sportsbook=bk.key,
                    market_type=mkt.key,
                    home_odds=home_out.price,
                    away_odds=away_out.price,
                    spread_value=home_out.point if mkt.key == "spreads" else None,
                    total_value=home_out.point if mkt.key == "totals" else None,
                )


def store_true_lines(db_client: object, games: list[Game]) -> None:
    """Devig sharp lines and store true probabilities."""
    from db import insert_true_line

    for game in games:
        sharp_key = find_sharp_book(game)
        if sharp_key is None:
            continue
        sharp_bk = next(bk for bk in game.bookmakers if bk.key == sharp_key)

        for market_key in ("h2h", "spreads", "totals"):
            sharp_market = get_market(sharp_bk.markets, market_key)
            if sharp_market is None or len(sharp_market.outcomes) != 2:
                continue
            true_home, true_away = calculate_no_vig_probability(
                sharp_market.outcomes[0].price,
                sharp_market.outcomes[1].price,
            )
            no_vig_line = sharp_market.outcomes[0].point
            insert_true_line(
                db_client,
                game_id=game.id,
                market_type=market_key,
                true_home_prob=round(true_home, 6),
                true_away_prob=round(true_away, 6),
                sharp_book=sharp_key,
                no_vig_line=no_vig_line,
            )


def store_ev_opportunities(
    db_client: object, opportunities: list[EVOpportunity]
) -> None:
    """Store +EV opportunities in the database via bulk insert.

    All rows share a single timestamp so ``get_latest_ev_opportunities``
    can retrieve the complete batch from one scan.
    """
    from db import bulk_insert_ev_opportunities

    scan_ts = datetime.now(timezone.utc).isoformat()

    rows = []
    for opp in opportunities:
        recommended_units = round(opp.kelly_pct * DEFAULT_BANKROLL_UNITS, 2)
        rows.append({
            "game_id": opp.game_id,
            "sportsbook": opp.book_key,
            "market_type": opp.market,
            "side": opp.selection + (
                f" {opp.point}" if opp.point is not None else ""
            ),
            "book_odds": opp.book_odds,
            "book_implied_prob": round(opp.book_implied_prob, 6),
            "true_prob": round(opp.true_prob, 6),
            "ev_percentage": round(opp.ev_pct, 2),
            "kelly_fraction": round(opp.kelly_pct, 6),
            "recommended_units": recommended_units,
            "status": "open",
            "timestamp": scan_ts,
        })

    bulk_insert_ev_opportunities(db_client, rows)


# ---------------------------------------------------------------------------
# Steam detection
# ---------------------------------------------------------------------------

# Minimum number of books moving same direction to trigger a steam alert.
STEAM_MIN_BOOKS = 3
# Only look at line movements from the last N minutes.
STEAM_WINDOW_MINUTES = 30
# Don't create duplicate alerts within this window (minutes).
STEAM_DEDUP_MINUTES = 60


def detect_steam_moves(db_client: object) -> int:
    """Scan recent line movements for steam (3+ books moving same direction).

    Returns the number of new steam alerts created.
    """
    from datetime import timedelta
    from db import (
        SupabaseClient,
        bulk_insert_steam_alerts,
        get_recent_steam_alert_keys,
    )

    client: SupabaseClient = db_client  # type: ignore[assignment]
    now = datetime.now(timezone.utc)
    window_start = (now - timedelta(minutes=STEAM_WINDOW_MINUTES)).isoformat()
    dedup_start = (now - timedelta(minutes=STEAM_DEDUP_MINUTES)).isoformat()

    # 1. Fetch recent line movements that have an actual change.
    recent_moves = client._get(
        "line_movements",
        select="game_id,sport,market_type,side,bookmaker,odds_change,timestamp",
        filters={
            "timestamp": f"gte.{window_start}",
            "odds_change": "not.is.null",
        },
        order="timestamp.asc",
    )
    if not recent_moves:
        return 0

    # 2. Group by (game_id, market_type, side, direction).
    #    direction: "shortened" if odds went down (sharp money ON),
    #               "lengthened" if odds went up (sharp money AGAINST).
    groups: dict[tuple[str, str, str, str, str], list[dict]] = {}
    for mv in recent_moves:
        change = float(mv["odds_change"])
        if change == 0:
            continue
        direction = "shortened" if change < 0 else "lengthened"
        key = (mv["game_id"], mv["sport"], mv["market_type"], mv["side"], direction)
        groups.setdefault(key, []).append(mv)

    # 3. Filter to groups with 3+ distinct bookmakers.
    candidates: list[tuple[tuple, list[dict]]] = []
    for key, moves in groups.items():
        unique_books = {m["bookmaker"] for m in moves}
        if len(unique_books) >= STEAM_MIN_BOOKS:
            candidates.append((key, moves))

    if not candidates:
        return 0

    # 4. Dedup against existing alerts.
    try:
        existing_alerts = get_recent_steam_alert_keys(client, dedup_start)
    except Exception:
        existing_alerts = []

    existing_set: set[tuple[str, str, str]] = set()
    for a in existing_alerts:
        existing_set.add((a["game_id"], a["market_type"], a["side"]))

    # 5. Build new alert rows.
    alert_rows: list[dict] = []
    detected_at = now.isoformat()
    for key, moves in candidates:
        game_id, sport, market_type, side, direction = key
        if (game_id, market_type, side) in existing_set:
            continue

        unique_books = sorted({m["bookmaker"] for m in moves})
        changes = [abs(float(m["odds_change"])) for m in moves]
        magnitude = round(sum(changes) / len(changes), 2)
        first_move = min(m["timestamp"] for m in moves)

        alert_rows.append({
            "game_id": game_id,
            "sport": sport,
            "market_type": market_type,
            "side": side,
            "direction": direction,
            "books_moved": unique_books,
            "magnitude": magnitude,
            "first_move_time": first_move,
            "detected_at": detected_at,
            "status": "active",
        })

    if alert_rows:
        bulk_insert_steam_alerts(client, alert_rows)

    return len(alert_rows)


# ---------------------------------------------------------------------------
# Console output
# ---------------------------------------------------------------------------

def format_american(odds: int) -> str:
    """Format American odds with a leading + for positive values."""
    return f"+{odds}" if odds > 0 else str(odds)


def format_point(market: str, point: float | None) -> str:
    """Format a spread/total point value for display."""
    if point is None:
        return ""
    if market == "spreads":
        return f" ({'+' if point > 0 else ''}{point})"
    if market == "totals":
        return f" ({point})"
    return ""


def sport_display_name(sport_key: str) -> str:
    """Return a human-readable sport name from the API sport key."""
    return SPORT_DISPLAY_NAMES.get(sport_key, sport_key)


def print_sport_results(sport_key: str, opportunities: list[EVOpportunity]) -> None:
    """Print +EV opportunities for a single sport."""
    sport_name = sport_display_name(sport_key)
    if not opportunities:
        print(f"  {sport_name}: no +EV opportunities\n")
        return

    opportunities.sort(key=lambda o: o.ev_pct, reverse=True)

    header = (
        f"{'Game':<40} {'Market':<8} {'Selection':<25} "
        f"{'Book':<20} {'Odds':>7} {'True%':>7} {'Book%':>7} "
        f"{'EV%':>7} {'Kelly%':>7}"
    )
    divider = "-" * len(header)

    print(f"\n  {sport_name}  ({len(opportunities)} opportunities)")
    print(divider)
    print(header)
    print(divider)

    for opp in opportunities:
        sel_display = opp.selection + format_point(opp.market, opp.point)
        print(
            f"{opp.game:<40} {opp.market:<8} {sel_display:<25} "
            f"{opp.book:<20} {format_american(opp.book_odds):>7} "
            f"{opp.true_prob * 100:>6.1f}% {opp.book_implied_prob * 100:>6.1f}% "
            f"{opp.ev_pct:>+6.1f}% {opp.kelly_pct * 100:>6.2f}%"
        )

    print(divider)


def print_results(all_opportunities: list[EVOpportunity]) -> None:
    """Print +EV opportunities grouped by sport with a combined summary."""
    banner_width = 120
    print(f"\n{'=' * banner_width}")
    print(
        f"  RTM +EV Scanner  |  "
        f"{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}  |  "
        f"{len(all_opportunities)} total opportunities"
    )
    print(f"{'=' * banner_width}")

    if not all_opportunities:
        print("\nNo +EV opportunities found across any sport right now.\n")
        return

    # Group by sport.
    sports_seen: list[str] = []
    by_sport: dict[str, list[EVOpportunity]] = {}
    for opp in all_opportunities:
        if opp.sport_key not in by_sport:
            by_sport[opp.sport_key] = []
            sports_seen.append(opp.sport_key)
        by_sport[opp.sport_key].append(opp)

    for sport_key in sports_seen:
        print_sport_results(sport_key, by_sport[sport_key])

    # Best overall.
    best = max(all_opportunities, key=lambda o: o.ev_pct)
    print(
        f"\nBest opportunity: {best.selection} "
        f"({best.game}, {sport_display_name(best.sport_key)}) at {best.book} "
        f"[{format_american(best.book_odds)}] -> {best.ev_pct:+.1f}% EV\n"
    )


# ---------------------------------------------------------------------------
# Sport resolution
# ---------------------------------------------------------------------------

def resolve_sport_keys(cli_args: list[str]) -> list[str]:
    """Determine which sport keys to fetch.

    If CLI args are provided (e.g. "NBA", "NFL"), map them to API keys.
    Otherwise, return all sport keys from ODDS_API_SPORT_KEYS in config.
    """
    if cli_args:
        keys: list[str] = []
        for arg in cli_args:
            api_key = ODDS_API_SPORT_KEYS.get(arg.upper())
            if api_key:
                keys.append(api_key)
            else:
                # Treat as a raw API sport key (e.g. "tennis_atp_french_open").
                keys.append(arg)
        return keys

    keys = list(ODDS_API_SPORT_KEYS.values())
    print(f"Will fetch odds for {len(keys)} sports: {', '.join(sport_display_name(k) for k in keys)}\n")
    return keys


# ---------------------------------------------------------------------------
# Single scan run
# ---------------------------------------------------------------------------

def run_scan(sport_keys: list[str]) -> int:
    """Execute one full scan cycle. Returns the number of opportunities found."""
    # --- Connect to Supabase ---
    db = None
    try:
        from db import get_supabase
        db = get_supabase()
    except Exception as e:
        print(f"Warning: Could not connect to Supabase ({e}). Will skip DB writes.")

    # --- Fetch & process each sport ---
    all_games: list[Game] = []
    all_opportunities: list[EVOpportunity] = []

    for i, sport_key in enumerate(sport_keys):
        if i > 0:
            time.sleep(1)

        display = sport_display_name(sport_key)
        print(f"Fetching {display} odds...")

        try:
            games = fetch_odds(sport_key)
        except Exception as e:
            print(f"  Skipping {display}: {e}")
            continue

        if not games:
            print(f"  {display}: no games available right now.")
            continue

        print(f"  {display}: {len(games)} games found.")
        all_games.extend(games)

        # Persist game data.
        if db is not None:
            try:
                store_games(db, games)
                store_odds_snapshots(db, games)
                store_true_lines(db, games)
            except Exception as e:
                print(f"  Warning: DB write failed for {display} ({e}).")

            # Line movements (separate try so a failure doesn't block EV).
            try:
                store_line_movements(db, games)
            except Exception as e:
                print(f"  Warning: Line movement write failed for {display} ({e}).")

        # Scan for +EV.
        for game in games:
            all_opportunities.extend(scan_game(game))

    # --- Persist EV opportunities ---
    if db is not None and all_opportunities:
        try:
            print(f"\nStoring {len(all_opportunities)} EV opportunities...")
            store_ev_opportunities(db, all_opportunities)
            print(f"All {len(all_opportunities)} opportunities persisted to Supabase.")
        except Exception as e:
            print(f"Warning: Bulk insert failed ({e}), falling back to row-by-row...")
            from db import insert_ev_opportunity

            saved = 0
            scan_ts = datetime.now(timezone.utc).isoformat()
            for opp in all_opportunities:
                try:
                    recommended_units = round(opp.kelly_pct * DEFAULT_BANKROLL_UNITS, 2)
                    insert_ev_opportunity(
                        db,
                        game_id=opp.game_id,
                        sportsbook=opp.book_key,
                        market_type=opp.market,
                        side=opp.selection + (
                            f" {opp.point}" if opp.point is not None else ""
                        ),
                        book_odds=opp.book_odds,
                        book_implied_prob=round(opp.book_implied_prob, 6),
                        true_prob=round(opp.true_prob, 6),
                        ev_percentage=round(opp.ev_pct, 2),
                        kelly_frac=round(opp.kelly_pct, 6),
                        recommended_units=recommended_units,
                    )
                    saved += 1
                except Exception as row_err:
                    print(f"  Skipped row ({opp.game_id}/{opp.book_key}): {row_err}")
            print(f"Fallback complete: {saved}/{len(all_opportunities)} rows saved.")

    # --- Steam detection ---
    if db is not None:
        try:
            new_alerts = detect_steam_moves(db)
            if new_alerts:
                print(f"\nSteam alerts: {new_alerts} new alert(s) detected!")
            else:
                print("\nSteam alerts: no new steam detected.")
        except Exception as e:
            print(f"Warning: Steam detection failed ({e}).")

    # --- Console output ---
    print_results(all_opportunities)
    return len(all_opportunities)


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------

SCAN_INTERVAL_MINUTES = 10


def main() -> None:
    """Run the odds pipeline on a recurring schedule."""
    from apscheduler.schedulers.blocking import BlockingScheduler

    # Load .env from project root.
    dotenv_path = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
    load_dotenv(dotenv_path)

    # Determine which sports to scan.
    cli_sports = sys.argv[1:]
    sport_keys = resolve_sport_keys(cli_sports)

    if not sport_keys:
        print("No active sports found.")
        return

    def scheduled_run() -> None:
        print(f"\n{'#' * 80}")
        print(f"# Scan starting at {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
        print(f"{'#' * 80}\n")

        count = run_scan(sport_keys)

        next_run = scheduler.get_job("odds_scan").next_run_time
        print(
            f"\nScan complete: {count} opportunities found. "
            f"Next run at {next_run.strftime('%H:%M:%S UTC')}.\n"
        )

    scheduler = BlockingScheduler(timezone="UTC")
    scheduler.add_job(
        scheduled_run,
        "interval",
        minutes=SCAN_INTERVAL_MINUTES,
        id="odds_scan",
        next_run_time=datetime.now(timezone.utc),  # run immediately on start
    )

    print(
        f"RTM +EV Scanner started. Running every {SCAN_INTERVAL_MINUTES} minutes. "
        f"Press Ctrl+C to stop.\n"
    )

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        print("\nShutting down scheduler...")
        scheduler.shutdown(wait=False)
        print("Scheduler stopped.")


if __name__ == "__main__":
    main()
