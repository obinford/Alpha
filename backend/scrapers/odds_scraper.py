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
from models.kelly import kelly_fraction, kelly_full
from scrapers.odds.odds_api import Game, Market, fetch_odds

from concurrent.futures import ThreadPoolExecutor, as_completed

from config import (
    ODDS_API_SPORT_KEYS, SHARP_BOOKS, SPORT_DISPLAY_NAMES,
    ALL_MARKETS, PROP_MARKETS, MARKETS, ODDS_API_REGIONS,
    get_prop_markets_for_sport, is_sport_in_season,
    MIN_EV_THRESHOLD, DEFAULT_KELLY_FRACTION,
    DEFAULT_BANKROLL_UNITS, PROP_WINDOW_HOURS,
    STEAM_MIN_BOOKS, STEAM_WINDOW_MINUTES, STEAM_DEDUP_MINUTES,
    SCAN_INTERVAL_MINUTES,
)
from books import get_book_tier, get_book_name, get_book_info

# ---------------------------------------------------------------------------
# Book whitelist — only process books we can actually bet at (US) plus
# Pinnacle as our sharp devig reference.  Everything else (EU soft books,
# regional sportsbooks like betclic_fr, tipico_de, etc.) is dropped after
# fetching to reduce payload size and avoid false +EV noise.
# ---------------------------------------------------------------------------
ALLOWED_BOOKS: set[str] = {
    # Sharp reference (needed for devig)
    "pinnacle", "circasports", "bookmaker",
    # US books
    "betonlineag", "bovada",
    # US market makers
    "betmgm", "betrivers", "draftkings", "fanatics", "fanduel",
    # US soft
    "betus", "mybookieag",
    # US2 soft
    "ballybet", "betparx", "espnbet", "fliff", "hardrockbet", "rebet",
    # US exchanges
    "kalshi", "novig", "polymarket", "prophetx",
}

# Hardcoded blocklist — books that must NEVER appear in scan output,
# opportunities, or devig calculations regardless of what The Odds API
# returns.  Checked at parse time before any processing.
BLOCKED_BOOKS: set[str] = {
    "betopenly",
    "betparx",
}

# Build fetch regions: base regions + eu (for Pinnacle).
_FETCH_REGIONS = ODDS_API_REGIONS if "eu" in ODDS_API_REGIONS else f"{ODDS_API_REGIONS},eu"


def _is_book_allowed(book_key: str) -> bool:
    """Return True if a bookmaker should be processed.

    A book must be in the whitelist AND not in the blocklist.
    """
    return book_key in ALLOWED_BOOKS and book_key not in BLOCKED_BOOKS


