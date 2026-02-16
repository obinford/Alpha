#!/usr/bin/env python3
"""Diagnostic scan — runs one cycle with detailed output for debugging.

Shows:
  - How many books per region responded
  - Which sharp books were found
  - What devig source was used for each game
  - Sample Kelly calculations for 3 signals

Usage:
    python scripts/diagnostic_scan.py              # all configured sports
    python scripts/diagnostic_scan.py NBA CBB      # specific sports only
"""

import os
import sys

# Path setup so imports work from repo root.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "shared"))

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from datetime import datetime, timezone

from models.ev_calculator import american_to_decimal, american_to_implied_prob
from models.kelly import kelly_full, kelly_units
from models.devig import devig_market, select_devig_source
from scrapers.odds.odds_api import fetch_odds
from scrapers.odds_scraper import (
    scan_game,
    scan_game_props,
    build_devig_line_map,
    _extract_market_odds_by_book,
    _filter_eu_books,
    _FETCH_REGIONS,
    resolve_sport_keys,
    hours_until_start,
    format_american,
    EVOpportunity,
)
from config import (
    ODDS_API_SPORT_KEYS,
    ODDS_API_REGIONS,
    MARKETS,
    SPORT_DISPLAY_NAMES,
    get_prop_markets_for_sport,
    PROP_WINDOW_HOURS,
)
from books import get_book_info, get_book_tier, get_book_name

W = 100


def banner(text: str) -> None:
    print(f"\n{'=' * W}")
    print(f"  {text}")
    print(f"{'=' * W}")


def section(text: str) -> None:
    print(f"\n{'─' * W}")
    print(f"  {text}")
    print(f"{'─' * W}")


