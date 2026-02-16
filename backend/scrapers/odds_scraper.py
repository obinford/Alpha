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
from datetime import datetime, timedelta, timezone

# Allow running as a standalone script from the repo root.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "shared"))

from dotenv import load_dotenv

from models.ev_calculator import (
    american_to_implied_prob,
    calculate_ev,
    calculate_no_vig_probability,
)
from models.devig import devig_market, devig_pair as devig_pair_new, DevigResult, select_devig_source, BookOdds
from models.kelly import kelly_fraction
from scrapers.odds.odds_api import Game, Market, fetch_odds

from config import (
    ODDS_API_SPORT_KEYS, SHARP_BOOKS, SPORT_DISPLAY_NAMES,
    ALL_MARKETS, PROP_MARKETS, MARKETS, ODDS_API_REGIONS,
    get_prop_markets_for_sport,
    MIN_EV_THRESHOLD, DEFAULT_KELLY_FRACTION,
    DEFAULT_BANKROLL_UNITS, PROP_WINDOW_HOURS,
    STEAM_MIN_BOOKS, STEAM_WINDOW_MINUTES, STEAM_DEDUP_MINUTES,
    SCAN_INTERVAL_MINUTES,
)
from books import get_book_tier, get_book_name, get_book_info


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
    devig_source: str = ""
    devig_confidence: str = ""
    devig_method: str = "multiplicative"


def parse_commence_time(ct: str) -> datetime:
    """Parse an ISO-8601 commence_time string to a timezone-aware datetime."""
    ct = ct.replace("Z", "+00:00")
    return datetime.fromisoformat(ct)


def hours_until_start(game: Game) -> float:
    """Return the number of hours until a game starts. Negative = already started."""
    try:
        start = parse_commence_time(game.commence_time)
        delta = start - datetime.now(timezone.utc)
        return delta.total_seconds() / 3600
    except Exception:
        return 0.0


def game_date_label(game: Game) -> str:
    """Return a human-readable date label for grouping (TODAY, TOMORROW, day name)."""
    try:
        start = parse_commence_time(game.commence_time)
        now = datetime.now(timezone.utc)
        today = now.date()
        game_date = start.date()
        if game_date == today:
            return "TODAY"
        elif game_date == today + timedelta(days=1):
            return "TOMORROW"
        else:
            return start.strftime("%A %b %d").upper()
    except Exception:
        return "UNKNOWN"


def has_games_within(games: list[Game], hours: float) -> bool:
    """Return True if any game starts within the given number of hours."""
    for g in games:
        h = hours_until_start(g)
        if h <= hours and h > -3:  # include games that started up to 3h ago
            return True
    return False


def merge_prop_data(mainline_games: list[Game], prop_games: list[Game]) -> None:
    """Merge prop market data from a second API call into existing game objects."""
    prop_map = {g.id: g for g in prop_games}
    for game in mainline_games:
        prop_game = prop_map.get(game.id)
        if not prop_game:
            continue
        existing_keys = {m.key for bk in game.bookmakers for m in bk.markets}
        bk_map = {bk.key: bk for bk in game.bookmakers}
        for prop_bk in prop_game.bookmakers:
            target_bk = bk_map.get(prop_bk.key)
            if target_bk is None:
                game.bookmakers.append(prop_bk)
            else:
                for mkt in prop_bk.markets:
                    if mkt.key not in existing_keys:
                        target_bk.markets.append(mkt)


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
    LEGACY: used when only a single sharp book is available.
    Prefer build_devig_line_map for the hierarchical approach.
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


def _extract_market_odds_by_book(
    game: Game, market_key: str,
) -> tuple[dict[str, tuple[int, int]], list | None]:
    """Extract {book_key: (odds_a, odds_b)} for a two-outcome market across all books.

    Returns (book_odds_dict, outcome_names) where outcome_names is
    [name_a, name_b, point_a, point_b] from the first book found.
    """
    book_odds: dict[str, tuple[int, int]] = {}
    outcome_info: list | None = None

    for bk in game.bookmakers:
        mkt = get_market(bk.markets, market_key)
        if mkt is None or len(mkt.outcomes) != 2:
            continue
        book_odds[bk.key] = (mkt.outcomes[0].price, mkt.outcomes[1].price)
        if outcome_info is None:
            outcome_info = [
                mkt.outcomes[0].name, mkt.outcomes[1].name,
                mkt.outcomes[0].point, mkt.outcomes[1].point,
            ]

    return book_odds, outcome_info