def _filter_non_whitelisted_books(games: list[Game]) -> int:
    """Remove bookmakers not in ALLOWED_BOOKS (or in BLOCKED_BOOKS) from game data.

    Mutates game.bookmakers in place.  Returns the total number of
    bookmakers removed across all games.
    """
    removed = 0
    for game in games:
        original = len(game.bookmakers)
        game.bookmakers = [
            bk for bk in game.bookmakers if _is_book_allowed(bk.key)
        ]
        removed += original - len(game.bookmakers)
    return removed


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
            # Block explicitly blocked books from entering via prop merge.
            if prop_bk.key in BLOCKED_BOOKS:
                continue
            target_bk = bk_map.get(prop_bk.key)
            if target_bk is None:
                # Only add if the book passes the whitelist check.
                if _is_book_allowed(prop_bk.key):
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

    Outcomes are matched by name across bookmakers to ensure consistent
    ordering.  The first bookmaker sets the canonical name order; subsequent
    bookmakers' outcomes are looked up by name rather than position so that
    home/away odds are never flipped.
    """
    book_odds: dict[str, tuple[int, int]] = {}
    outcome_info: list | None = None
    canonical_names: tuple[str, str] | None = None

    for bk in game.bookmakers:
        if bk.key in BLOCKED_BOOKS:
            continue
        mkt = get_market(bk.markets, market_key)
        if mkt is None or len(mkt.outcomes) != 2:
            continue

        if canonical_names is None:
            # First bookmaker establishes the canonical name order.
            canonical_names = (mkt.outcomes[0].name, mkt.outcomes[1].name)
            outcome_info = [
                mkt.outcomes[0].name, mkt.outcomes[1].name,
                mkt.outcomes[0].point, mkt.outcomes[1].point,
            ]
            book_odds[bk.key] = (mkt.outcomes[0].price, mkt.outcomes[1].price)
        else:
            # Match outcomes by name to ensure consistent ordering.
            odds_by_name = {o.name: o.price for o in mkt.outcomes}
            name_a, name_b = canonical_names
            if name_a in odds_by_name and name_b in odds_by_name:
                book_odds[bk.key] = (odds_by_name[name_a], odds_by_name[name_b])
            else:
                # Names don't match — fall back to positional order.
                book_odds[bk.key] = (mkt.outcomes[0].price, mkt.outcomes[1].price)

    return book_odds, outcome_info


def build_devig_line_map(
    game: Game, market_key: str,
) -> tuple[dict[tuple[str, float | None], float], str, str, str, frozenset[str]]:
    """Build a true-probability map using the hierarchical devig engine.

    Returns:
        (true_probs, devig_source, devig_confidence, devig_method, source_keys)
        where true_probs is {(selection_name, point): true_probability}
        and source_keys is the set of book keys used as the devig source.
    """
    book_odds, outcome_info = _extract_market_odds_by_book(game, market_key)
    if not book_odds or outcome_info is None:
        return {}, "", "CAUTION", "multiplicative", frozenset()

    result = devig_market(book_odds)
    if result is None:
        return {}, "", "CAUTION", "multiplicative", frozenset()

    name_a, name_b, point_a, point_b = outcome_info
    true_probs = {
        (name_a, point_a): result.true_prob_a,
        (name_b, point_b): result.true_prob_b,
    }

    # Debug logging for h2h devig — verify probabilities match team names.
    if market_key == "h2h" and "pinnacle" in book_odds:
        pin_a, pin_b = book_odds["pinnacle"]
        game_label = f"{game.away_team} @ {game.home_team}"
        print(
            f"  [DEVIG DEBUG] {game_label} h2h | "
            f"Pinnacle odds (canonical): {name_a}={pin_a:+d}, {name_b}={pin_b:+d} | "
            f"True probs: {name_a}={result.true_prob_a:.4f}, {name_b}={result.true_prob_b:.4f}"
        )

    return true_probs, result.source, result.confidence, result.method, result.source_keys


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
        true_probs, source, confidence, method, source_keys = build_devig_line_map(
            game, market_key
        )
        if not true_probs:
            continue

        for bk in game.bookmakers:
            if bk.key in source_keys or bk.key in BLOCKED_BOOKS:
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

                kelly_pct = kelly_full(true_prob, outcome.price)

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
    # Collect all O/U pairs per book per (player, point).
    # Structure: {(desc, point): {book_key: (over_price, under_price)}}
    pair_by_book: dict[tuple[str | None, float | None], dict[str, tuple[int, int]]] = {}

    for bk in game.bookmakers:
        if bk.key in BLOCKED_BOOKS:
            continue
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
        all_source_keys.update(devig_result.source_keys)

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
            if bk.key in source_keys or bk.key in BLOCKED_BOOKS:
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

                kelly_pct = kelly_full(true_prob, outcome.price)

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
    """Upsert all games into the database (batched)."""
    rows = [
        {
            "game_id": g.id,
            "sport": g.sport_key,
            "home_team": g.home_team,
            "away_team": g.away_team,
            "start_time": g.commence_time,
            "status": "upcoming",
        }
        for g in games
    ]
    if rows:
        db_client._upsert_many("games", rows, on_conflict="game_id")


def store_line_movements(db_client: object, games: list[Game]) -> None:
    """Record line movements for ALL bookmaker/game/market/side combos.

    Compares current odds to the most recent row for each combo.  If odds
    changed, insert with ``previous_odds`` / ``odds_change``.  If odds are
    the same, skip the insert to save space.

    Batched: fetches latest odds for all games in one query.
    """
    from db import bulk_insert_line_movements

    scan_ts = datetime.now(timezone.utc).isoformat()
    rows: list[dict] = []

    # Batch-fetch existing latest odds for ALL games at once (N+1 fix).
    game_ids = [g.id for g in games]
    all_existing: list[dict] = []
    for i in range(0, len(game_ids), 50):
        chunk = game_ids[i : i + 50]
        id_list = ",".join(chunk)
        try:
            batch = db_client._get(
                "line_movements",
                select="game_id,bookmaker,market_type,side,odds,timestamp",
                filters={"game_id": f"in.({id_list})"},
                order="timestamp.desc",
            )
            all_existing.extend(batch)
        except Exception:
            pass

    # Build lookup: (game_id, bookmaker, market_type, side) -> latest odds.
    latest_map: dict[tuple[str, str, str, str], float] = {}
    for row in all_existing:
        key = (row["game_id"], row["bookmaker"], row["market_type"], row["side"])
        if key not in latest_map:
            latest_map[key] = float(row["odds"])

    for game in games:
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
                    key = (game.id, bk.key, mkt.key, side)
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


def validate_odds_mapping(games: list[Game], threshold: int = 5) -> int:
    """Post-scan validation: compare raw Pinnacle API odds against mapped values.

    For each game, extracts Pinnacle h2h outcomes by name and compares
    against what store_odds_snapshots would have mapped.  Logs mismatches
    where the stored value differs from the API by more than ``threshold``
    American-odds cents.

    Returns number of mismatches found.
    """
    mismatches = 0
    for game in games:
        game_label = f"{game.away_team} @ {game.home_team}"
        pin_bk = None
        for bk in game.bookmakers:
            if bk.key == "pinnacle":
                pin_bk = bk
                break
        if pin_bk is None:
            continue

        for mkt in pin_bk.markets:
            if len(mkt.outcomes) != 2:
                continue

            # What the API returned: match by team name to get "truth".
            api_home = None
            api_away = None
            if mkt.key == "totals":
                for o in mkt.outcomes:
                    if o.name.lower() == "over":
                        api_home = o.price  # convention: Over → home slot
                    elif o.name.lower() == "under":
                        api_away = o.price
            else:
                for o in mkt.outcomes:
                    if o.name == game.home_team:
                        api_home = o.price
                    elif o.name == game.away_team:
                        api_away = o.price

            if api_home is None or api_away is None:
                # Names didn't match — this IS a problem, log it.
                raw_names = [o.name for o in mkt.outcomes]
                print(
                    f"  [ODDS VALIDATION] NAME MISMATCH: {game_label} {mkt.key} | "
                    f"API outcome names {raw_names} don't match "
                    f"home='{game.home_team}' away='{game.away_team}'"
                )
                mismatches += 1
                continue

            # What store_odds_snapshots would store (replicate its logic).
            if mkt.key == "totals":
                odds_by_name = {o.name.lower(): o for o in mkt.outcomes}
                stored_home = odds_by_name.get("over", mkt.outcomes[0]).price
                stored_away = odds_by_name.get("under", mkt.outcomes[1]).price
            else:
                odds_by_name = {o.name: o for o in mkt.outcomes}
                stored_home = odds_by_name.get(game.home_team, mkt.outcomes[0]).price
                stored_away = odds_by_name.get(game.away_team, mkt.outcomes[1]).price

            home_diff = abs(api_home - stored_home)
            away_diff = abs(api_away - stored_away)

            if home_diff > threshold or away_diff > threshold:
                mismatches += 1
                print(
                    f"  [ODDS VALIDATION] MISMATCH: {game_label} {mkt.key} | "
                    f"API returned: home={api_home:+d} away={api_away:+d} | "
                    f"Stored: home={stored_home:+d} away={stored_away:+d}"
                )

    if mismatches == 0:
        game_count = sum(
            1 for g in games
            if any(bk.key == "pinnacle" for bk in g.bookmakers)
        )
        print(f"  [ODDS VALIDATION] All {game_count} Pinnacle games validated OK")

    return mismatches


def store_odds_snapshots(db_client: object, games: list[Game]) -> None:
    """Store raw odds from every sportsbook/market combination (batched)."""
    rows: list[dict] = []
    for game in games:
        game_label = f"{game.away_team} @ {game.home_team}"
        for bk in game.bookmakers:
            for mkt in bk.markets:
                if len(mkt.outcomes) != 2:
                    continue
                # Match outcomes by name to home/away teams.
                # The Odds API may return outcomes in any order per bookmaker.
                # For totals, outcome names are "Over"/"Under" (not team names),
                # so we map Over → home_odds slot, Under → away_odds slot.
                if mkt.key == "totals":
                    odds_by_name = {o.name.lower(): o for o in mkt.outcomes}
                    home_out = odds_by_name.get("over", mkt.outcomes[0])
                    away_out = odds_by_name.get("under", mkt.outcomes[1])
                else:
                    odds_by_name = {o.name: o for o in mkt.outcomes}
                    home_out = odds_by_name.get(game.home_team, mkt.outcomes[0])
                    away_out = odds_by_name.get(game.away_team, mkt.outcomes[1])

                # Debug logging for Pinnacle h2h mapping.
                if bk.key == "pinnacle" and mkt.key == "h2h":
                    raw_o1 = mkt.outcomes[0]
                    raw_o2 = mkt.outcomes[1]
                    print(
                        f"  [ODDS DEBUG] Game: {game_label} | "
                        f"Pinnacle raw: outcome1={raw_o1.name} odds1={raw_o1.price:+d}, "
                        f"outcome2={raw_o2.name} odds2={raw_o2.price:+d} | "
                        f"Mapped: home_ml={home_out.price:+d} ({game.home_team}), "
                        f"away_ml={away_out.price:+d} ({game.away_team})"
                    )

                rows.append({
                    "game_id": game.id,
                    "sportsbook": bk.key,
                    "market_type": mkt.key,
                    "home_odds": home_out.price,
                    "away_odds": away_out.price,
                    "spread_value": home_out.point if mkt.key == "spreads" else None,
                    "total_value": home_out.point if mkt.key == "totals" else None,
                })
    if rows:
        db_client._post_many("odds_snapshots", rows)


def store_true_lines(db_client: object, games: list[Game]) -> None:
    """Devig lines using hierarchical source selection and store true probabilities.

    Uses the new devig engine: Pinnacle → Exchanges → Sharp consensus → Market avg.
    Falls back to single sharp book if hierarchical devig fails.
    Batched: collects all rows then bulk-inserts.
    """
    rows: list[dict] = []
    for game in games:
        for market_key in ("h2h", "spreads", "totals"):
            true_probs, source, confidence, method, _source_keys = build_devig_line_map(
                game, market_key
            )
            if not true_probs:
                continue

            # Look up true probabilities by actual home/away team name.
            # For h2h/spreads: use game.home_team and game.away_team.
            # For totals: Over/Under — "home" slot gets Over, "away" gets Under.
            if market_key == "totals":
                # Totals use Over/Under, not team names.
                # Find the point (total line) from any available prob key.
                total_point = None
                true_home = 0.5
                true_away = 0.5
                for (name, pt), prob in true_probs.items():
                    if name.lower() == "over":
                        true_home = prob
                        total_point = pt
                    elif name.lower() == "under":
                        true_away = prob
                no_vig_line = total_point
            else:
                # h2h and spreads: match by team name.
                # Try exact match first, then scan all probs for a match.
                true_home = 0.5
                true_away = 0.5
                no_vig_line = None
                for (name, pt), prob in true_probs.items():
                    if name == game.home_team:
                        true_home = prob
                        no_vig_line = pt
                    elif name == game.away_team:
                        true_away = prob

            rows.append({
                "game_id": game.id,
                "market_type": market_key,
                "true_home_prob": round(true_home, 6),
                "true_away_prob": round(true_away, 6),
                "sharp_book": source,
                "no_vig_line": no_vig_line,
            })
    if rows:
        db_client._post_many("true_lines", rows)


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
        # NOTE: commence_time and sport are NOT columns in
        # ev_opportunities — omit them to avoid bulk insert failures.
        # NOTE: devig_confidence is a numeric column in the DB —
        # map the string label to a numeric score.
        _CONFIDENCE_MAP = {"HIGH": 3, "MEDIUM": 2, "LOW": 1, "CAUTION": 0}
        confidence_val = _CONFIDENCE_MAP.get(
            (opp.devig_confidence or "").upper()
        )
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
            "devig_source": opp.devig_source or None,
            "devig_confidence": confidence_val,
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
    Otherwise, return only *in-season* sport keys to avoid wasting API
    calls.  Set SCAN_ALL_SPORTS=1 to override the season filter.
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

    # Reverse lookup: api_key -> sport name  (for season filtering).
    key_to_name = {v: k for k, v in ODDS_API_SPORT_KEYS.items()}

    all_keys = list(ODDS_API_SPORT_KEYS.values())
    active_keys = [k for k in all_keys if is_sport_in_season(key_to_name.get(k, ""))]
    skipped = [k for k in all_keys if k not in active_keys]

    print(f"Active sports ({len(active_keys)}): {', '.join(sport_display_name(k) for k in active_keys)}")
    if skipped:
        print(f"Off-season ({len(skipped)}): {', '.join(sport_display_name(k) for k in skipped)}  (skipped)\n")
    else:
        print()
    return active_keys


# ---------------------------------------------------------------------------
# Cleanup helpers
# ---------------------------------------------------------------------------


def cleanup_stale_data(db_client) -> None:
    """Delete stale opportunities and expire stale signals before a new scan.

    1. Delete ev_opportunities older than 20 minutes.
    2. Expire active signals for started games or older than 30 minutes.
    3. Bulk-repair NULL kelly_size on existing signals.

    Designed to complete in <3 seconds using bulk DB operations.
    """
    from projections.math_utils import american_to_decimal

    now = datetime.now(timezone.utc)
    stale_cutoff = (now - timedelta(minutes=20)).isoformat()
    signal_stale_cutoff = (now - timedelta(minutes=30)).isoformat()

    # 1. Delete stale opportunities (>20 min old) — single bulk DELETE.
    total_deleted = 0
    try:
        n = db_client._delete(
            "ev_opportunities",
            {"timestamp": f"lt.{stale_cutoff}"},
        )
        total_deleted += n
    except Exception as e:
        print(f"  Warning: Failed to delete old opportunities ({e})")

    if total_deleted:
        print(f"  [CLEANUP] Deleted {total_deleted} stale opportunities (>20min old)")

    # 2. Expire stale signals — two bulk PATCHes (no row-by-row).
    total_expired = 0

    # 2a. Expire signals older than 30 minutes — single PATCH.
    try:
        n = db_client._patch(
            "rtm_signals",
            {"status": "eq.active", "created_at": f"lt.{signal_stale_cutoff}"},
            {"status": "expired"},
        )
        total_expired += n
    except Exception as e:
        print(f"  Warning: Failed to expire old signals ({e})")

    # 2b. Expire signals for started games — fetch IDs, bulk PATCH.
    try:
        active_signals = db_client._get(
            "rtm_signals",
            select="id,game_id",
            filters={"status": "eq.active"},
        )
        if active_signals:
            game_ids = list({s["game_id"] for s in active_signals})
            games_data: dict[str, str] = {}
            for i in range(0, len(game_ids), 50):
                chunk = game_ids[i : i + 50]
                id_list = ",".join(chunk)
                try:
                    rows = db_client._get(
                        "games",
                        select="game_id,start_time",
                        filters={"game_id": f"in.({id_list})"},
                    )
                    for r in rows:
                        games_data[r["game_id"]] = r.get("start_time", "")
                except Exception:
                    pass

            now_iso = now.isoformat()
            started_ids = [
                s["id"] for s in active_signals
                if games_data.get(s["game_id"], "") and games_data[s["game_id"]] < now_iso
            ]
            if started_ids:
                db_client._patch_by_ids(
                    "rtm_signals", "id", started_ids,
                    {"status": "expired"},
                )
                total_expired += len(started_ids)
    except Exception as e:
        print(f"  Warning: Failed to expire started-game signals ({e})")

    if total_expired:
        print(f"  [CLEANUP] Expired {total_expired} stale signals")

    # 3. Bulk-repair signals with NULL kelly_size.
    #    Fetch all at once, compute locally, batch-PATCH by groups of 100.
    try:
        null_kelly = db_client._get(
            "rtm_signals",
            select="id,book_odds,edge_percentage",
            filters={"kelly_size": "is.null"},
        )
        if null_kelly:
            repairs: list[dict] = []
            for sig in null_kelly:
                odds = sig.get("book_odds")
                edge = sig.get("edge_percentage")
                if odds and edge is not None:
                    decimal_odds = american_to_decimal(int(odds))
                    if decimal_odds > 1:
                        true_prob = (edge / 100 + 1) / decimal_odds
                        if 0 < true_prob < 1:
                            k = max((true_prob * decimal_odds - 1) / (decimal_odds - 1), 0)
                            repairs.append({"id": sig["id"], "kelly": round(k, 6)})

            # Group by kelly value to minimize PATCH calls.
            by_kelly: dict[float, list[int]] = {}
            for r in repairs:
                by_kelly.setdefault(r["kelly"], []).append(r["id"])
            for kelly_val, ids in by_kelly.items():
                db_client._patch_by_ids(
                    "rtm_signals", "id", ids,
                    {"kelly_size": kelly_val},
                )
            print(f"  [KELLY REPAIR] Updated {len(repairs)} signals with missing kelly_size")
    except Exception as e:
        print(f"  Warning: Kelly repair failed ({e})")


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
        print("[SCAN] Supabase connected OK.")
    except Exception as e:
        print(f"[SCAN] WARNING: Could not connect to Supabase ({e}). Will skip DB writes.")
        print(f"[SCAN] → KenPom snapshots, grading, and other DB features will be disabled.")

    # --- Cleanup stale data before writing new data ---
    if db is not None:
        t0 = time.time()
        try:
            cleanup_stale_data(db)
        except Exception as e:
            print(f"Warning: Stale data cleanup failed ({e})")
        print(f"[TIMING] Stale data cleanup: {time.time() - t0:.1f}s")

    # --- Parallel API fetch for all sports ---
    all_games: list[Game] = []
    all_opportunities: list[EVOpportunity] = []

    def _fetch_sport(sport_key: str) -> tuple[str, list[Game] | None, float]:
        """Fetch mainline odds for one sport. Returns (key, games, elapsed)."""
        t0 = time.time()
        try:
            games = fetch_odds(sport_key, markets=MARKETS, regions=_FETCH_REGIONS)
        except Exception as e:
            print(f"  Skipping {sport_display_name(sport_key)}: {e}")
            return sport_key, None, time.time() - t0
        if games:
            removed = _filter_non_whitelisted_books(games)
            if removed:
                print(f"  [SCAN] {sport_display_name(sport_key)}: filtered {removed} non-whitelisted book entries")
        return sport_key, games if games else None, time.time() - t0

    print(f"[SCAN] Fetching {len(sport_keys)} sports in parallel from regions: {_FETCH_REGIONS} (EU for Pinnacle only)")
    t0_fetch_all = time.time()
    fetch_results: dict[str, tuple[list[Game] | None, float]] = {}
    with ThreadPoolExecutor(max_workers=len(sport_keys)) as pool:
        futures = {pool.submit(_fetch_sport, sk): sk for sk in sport_keys}
        for future in as_completed(futures):
            sport_key, games, elapsed = future.result()
            fetch_results[sport_key] = (games, elapsed)
    print(f"[TIMING] All API fetches (parallel): {time.time() - t0_fetch_all:.1f}s")

    # --- Process each sport sequentially ---
    for sport_key in sport_keys:
        games, fetch_elapsed = fetch_results[sport_key]
        display = sport_display_name(sport_key)

        print(f"\n[SCAN] {display}")
        print(f"  [TIMING] {display} mainline API fetch: {fetch_elapsed:.1f}s")

        if games is None:
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

        # Sharp book presence check — critical for devig quality.
        sharp_present = sorted(k for k in all_book_keys if k in ("pinnacle", "circasports", "bookmaker"))
        if sharp_present:
            names = ", ".join(get_book_name(k) for k in sharp_present)
            print(f"  [SCAN] \u2713 Tier 1 sharp books: {names} — HIGH confidence devig")
        else:
            t2_present = sorted(k for k in all_book_keys if k in ("draftkings", "fanduel", "betonlineag"))
            if t2_present:
                names = ", ".join(get_book_name(k) for k in t2_present)
                print(f"  [SCAN] \u26a0 No Tier 1 sharps — Tier 2 fallback: {names}")
            else:
                print(f"  [SCAN] \u26a0 No sharp books found — falling back to exchanges \u2192 market avg")

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
            t0 = time.time()
            try:
                prop_games = fetch_odds(sport_key, markets=sport_props, regions=_FETCH_REGIONS)
                if prop_games:
                    _filter_non_whitelisted_books(prop_games)
                    merge_prop_data(games, prop_games)
                    print(f"  Props merged for {display}.")
            except Exception as e:
                # API may reject unsupported markets (422) for some sports.
                # Fall back to fetching each market individually.
                print(f"  Warning: Bulk prop fetch failed for {display} ({e}), trying per-market...")
                for mkt_name in sport_props:
                    try:
                        mkt_games = fetch_odds(sport_key, markets=[mkt_name], regions=_FETCH_REGIONS)
                        if mkt_games:
                            _filter_non_whitelisted_books(mkt_games)
                            merge_prop_data(games, mkt_games)
                    except Exception:
                        pass  # Silently skip unsupported markets
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

            # Pinnacle opening/closing history — critical for CLV analysis.
            t0 = time.time()
            try:
                from intelligence.pinnacle_history import store_pinnacle_history
                store_pinnacle_history(db, games)
            except Exception as e:
                print(f"  Warning: Pinnacle history write failed for {display} ({e}).")
            print(f"  [TIMING] {display} pinnacle_history DB write: {time.time() - t0:.1f}s")

        # Scan for +EV: mainlines for ALL games, props for near-term only.
        # Track devig source usage for diagnostics.
        t0 = time.time()
        devig_source_counts: dict[str, int] = {}
        sport_opps: list[EVOpportunity] = []
        for game in games:
            game_opps = scan_game(game)
            # Track which devig sources were used (labels are already clean).
            for opp in game_opps:
                src_label = opp.devig_source or "none"
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

            # Tier summary — show which devig tier was predominantly used.
            tier_counts: dict[int, int] = {}
            for src, cnt in devig_source_counts.items():
                if src.startswith("sharp_avg") or src in ("pinnacle", "circasports", "bookmaker"):
                    tier = 1
                elif src.startswith("market_sharp"):
                    tier = 2
                elif src == "exchange_consensus":
                    tier = 3
                elif src == "market_average":
                    tier = 4
                else:
                    tier = 0
                tier_counts[tier] = tier_counts.get(tier, 0) + cnt
            _tier_labels = {
                1: "Tier 1 (Sharp)",
                2: "Tier 2 (Market Sharp Fallback)",
                3: "Tier 3 (Exchange Consensus)",
                4: "Tier 4 (Market Average)",
            }
            primary_tier = min(t for t in tier_counts if t > 0) if any(t > 0 for t in tier_counts) else 0
            if primary_tier == 1:
                print(f"  [SCAN] \u2713 {_tier_labels[1]}")
            elif primary_tier in _tier_labels:
                print(f"  [SCAN] \u26a0 {_tier_labels[primary_tier]} (no sharp books)")

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

    # --- KenPom refresh (CBB intelligence) ---
    # Build game_projections ONCE here and reuse in the signal engine below.
    # Previously, projections were regenerated in a second pass which could
    # fail if the fanmatch cache TTL expired between passes.
    _cbb_sport_key = "basketball_ncaab"
    _kenpom_client = None
    game_projections: dict[str, dict] = {}
    if any(g.sport_key == _cbb_sport_key for g in all_games):
        t0_kp = time.time()
        try:
            from intelligence.kenpom import KenPomClient

            # Collect all unique Odds API team names from CBB games.
            cbb_teams: list[str] = []
            for g in all_games:
                if g.sport_key == _cbb_sport_key:
                    if g.home_team not in cbb_teams:
                        cbb_teams.append(g.home_team)
                    if g.away_team not in cbb_teams:
                        cbb_teams.append(g.away_team)

            _kenpom_client = KenPomClient(odds_api_teams=cbb_teams)
            _kenpom_client.refresh()
            print(f"  KenPom: refreshed data for {len(cbb_teams)} CBB teams.")

            # Build projections for each CBB game — stored in game_projections
            # dict for reuse by the signal engine (no second lookup needed).
            for g in all_games:
                if g.sport_key != _cbb_sport_key:
                    continue
                proj = _kenpom_client.get_projection(g.home_team, g.away_team)
                if proj:
                    game_projections[g.id] = proj
                    src = proj.get("source", "unknown")
                    home_score = proj.get("home_score", 0)
                    away_score = proj.get("away_score", 0)
                    home_wp = proj.get("home_win_prob", 0)
                    print(
                        f"  KenPom: {g.away_team} @ {g.home_team} -> "
                        f"{away_score:.0f}-{home_score:.0f} "
                        f"(home WP {home_wp:.1%}) [{src}]"
                    )
                else:
                    print(
                        f"  KenPom: {g.away_team} @ {g.home_team} -> "
                        f"no projection available"
                    )
            if game_projections:
                print(f"  [KENPOM] {len(game_projections)} CBB game projections cached for signal engine.")
            else:
                print(f"  [KENPOM] No projections available — CBB projection scoring will be disabled.")
        except Exception as e:
            print(f"  Warning: KenPom refresh failed ({e}).")
        print(f"  [TIMING] KenPom refresh: {time.time() - t0_kp:.1f}s")

    # --- KenPom daily snapshots (projections + Pinnacle odds) ---
    if db is None:
        print("[KENPOM SNAPSHOT] Skipping snapshot save — db is None (no Supabase connection).")
    elif not game_projections:
        print("[KENPOM SNAPSHOT] Skipping snapshot save — no game_projections (no CBB games or KenPom disabled).")
    else:
        print(f"[KENPOM SNAPSHOT] db={type(db).__name__} (not None), {len(game_projections)} projections, {len(all_games)} games")
        t0_snap = time.time()
        try:
            from intelligence.kenpom_snapshots import save_kenpom_snapshots
            snap_count = save_kenpom_snapshots(db, game_projections, all_games)
            if snap_count:
                print(f"  [KENPOM SNAPSHOT] {snap_count} snapshots persisted.")
            else:
                print(f"  [KENPOM SNAPSHOT] No new snapshots saved (may already exist for today).")
        except Exception as e:
            import traceback
            print(f"  [KENPOM SNAPSHOT] ERROR: Snapshot save failed: {e}")
            traceback.print_exc()
        print(f"  [TIMING] KenPom snapshots: {time.time() - t0_snap:.1f}s")

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
            t0_sub = time.time()
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
            print(f"  [TIMING] Book profiler: {time.time() - t0_sub:.1f}s")

            # Detect stale lines.
            t0_sub = time.time()
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
            print(f"  [TIMING] Stale detection: {time.time() - t0_sub:.1f}s")

            # Track line lifecycle (market timing) — batched.
            t0_sub = time.time()
            try:
                timing = MarketTimingEngine(db)

                # Collect all game IDs we need to check.
                game_ids = [g.id for g in all_games]

                # Batch-fetch ALL existing lifecycle keys for these games
                # in a single DB query instead of one per outcome (N+1 fix).
                existing_lifecycle_keys: set[tuple[str, str, str, str]] = set()
                for i in range(0, len(game_ids), 50):
                    chunk_ids = game_ids[i : i + 50]
                    # PostgREST IN filter: game_id=in.(id1,id2,...)
                    id_list = ",".join(chunk_ids)
                    try:
                        existing_rows = db._get(
                            "line_lifecycle",
                            select="game_id,market_type,side,sportsbook",
                            filters={"game_id": f"in.({id_list})"},
                        )
                        for r in existing_rows:
                            existing_lifecycle_keys.add((
                                r["game_id"], r["market_type"],
                                r["side"], r["sportsbook"],
                            ))
                    except Exception:
                        pass

                # Collect new lifecycle rows to batch-insert.
                new_lifecycle_rows: list[dict] = []
                now_iso = datetime.now(timezone.utc).isoformat()
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
                                key = (game.id, mkt.key, side, bk.key)
                                if key not in existing_lifecycle_keys:
                                    new_lifecycle_rows.append({
                                        "game_id": game.id,
                                        "sport": game.sport_key,
                                        "market_type": mkt.key,
                                        "side": side,
                                        "sportsbook": bk.key,
                                        "first_seen_at": now_iso,
                                        "opening_odds": outcome.price,
                                        "game_start_time": game.commence_time,
                                    })
                                    # Mark as seen so we don't insert duplicates
                                    # from the same scan.
                                    existing_lifecycle_keys.add(key)

                if new_lifecycle_rows:
                    db._post_many("line_lifecycle", new_lifecycle_rows)
                    print(f"  Market timing: {len(new_lifecycle_rows)} new line lifecycle(s) tracked.")
            except Exception as e:
                print(f"  Warning: Market timing tracking failed ({e}).")
            print(f"  [TIMING] Market timing: {time.time() - t0_sub:.1f}s")
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

        # Grade KenPom snapshots against final scores.
        try:
            from intelligence.kenpom_snapshots import grade_kenpom_snapshots
            kp_grade = grade_kenpom_snapshots(db)
            if kp_grade["graded"] > 0:
                print(f"  [KENPOM GRADING] {kp_grade['graded']} game(s) graded.")
        except Exception as e:
            import traceback
            print(f"  [KENPOM GRADING] ERROR: Grading failed: {e}")
            traceback.print_exc()

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

            # Reuse KenPom game projections built during the first pass
            # (KenPom refresh section above).  No second lookup needed —
            # game_projections was populated when the cache was fresh.
            if game_projections:
                print(f"  [KENPOM] Passing {len(game_projections)} cached CBB projections to signal engine.")
            else:
                cbb_opps = sum(1 for o in all_opportunities if o.sport_key == _cbb_sport_key)
                if cbb_opps:
                    print(f"  [KENPOM] No cached projections — {cbb_opps} CBB opportunities will score Proj:0.")

            signal_engine = RTMSignal(db_client=db)
            game_ids = list({o.game_id for o in all_opportunities})
            signal_engine.load_cache(game_ids)

            signals = signal_engine.generate_signals(
                opp_dicts_for_signal, player_projections, game_projections
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

    # --- Odds validation ---
    if all_games:
        t0 = time.time()
        try:
            mismatches = validate_odds_mapping(all_games)
            if mismatches:
                print(f"\n[ODDS VALIDATION] {mismatches} mismatch(es) detected — check logs above!")
        except Exception as e:
            print(f"Warning: Odds validation failed ({e}).")
        print(f"[TIMING] Odds validation: {time.time() - t0:.1f}s")

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