def run_diagnostic(sport_keys: list[str]) -> None:
    banner(
        f"RTM DIAGNOSTIC SCAN — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}"
    )
    print(f"  Configured regions: {ODDS_API_REGIONS}")
    print(f"  Sports to scan: {len(sport_keys)}")

    all_opportunities: list[EVOpportunity] = []
    all_devig_sources: dict[str, int] = {}

    for sport_key in sport_keys:
        display = SPORT_DISPLAY_NAMES.get(sport_key, sport_key)
        section(f"SPORT: {display} ({sport_key})")

        # ── Fetch odds ──────────────────────────────────────────────
        try:
            games = fetch_odds(sport_key, markets=MARKETS, regions=_FETCH_REGIONS)
            if games:
                eu_removed = _filter_eu_books(games)
                if eu_removed:
                    print(f"  Filtered {eu_removed} EU soft book entries (keeping Pinnacle only)")
        except Exception as e:
            print(f"  ✗ Fetch FAILED: {e}")
            continue

        if not games:
            print(f"  No games available.")
            continue

        print(f"  Games found: {len(games)}")

        # ── Book discovery by region ────────────────────────────────
        all_book_keys: set[str] = set()
        for g in games:
            for bk in g.bookmakers:
                all_book_keys.add(bk.key)

        region_counts: dict[str, list[str]] = {}
        for bk_key in sorted(all_book_keys):
            info = get_book_info(bk_key)
            region = info.get("region", "unknown")
            region_counts.setdefault(region, []).append(bk_key)

        print(f"\n  Books by region ({len(all_book_keys)} total):")
        for region in sorted(region_counts.keys()):
            books = region_counts[region]
            names = [get_book_name(k) for k in books]
            print(f"    {region:>8}: {len(books)} books — {', '.join(names)}")

        # ── Sharp book check ────────────────────────────────────────
        sharp = sorted(k for k in all_book_keys if get_book_tier(k) == "sharp")
        exchange = sorted(k for k in all_book_keys if get_book_tier(k) == "exchange")

        print(f"\n  Sharp books: {', '.join(get_book_name(k) for k in sharp) or 'NONE'}")
        print(f"  Exchanges:   {', '.join(get_book_name(k) for k in exchange) or 'NONE'}")

        # ── Pinnacle check ──────────────────────────────────────────
        if "pinnacle" in all_book_keys:
            print(f"\n  ✓ PINNACLE PRESENT — HIGH confidence devig available")
        else:
            print(f"\n  ⚠ PINNACLE NOT FOUND")
            if "eu" in ODDS_API_REGIONS:
                print(f"    EU region is configured but Pinnacle data is missing.")
                print(f"    Possible causes:")
                print(f"      1. API plan may not support EU region (need $59+ plan)")
                print(f"      2. Pinnacle may not cover this sport")
                print(f"      3. API returned EU books but with a different key")
                # Check if any EU books came back at all.
                eu_books = region_counts.get("eu", [])
                if eu_books:
                    print(f"    EU books found: {', '.join(get_book_name(k) for k in eu_books)}")
                    print(f"    → EU region IS working, but Pinnacle not present for this sport")
                else:
                    print(f"    No EU books found at all → EU region call is FAILING SILENTLY")
                    print(f"    → Check API plan tier and THE_ODDS_API_KEY validity")

        # ── Devig source per game ───────────────────────────────────
        print(f"\n  Devig source per game:")
        game_devig_sources: dict[str, int] = {}

        for game in games[:20]:  # Cap to first 20 games for readability.
            label = f"{game.away_team} @ {game.home_team}"
            game_sources = set()

            for mkt in ("h2h", "spreads", "totals"):
                true_probs, source, confidence, method = build_devig_line_map(
                    game, mkt
                )
                if source:
                    game_sources.add(source)
                    # Simplify for summary.
                    if source == "pinnacle":
                        src_label = "pinnacle"
                    elif source.startswith("exchange:"):
                        src_label = "exchange"
                    elif source.startswith("sharp:"):
                        src_label = "sharp"
                    elif source.startswith("market_avg:"):
                        src_label = "market_avg"
                    else:
                        src_label = source
                    game_devig_sources[src_label] = game_devig_sources.get(src_label, 0) + 1
                    all_devig_sources[src_label] = all_devig_sources.get(src_label, 0) + 1

            src_display = ", ".join(sorted(game_sources)) if game_sources else "none"
            print(f"    {label:<50} → {src_display}")

        if len(games) > 20:
            print(f"    ... and {len(games) - 20} more games")

        print(f"\n  Devig source summary ({display}):")
        for src, count in sorted(game_devig_sources.items(), key=lambda x: -x[1]):
            print(f"    {src:<25} {count} market(s)")

        # ── Scan for +EV ────────────────────────────────────────────
        sport_opps: list[EVOpportunity] = []
        for game in games:
            sport_opps.extend(scan_game(game))
            h = hours_until_start(game)
            if -3 < h <= PROP_WINDOW_HOURS:
                sport_opps.extend(scan_game_props(game))

        print(f"\n  +EV opportunities found: {len(sport_opps)}")
        all_opportunities.extend(sport_opps)

    # ── Global devig source summary ─────────────────────────────
    if all_devig_sources:
        section("DEVIG SOURCE SUMMARY (ALL SPORTS)")
        for src, count in sorted(all_devig_sources.items(), key=lambda x: -x[1]):
            print(f"  {src:<25} {count} market(s)")

    # ── Sample Kelly calculations ───────────────────────────────
    if all_opportunities:
        section("SAMPLE KELLY CALCULATIONS (top 3 by EV%)")
        all_opportunities.sort(key=lambda o: o.ev_pct, reverse=True)
        samples = all_opportunities[:3]

        for i, opp in enumerate(samples, 1):
            dec = american_to_decimal(opp.book_odds)
            b = dec - 1
            p = opp.true_prob
            q = 1 - p
            imp = american_to_implied_prob(opp.book_odds)
            fk = kelly_full(p, opp.book_odds)
            units = kelly_units(p, opp.book_odds)

            print(f"\n  Sample {i}: {opp.selection}")
            print(f"    Game:        {opp.game}")
            print(f"    Book:        {opp.book} ({opp.book_key})")
            print(f"    Odds:        {format_american(opp.book_odds)} (decimal: {dec:.4f})")
            print(f"    Implied prob: {imp:.4f} ({imp*100:.2f}%)")
            print(f"    True prob:   {p:.4f} ({p*100:.2f}%)")
            print(f"    EV%:         {opp.ev_pct:+.2f}%")
            print(f"    Devig src:   {opp.devig_source} (confidence: {opp.devig_confidence})")
            print(f"    ── Kelly breakdown ──")
            print(f"    b = dec - 1           = {b:.4f}")
            print(f"    full_kelly = (b*p-q)/b = ({b:.4f}*{p:.4f}-{q:.4f})/{b:.4f}")
            print(f"                         = ({b*p:.4f}-{q:.4f})/{b:.4f}")
            print(f"                         = {b*p-q:.4f}/{b:.4f}")
            print(f"                         = {fk:.6f}")
            print(f"    quarter_kelly         = {fk:.6f} * 0.25 = {fk*0.25:.6f}")
            print(f"    units                 = {fk*0.25:.6f} * 100 = {units:.2f}u")

    # ── Final summary ───────────────────────────────────────────
    banner("DIAGNOSTIC COMPLETE")
    print(f"  Total opportunities: {len(all_opportunities)}")

    # Count by devig confidence.
    conf_counts: dict[str, int] = {}
    for opp in all_opportunities:
        c = opp.devig_confidence or "unknown"
        conf_counts[c] = conf_counts.get(c, 0) + 1
    if conf_counts:
        conf_str = ", ".join(f"{k}={v}" for k, v in sorted(conf_counts.items(), key=lambda x: -x[1]))
        print(f"  Confidence breakdown: {conf_str}")

    pinnacle_opps = sum(1 for o in all_opportunities if o.devig_source == "pinnacle")
    print(f"  Pinnacle-sourced opportunities: {pinnacle_opps}/{len(all_opportunities)}")

    if pinnacle_opps == 0:
        print(f"\n  ⚠ ZERO opportunities used Pinnacle as devig source.")
        print(f"    This means Pinnacle odds are NOT flowing into the pipeline.")
        print(f"    Check: API plan tier, region config, and sport coverage.")
    else:
        pct = pinnacle_opps / len(all_opportunities) * 100
        print(f"  Pinnacle coverage: {pct:.1f}% of all opportunities")
    print()


if __name__ == "__main__":
    cli_sports = sys.argv[1:]
    sport_keys = resolve_sport_keys(cli_sports)
    if not sport_keys:
        print("No active sports found.")
        sys.exit(1)
    run_diagnostic(sport_keys)