def build_devig_line_map(
    game: Game, market_key: str,
) -> tuple[dict[tuple[str, float | None], float], str, str, str]:
    """Build a true-probability map using the hierarchical devig engine.

    Returns:
        (true_probs, devig_source, devig_confidence, devig_method)
        where true_probs is {(selection_name, point): true_probability}
    """
    book_odds, outcome_info = _extract_market_odds_by_book(game, market_key)
    if not book_odds or outcome_info is None:
        return {}, "", "CAUTION", "multiplicative"

    result = devig_market(book_odds)
    if result is None:
        return {}, "", "CAUTION", "multiplicative"

    name_a, name_b, point_a, point_b = outcome_info
    true_probs = {
        (name_a, point_a): result.true_prob_a,
        (name_b, point_b): result.true_prob_b,
    }
    return true_probs, result.source, result.confidence, result.method


def scan_game(game: Game) -> list[EVOpportunity]:
    """Scan a single game for +EV opportunities across all books and markets.

    Uses the hierarchical devig engine:
      Pinnacle → Exchanges → Sharp consensus → Market average
    The devig source books are excluded from the soft-book comparison loop
    (you don't bet the same book you used to set the true line).
    """
    game_label = f"{game.away_team} @ {game.home_team}"
    opportunities: list[EVOpportunity] = []

    for market_key in ("h2h", "spreads", "totals"):
        true_probs, source, confidence, method = build_devig_line_map(
            game, market_key
        )
        if not true_probs:
            continue

        # Determine which books were used as devig source — don't bet those.
        source_keys: set[str] = set()
        if ":" in source:
            # e.g. "exchange:novig,betfair_ex_eu" or "sharp:circa,betonlineag"
            source_keys = set(source.split(":", 1)[1].split(","))
        elif source and not source.startswith("market_avg"):
            source_keys = {source}

        for bk in game.bookmakers:
            if bk.key in source_keys:
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
                        devig_source=source,
                        devig_confidence=confidence,
                        devig_method=method,
                    )
                )

    return opportunities


def _build_prop_sharp_map(
    sharp_market: Market,
) -> dict[tuple[str, str, float | None], float]:
    """Build (player_name, over_under, point) -> true probability for a prop market.

    Groups outcomes by (description, point) pairs — each pair is an
    Over/Under duo that can be devigged.
    LEGACY: used for single-book devigging. See _build_prop_devig_map.
    """
    # Group outcomes by (description, point) to find Over/Under pairs.
    pairs: dict[tuple[str | None, float | None], list] = {}
    for o in sharp_market.outcomes:
        key = (o.description, o.point)
        pairs.setdefault(key, []).append(o)

    result: dict[tuple[str, str, float | None], float] = {}
    for (_desc, _point), outcomes in pairs.items():
        if len(outcomes) != 2:
            continue
        # Sort so Over comes first for consistent devigging.
        outcomes.sort(key=lambda o: o.name)  # Over < Under alphabetically
        true_a, true_b = calculate_no_vig_probability(
            outcomes[0].price, outcomes[1].price
        )
        for i, o in enumerate(outcomes):
            player = o.description or ""
            result[(player, o.name, o.point)] = true_a if i == 0 else true_b
    return result


def _build_prop_devig_map(
    game: Game, prop_market_key: str,
) -> tuple[dict[tuple[str, str, float | None], float], str, str, str, set[str]]:
    """Build prop true-probability map using hierarchical source selection.

    For each player/line pair, collect Over/Under odds from all books,
    pick the best source via the hierarchy, and devig.

    Returns:
        (true_probs, source, confidence, method, source_keys)
    """
    from models.devig import _PINNACLE_KEYS, _EXCHANGE_KEYS, _SHARP_KEYS

    # Collect all O/U pairs per book per (player, point).
    # Structure: {(desc, point): {book_key: (over_price, under_price)}}
    pair_by_book: dict[tuple[str | None, float | None], dict[str, tuple[int, int]]] = {}

    for bk in game.bookmakers:
        mkt = get_market(bk.markets, prop_market_key)
        if mkt is None:
            continue
        # Group this book's outcomes by (description, point).
        bk_pairs: dict[tuple[str | None, float | None], list] = {}
        for o in mkt.outcomes:
            bk_pairs.setdefault((o.description, o.point), []).append(o)
        for pair_key, outcomes in bk_pairs.items():
            if len(outcomes) != 2:
                continue
            outcomes.sort(key=lambda o: o.name)  # Over first
            pair_by_book.setdefault(pair_key, {})[bk.key] = (
                outcomes[0].price, outcomes[1].price
            )

    result: dict[tuple[str, str, float | None], float] = {}
    best_source = ""
    best_confidence = "CAUTION"
    best_method = "multiplicative"
    all_source_keys: set[str] = set()

    for (desc, point), book_odds in pair_by_book.items():
        devig_result = devig_market(book_odds)
        if devig_result is None:
            continue

        player = desc or ""
        # We need to know which outcome is Over vs Under.
        # Over sorts before Under alphabetically, matching our sort above.
        result[(player, "Over", point)] = devig_result.true_prob_a
        result[(player, "Under", point)] = devig_result.true_prob_b

        # Track the highest-confidence source across all pairs.
        confidence_rank = {"HIGH": 3, "MEDIUM": 2, "LOW": 1, "CAUTION": 0}
        if confidence_rank.get(devig_result.confidence, 0) >= confidence_rank.get(best_confidence, 0):
            best_source = devig_result.source
            best_confidence = devig_result.confidence
            best_method = devig_result.method

        # Collect source keys for exclusion.
        src = devig_result.source
        if ":" in src:
            all_source_keys.update(src.split(":", 1)[1].split(","))
        elif src and not src.startswith("market_avg"):
            all_source_keys.add(src)

    return result, best_source, best_confidence, best_method, all_source_keys


def scan_game_props(game: Game) -> list[EVOpportunity]:
    """Scan a single game for +EV player prop opportunities.

    Uses the hierarchical devig engine for prop markets.
    """
    # Only scan prop markets supported for this sport.
    sport_props = get_prop_markets_for_sport(game.sport_key)
    if not sport_props:
        return []

    game_label = f"{game.away_team} @ {game.home_team}"
    opportunities: list[EVOpportunity] = []

    for prop_market_key in sport_props:
        true_probs, source, confidence, method, source_keys = _build_prop_devig_map(
            game, prop_market_key
        )
        if not true_probs:
            continue

        for bk in game.bookmakers:
            if bk.key in source_keys:
                continue

            book_market = get_market(bk.markets, prop_market_key)
            if book_market is None:
                continue

            for outcome in book_market.outcomes:
                player = outcome.description or ""
                lookup_key = (player, outcome.name, outcome.point)
                true_prob = true_probs.get(lookup_key)
                if true_prob is None:
                    continue

                ev_pct = calculate_ev(outcome.price, true_prob)
                if ev_pct < MIN_EV_THRESHOLD:
                    continue

                kelly_pct = kelly_fraction(
                    true_prob, outcome.price, DEFAULT_KELLY_FRACTION
                )

                # Build selection string: "Player Name Over/Under X.X"
                point_str = f" {outcome.point}" if outcome.point is not None else ""
                selection = f"{player} {outcome.name}{point_str}"

                opportunities.append(
                    EVOpportunity(
                        game_id=game.id,
                        sport_key=game.sport_key,
                        game=game_label,
                        commence_time=game.commence_time,
                        market=prop_market_key,
                        selection=selection,
                        point=outcome.point,
                        book=bk.title,
                        book_key=bk.key,
                        book_odds=outcome.price,
                        book_implied_prob=american_to_implied_prob(outcome.price),
                        true_prob=true_prob,
                        ev_pct=ev_pct,
                        kelly_pct=kelly_pct,
                        devig_source=source,
                        devig_confidence=confidence,
                        devig_method=method,
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
                    # For props, include player name in side.
                    if outcome.description:
                        point_str = f" {outcome.point}" if outcome.point is not None else ""
                        side = f"{outcome.description} {outcome.name}{point_str}"
                    else:
                        side = outcome.name + (
                            f" {outcome.point}" if outcome.point is not None else ""
                        )
                    key = (bk.key, mkt.key, side)
                    current_odds = float(outcome.price)
                    prev = latest_map.get(key)

                    # Skip if odds unchanged.
                    if prev is not None and prev == current_odds:
                        continue

                    # Every row MUST have the same keys — PostgREST
                    # rejects batches with mismatched keys (PGRST102).
                    row: dict = {
                        "game_id": game.id,
                        "sport": game.sport_key,
                        "bookmaker": bk.key,
                        "market_type": mkt.key,
                        "side": side,
                        "odds": current_odds,
                        "timestamp": scan_ts,
                        "previous_odds": prev if prev is not None else None,
                        "odds_change": (current_odds - prev) if prev is not None else None,
                    }
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
    """Devig lines using hierarchical source selection and store true probabilities.

    Uses the new devig engine: Pinnacle → Exchanges → Sharp consensus → Market avg.
    Falls back to single sharp book if hierarchical devig fails.
    """
    from db import insert_true_line

    for game in games:
        for market_key in ("h2h", "spreads", "totals"):
            true_probs, source, confidence, method = build_devig_line_map(
                game, market_key
            )
            if not true_probs:
                continue

            # Get outcome names and points from the first available book.
            _, outcome_info = _extract_market_odds_by_book(game, market_key)
            if outcome_info is None:
                continue
            name_a, name_b, point_a, point_b = outcome_info

            true_home = true_probs.get((name_a, point_a), 0.5)
            true_away = true_probs.get((name_b, point_b), 0.5)
            no_vig_line = point_a

            insert_true_line(
                db_client,
                game_id=game.id,
                market_type=market_key,
                true_home_prob=round(true_home, 6),
                true_away_prob=round(true_away, 6),
                sharp_book=source,
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
        # Every row MUST have the same keys — PostgREST rejects batches
        # with mismatched keys (PGRST102).  Use None for absent values.
        # NOTE: commence_time is NOT a column in ev_opportunities — store
        # it only if the column is added later; for now, omit it.
        row_data: dict = {
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
            "sport": opp.sport_key or None,
            "devig_source": opp.devig_source or None,
            "devig_confidence": opp.devig_confidence or None,
            "devig_method": opp.devig_method or None,
        }
        rows.append(row_data)

    bulk_insert_ev_opportunities(db_client, rows)


# ---------------------------------------------------------------------------
# Steam detection
# ---------------------------------------------------------------------------


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


def _is_prop_market(market_key: str) -> bool:
    """Return True if the market key is a player prop."""
    return market_key.startswith("player_")


def print_prop_results(opportunities: list[EVOpportunity]) -> None:
    """Print +EV player prop opportunities grouped by prop type."""
    if not opportunities:
        return

    by_prop: dict[str, list[EVOpportunity]] = {}
    for opp in opportunities:
        by_prop.setdefault(opp.market, []).append(opp)

    for prop_type, opps in sorted(by_prop.items()):
        opps.sort(key=lambda o: o.ev_pct, reverse=True)
        label = prop_type.replace("player_", "").replace("_", " ").title()
        header = (
            f"{'Game':<35} {'Player':<22} {'Line':>6} {'Side':<6} "
            f"{'Book':<18} {'Odds':>7} {'True%':>7} {'Book%':>7} "
            f"{'EV%':>7} {'Kelly%':>7}"
        )
        divider = "-" * len(header)
        print(f"\n  Props: {label}  ({len(opps)} opportunities)")
        print(divider)
        print(header)
        print(divider)
        for opp in opps:
            # Parse player/side from selection "Player Name Over X.X"
            parts = opp.selection.rsplit(" ", 2)
            if len(parts) >= 3:
                player = " ".join(parts[:-2])
                ou = parts[-2]
                line = parts[-1]
            elif len(parts) == 2:
                player = parts[0]
                ou = parts[1]
                line = ""
            else:
                player = opp.selection
                ou = ""
                line = ""
            print(
                f"{opp.game:<35} {player:<22} {line:>6} {ou:<6} "
                f"{opp.book:<18} {format_american(opp.book_odds):>7} "
                f"{opp.true_prob * 100:>6.1f}% {opp.book_implied_prob * 100:>6.1f}% "
                f"{opp.ev_pct:>+6.1f}% {opp.kelly_pct * 100:>6.2f}%"
            )
        print(divider)


def _opp_date_label(opp: EVOpportunity) -> str:
    """Get the date label for an opportunity based on its commence_time."""
    try:
        start = parse_commence_time(opp.commence_time)
        now = datetime.now(timezone.utc)
        today = now.date()
        game_date = start.date()
        if game_date == today:
            return f"TODAY ({start.strftime('%a %b %d')})"
        elif game_date == today + timedelta(days=1):
            return f"TOMORROW ({start.strftime('%a %b %d')})"
        else:
            return start.strftime("%A %b %d").upper()
    except Exception:
        return "UNKNOWN"


def _opp_date_sort_key(opp: EVOpportunity) -> str:
    """Sort key to order opportunities by commence_time."""
    try:
        return parse_commence_time(opp.commence_time).isoformat()
    except Exception:
        return ""


def print_results(all_opportunities: list[EVOpportunity], all_games: list[Game] | None = None) -> None:
    """Print +EV opportunities grouped by date with mainline/prop breakdown."""
    game_opps = [o for o in all_opportunities if not _is_prop_market(o.market)]
    prop_opps = [o for o in all_opportunities if _is_prop_market(o.market)]

    # Count unique games tracked.
    unique_games = len({o.game_id for o in all_opportunities})
    total_games = len(all_games) if all_games else unique_games
    unique_sports = len({o.sport_key for o in all_opportunities})

    banner_width = 120
    print(f"\n{'=' * banner_width}")
    print(
        f"  RTM +EV Scanner  |  "
        f"{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}  |  "
        f"Tracking {total_games} games across {unique_sports} sports  |  "
        f"{len(all_opportunities)} opps ({len(game_opps)} lines, {len(prop_opps)} props)"
    )
    print(f"{'=' * banner_width}")

    if not all_opportunities:
        print("\nNo +EV opportunities found across any sport right now.\n")
        return

    # Group ALL opportunities by date.
    by_date: dict[str, list[EVOpportunity]] = {}
    date_order: list[str] = []
    for opp in sorted(all_opportunities, key=_opp_date_sort_key):
        label = _opp_date_label(opp)
        if label not in by_date:
            by_date[label] = []
            date_order.append(label)
        by_date[label].append(opp)

    for date_label in date_order:
        opps = by_date[date_label]
        d_game_opps = [o for o in opps if not _is_prop_market(o.market)]
        d_prop_opps = [o for o in opps if _is_prop_market(o.market)]
        d_games = len({o.game_id for o in opps})

        print(f"\n{'─' * banner_width}")
        print(
            f"  === {date_label} — "
            f"{d_games} game{'s' if d_games != 1 else ''}, "
            f"{len(d_game_opps)} mainline opp{'s' if len(d_game_opps) != 1 else ''}, "
            f"{len(d_prop_opps)} prop opp{'s' if len(d_prop_opps) != 1 else ''} ==="
        )
        print(f"{'─' * banner_width}")

        # Group game lines by sport within this date.
        if d_game_opps:
            sports_seen: list[str] = []
            by_sport: dict[str, list[EVOpportunity]] = {}
            for opp in d_game_opps:
                if opp.sport_key not in by_sport:
                    by_sport[opp.sport_key] = []
                    sports_seen.append(opp.sport_key)
                by_sport[opp.sport_key].append(opp)
            for sport_key in sports_seen:
                print_sport_results(sport_key, by_sport[sport_key])

        if d_prop_opps:
            print_prop_results(d_prop_opps)

    # Best overall.
    best = max(all_opportunities, key=lambda o: o.ev_pct)
    best_hours = 0.0
    try:
        best_start = parse_commence_time(best.commence_time)
        best_hours = (best_start - datetime.now(timezone.utc)).total_seconds() / 3600
    except Exception:
        pass
    time_label = (
        f"in {best_hours:.0f}h" if best_hours > 1
        else "starting soon" if best_hours > 0
        else "live"
    )
    print(
        f"\nBest opportunity: {best.selection} "
        f"({best.game}, {sport_display_name(best.sport_key)}) at {best.book} "
        f"[{format_american(best.book_odds)}] -> {best.ev_pct:+.1f}% EV | {time_label}\n"
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
    scan_start = time.time()

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
        print(f"[SCAN] Fetching {display} mainlines from regions: {ODDS_API_REGIONS}")

        # Step 1: Fetch mainlines (h2h, spreads, totals) for ALL upcoming games.
        t0 = time.time()
        try:
            games = fetch_odds(sport_key, markets=MARKETS)
        except Exception as e:
            print(f"  Skipping {display}: {e}")
            continue
        print(f"  [TIMING] {display} mainline API fetch: {time.time() - t0:.1f}s")

        if not games:
            print(f"  {display}: no games available right now.")
            continue

        # Log book discovery by tier.
        all_book_keys: set[str] = set()
        for g in games:
            for bk in g.bookmakers:
                all_book_keys.add(bk.key)
        sharp_found = sorted(k for k in all_book_keys if get_book_tier(k) == "sharp")
        exchange_found = sorted(k for k in all_book_keys if get_book_tier(k) == "exchange")
        soft_found = sorted(k for k in all_book_keys if get_book_tier(k) in ("soft", "market_maker"))
        print(f"  [SCAN] {len(all_book_keys)} books across {len(games)} games")
        if sharp_found:
            print(f"  [SCAN] Sharp: {', '.join(get_book_name(k) for k in sharp_found)}")
        if exchange_found:
            print(f"  [SCAN] Exchanges: {', '.join(get_book_name(k) for k in exchange_found)}")
        if soft_found:
            print(f"  [SCAN] Soft/MM: {', '.join(get_book_name(k) for k in soft_found[:10])}"
                  + (f" +{len(soft_found)-10} more" if len(soft_found) > 10 else ""))

        # Pinnacle presence check — critical for devig quality.
        if "pinnacle" in all_book_keys:
            print(f"  [SCAN] ✓ Pinnacle FOUND — devig source will be HIGH confidence")
        elif "eu" in ODDS_API_REGIONS:
            print(f"  [SCAN] ⚠ Pinnacle NOT FOUND — EU region may be failing silently!")
            print(f"  [SCAN]   Requested regions: {ODDS_API_REGIONS}")
            print(f"  [SCAN]   Falling back to: exchanges → sharp consensus → market avg")

        # Region breakdown for diagnostics.
        region_counts: dict[str, int] = {}
        for bk_key in all_book_keys:
            info = get_book_info(bk_key)
            r = info.get("region", "unknown")
            region_counts[r] = region_counts.get(r, 0) + 1
        if region_counts:
            region_str = ", ".join(f"{r}={c}" for r, c in sorted(region_counts.items()))
            print(f"  [SCAN] Books by region: {region_str}")

        # Full book list — useful for confirming which books the API returns.
        print(f"  [SCAN] All books: {', '.join(sorted(all_book_keys))}")

        # Categorize games by date.
        near_games = [g for g in games if -3 < hours_until_start(g) <= PROP_WINDOW_HOURS]
        far_games = [g for g in games if hours_until_start(g) > PROP_WINDOW_HOURS]
        print(
            f"  {display}: {len(games)} games found "
            f"({len(near_games)} within {PROP_WINDOW_HOURS:.0f}h, "
            f"{len(far_games)} further out)."
        )

        # Step 2: Fetch props ONLY if there are games within the prop window
        # and the sport has supported prop markets.
        sport_props = get_prop_markets_for_sport(sport_key)
        if near_games and sport_props:
            print(f"  Fetching {display} props ({len(sport_props)} markets) for {len(near_games)} near-term game(s)...")
            time.sleep(1)
            t0 = time.time()
            try:
                prop_games = fetch_odds(sport_key, markets=sport_props)
                if prop_games:
                    merge_prop_data(games, prop_games)
                    print(f"  Props merged for {display}.")
            except Exception as e:
                print(f"  Warning: Prop fetch failed for {display} ({e}).")
            print(f"  [TIMING] {display} props API fetch: {time.time() - t0:.1f}s")
        elif near_games:
            print(f"  Skipping props for {display} — no prop markets configured for this sport.")
        else:
            print(f"  Skipping props for {display} — no games within {PROP_WINDOW_HOURS:.0f}h.")

        all_games.extend(games)

        # Persist game data.
        if db is not None:
            t0 = time.time()
            try:
                store_games(db, games)
                store_odds_snapshots(db, games)
                store_true_lines(db, games)
            except Exception as e:
                print(f"  Warning: DB write failed for {display} ({e}).")
            print(f"  [TIMING] {display} games/odds/true_lines DB write: {time.time() - t0:.1f}s")

            # Line movements for ALL games (early lines are most valuable).
            t0 = time.time()
            try:
                store_line_movements(db, games)
            except Exception as e:
                print(f"  Warning: Line movement write failed for {display} ({e}).")
            print(f"  [TIMING] {display} line_movements DB write: {time.time() - t0:.1f}s")

        # Scan for +EV: mainlines for ALL games, props for near-term only.
        # Track devig source usage for diagnostics.
        t0 = time.time()
        devig_source_counts: dict[str, int] = {}
        sport_opps: list[EVOpportunity] = []
        for game in games:
            game_opps = scan_game(game)
            # Track which devig sources were used.
            for opp in game_opps:
                src = opp.devig_source or "none"
                # Simplify source label for summary.
                if src.startswith("exchange:"):
                    src_label = "exchange_consensus"
                elif src.startswith("sharp:"):
                    src_label = "sharp_consensus"
                elif src.startswith("market_avg:"):
                    src_label = "market_average"
                elif src == "pinnacle":
                    src_label = "pinnacle"
                else:
                    src_label = src
                devig_source_counts[src_label] = devig_source_counts.get(src_label, 0) + 1
            sport_opps.extend(game_opps)
            all_opportunities.extend(game_opps)
            h = hours_until_start(game)
            if -3 < h <= PROP_WINDOW_HOURS:
                prop_opps = scan_game_props(game)
                sport_opps.extend(prop_opps)
                all_opportunities.extend(prop_opps)

        print(f"  [TIMING] {display} EV scanning: {time.time() - t0:.1f}s ({len(sport_opps)} opps)")

        # Print devig source summary for this sport.
        if devig_source_counts:
            src_str = ", ".join(f"{k}={v}" for k, v in sorted(devig_source_counts.items(), key=lambda x: -x[1]))
            print(f"  [DEVIG] Source breakdown: {src_str}")

    # --- Persist EV opportunities ---
    if db is not None and all_opportunities:
        t0 = time.time()
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
        print(f"[TIMING] EV store: {time.time() - t0:.1f}s")

    # --- CLV record creation ---
    if db is not None and all_opportunities:
        t0 = time.time()
        try:
            from scrapers.clv_tracker import create_clv_from_ev_opportunities
            clv_count = create_clv_from_ev_opportunities(db)
            if clv_count:
                print(f"CLV tracking: {clv_count} new record(s) created.")
        except Exception as e:
            print(f"Warning: CLV record creation failed ({e}).")
        print(f"[TIMING] CLV record creation: {time.time() - t0:.1f}s")

    # --- CLV processing (close records for started games) ---
    if db is not None:
        t0 = time.time()
        try:
            from scrapers.clv_tracker import process_open_records
            clv_processed, clv_expired = process_open_records(db)
            if clv_processed or clv_expired:
                print(f"CLV processing: {clv_processed} closed, {clv_expired} expired.")
        except Exception as e:
            print(f"Warning: CLV processing failed ({e}).")
        print(f"[TIMING] CLV processing: {time.time() - t0:.1f}s")

    # --- Steam detection ---
    if db is not None:
        t0 = time.time()
        try:
            new_alerts = detect_steam_moves(db)
            if new_alerts:
                print(f"\nSteam alerts: {new_alerts} new alert(s) detected!")
        except Exception as e:
            print(f"Warning: Steam detection failed ({e}).")
        print(f"[TIMING] Steam detection: {time.time() - t0:.1f}s")

    # --- Intelligence Layers ---
    if db is not None and all_games:
        t0_intel = time.time()
        try:
            from intelligence.book_profiler import BookProfiler, track_reactions_from_movements
            from intelligence.stale_detector import StaleLineDetector, build_odds_snapshot_from_games
            from intelligence.market_timing import MarketTimingEngine

            profiler = BookProfiler(db)
            detector = StaleLineDetector(db)

            # Build current odds snapshot for stale detection.
            odds_snapshot = build_odds_snapshot_from_games(all_games)

            # Track book reaction times from recent line movements.
            try:
                now_ts = datetime.now(timezone.utc)
                since = (now_ts - timedelta(minutes=SCAN_INTERVAL_MINUTES + 5)).isoformat()
                recent_moves = db._get(
                    "line_movements",
                    select="game_id,sport,market_type,side,bookmaker,odds,timestamp",
                    filters={"timestamp": f"gte.{since}"},
                )
                if recent_moves:
                    reactions = track_reactions_from_movements(db, profiler, recent_moves)
                    if reactions:
                        print(f"  Book profiler: {reactions} reaction(s) tracked.")
            except Exception as e:
                print(f"  Warning: Book profiler tracking failed ({e}).")

            # Detect stale lines.
            try:
                stale_lines = detector.detect_stale_lines(odds_snapshot)
                if stale_lines:
                    stored = detector.store_stale_lines(stale_lines)
                    print(f"  Stale lines: {len(stale_lines)} detected, {stored} new alert(s).")

                    # Resolve stale lines that have been corrected.
                    resolved = detector.resolve_stale_lines(odds_snapshot)
                    if resolved:
                        print(f"  Stale lines: {resolved} resolved (book caught up).")

                    # Discord alert for high-edge stale lines.
                    from notifications.discord import _send_webhook, _is_enabled
                    for sl in stale_lines:
                        if sl["edge_percentage"] >= 5.0 and _is_enabled():
                            try:
                                _send_webhook({"embeds": [{
                                    "title": "\U0001f3af STALE LINE DETECTED",
                                    "description": (
                                        f"**{sl['stale_book']}** still has **{sl['side']}** at "
                                        f"**{int(sl['stale_odds']):+d}** | Consensus moved to "
                                        f"**{int(sl['consensus_odds']):+d}** | "
                                        f"**{sl['edge_percentage']:.1f}%** edge | ACT NOW"
                                    ),
                                    "color": 0xFF4444,
                                    "footer": {"text": "RTM Intelligence | Stale Line Detection"},
                                }]})
                            except Exception:
                                pass
            except Exception as e:
                print(f"  Warning: Stale line detection failed ({e}).")

            # Track line lifecycle (market timing).
            try:
                timing = MarketTimingEngine(db)
                lifecycle_count = 0
                for game in all_games:
                    for bk in game.bookmakers:
                        for mkt in bk.markets:
                            for outcome in mkt.outcomes:
                                if outcome.description:
                                    point_str = f" {outcome.point}" if outcome.point is not None else ""
                                    side = f"{outcome.description} {outcome.name}{point_str}"
                                else:
                                    side = outcome.name + (
                                        f" {outcome.point}" if outcome.point is not None else ""
                                    )
                                # Check if this line already exists in lifecycle.
                                try:
                                    existing = db._get(
                                        "line_lifecycle",
                                        select="id",
                                        filters={
                                            "game_id": f"eq.{game.id}",
                                            "market_type": f"eq.{mkt.key}",
                                            "side": f"eq.{side}",
                                            "sportsbook": f"eq.{bk.key}",
                                        },
                                        limit=1,
                                    )
                                    if not existing:
                                        timing.track_line_first_seen(
                                            game_id=game.id,
                                            sport=game.sport_key,
                                            market_type=mkt.key,
                                            side=side,
                                            sportsbook=bk.key,
                                            opening_odds=outcome.price,
                                            game_start_time=game.commence_time,
                                        )
                                        lifecycle_count += 1
                                except Exception:
                                    pass
                if lifecycle_count:
                    print(f"  Market timing: {lifecycle_count} new line lifecycle(s) tracked.")
            except Exception as e:
                print(f"  Warning: Market timing tracking failed ({e}).")
        except Exception as e:
            print(f"Warning: Intelligence layers failed ({e}).")
        print(f"[TIMING] Intelligence layers: {time.time() - t0_intel:.1f}s")

    # --- Score fetching & auto-grading ---
    if db is not None:
        t0 = time.time()
        try:
            from scrapers.scores.score_fetcher import fetch_and_update_scores
            score_count = fetch_and_update_scores(db, sport_keys)
            if score_count:
                print(f"Scores: {score_count} game(s) finalized.")
        except Exception as e:
            print(f"Warning: Score fetch failed ({e}).")

        try:
            from scrapers.grader import grade_opportunities
            grade_result = grade_opportunities(db)
        except Exception as e:
            print(f"Warning: Auto-grading failed ({e}).")
        print(f"[TIMING] Scores & grading: {time.time() - t0:.1f}s")

    # --- RTM Signal generation ---
    if db is not None and all_opportunities:
        t0_sig = time.time()
        try:
            from rtm_signal_engine.rtm_signal import RTMSignal, store_signals, format_signal_for_console
            from notifications.discord import send_signal_alert

            # Build EV opportunity dicts for signal scoring.
            opp_dicts_for_signal = []
            for o in all_opportunities:
                game_parts = o.game.split(" @ ") if " @ " in o.game else ["", ""]
                h_until = 0.0
                try:
                    s = parse_commence_time(o.commence_time)
                    h_until = (s - datetime.now(timezone.utc)).total_seconds() / 3600
                except Exception:
                    pass
                opp_dicts_for_signal.append({
                    "game_id": o.game_id,
                    "sport": o.sport_key,
                    "market_type": o.market,
                    "side": o.selection + (
                        f" {o.point}" if o.point is not None and not _is_prop_market(o.market) else ""
                    ),
                    "ev_percentage": o.ev_pct,
                    "book_odds": o.book_odds,
                    "sportsbook": o.book_key,
                    "true_prob": o.true_prob,
                    "commence_time": o.commence_time,
                    "hours_until_start": round(h_until, 1),
                    "games": {
                        "sport": o.sport_key,
                        "home_team": game_parts[-1],
                        "away_team": game_parts[0],
                    },
                })

            # Build player projections for NBA props.
            player_projections: dict[int, dict] = {}
            nba_keys = {"basketball_nba"}
            has_nba = any(o.sport_key in nba_keys for o in all_opportunities)
            if has_nba:
                try:
                    from projections.projection_engine import ProjectionEngine
                    engine = ProjectionEngine(use_mock=True)
                    from projections.mock_data import MOCK_PLAYERS
                    for pid in MOCK_PLAYERS:
                        try:
                            proj = engine.project_player(pid, "BOS", "home")
                            if proj:
                                player_projections[pid] = proj
                        except Exception:
                            pass
                except Exception:
                    pass

            signal_engine = RTMSignal(db_client=db)
            game_ids = list({o.game_id for o in all_opportunities})
            signal_engine.load_cache(game_ids)

            signals = signal_engine.generate_signals(
                opp_dicts_for_signal, player_projections
            )

            if signals:
                stored = store_signals(db, signals)
                print(f"\nRTM Signals: {len(signals)} signals fired ({stored} stored)")
                for sig in signals[:5]:
                    print(f"  {format_signal_for_console(sig)}")
                for sig in signals:
                    if sig["star_rating"] >= 4:
                        try:
                            send_signal_alert(sig)
                        except Exception:
                            pass
            # Silent when no signals fire — expected for many scans.
        except Exception as e:
            print(f"Warning: RTM Signal generation failed ({e}).")
        print(f"[TIMING] Signal generation: {time.time() - t0_sig:.1f}s")

    # --- Signal grading ---
    if db is not None:
        t0 = time.time()
        try:
            from rtm_signal_engine.signal_grader import grade_signals
            sig_grade_result = grade_signals(db)
            if sig_grade_result["graded"] > 0:
                print(f"Signal grading: {sig_grade_result['graded']} signals graded.")
        except Exception as e:
            print(f"Warning: Signal grading failed ({e}).")
        print(f"[TIMING] Signal grading: {time.time() - t0:.1f}s")

    # --- Discord alerts ---
    t0 = time.time()
    try:
        from notifications.alerts import alert_manager

        opp_dicts = [
            {
                "game_id": o.game_id, "sport_key": o.sport_key, "game": o.game,
                "selection": o.selection, "book": o.book, "book_key": o.book_key,
                "book_odds": o.book_odds, "ev_pct": o.ev_pct,
                "true_prob": o.true_prob, "kelly_pct": o.kelly_pct,
                "market": o.market, "point": o.point,
            }
            for o in all_opportunities
        ]
        ev_sent = alert_manager.check_and_alert(opp_dicts)
        if ev_sent:
            print(f"Discord: sent {ev_sent} EV alert(s).")
    except Exception as e:
        print(f"Warning: Discord alerts failed ({e}).")
    print(f"[TIMING] Discord alerts: {time.time() - t0:.1f}s")

    # --- Console output ---
    print_results(all_opportunities, all_games)

    total_elapsed = time.time() - scan_start
    print(f"\n[TIMING] ═══ Total scan cycle: {total_elapsed:.1f}s ═══")
    return len(all_opportunities)


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------


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
