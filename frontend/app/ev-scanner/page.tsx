"use client";

import { useEffect, useMemo, useState } from "react";
import { useBankroll } from "@/lib/bankroll-context";
import { getSportsbookUrl } from "@/lib/sportsbook-links";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "";

// Books to hide from all displays
const BLOCKED_BOOKS = new Set(["betparx"]);

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface Game {
  game_id: string;
  sport: string;
  home_team: string;
  away_team: string;
  start_time: string;
}

interface Opportunity {
  id: number;
  game_id: string;
  sportsbook: string;
  market_type: string;
  side: string;
  book_odds: number;
  book_implied_prob: number;
  true_prob: number;
  ev_percentage: number;
  kelly_fraction: number;
  recommended_units: number;
  timestamp: string;
  status: string;
  games: Game;
}

interface OppGroup {
  key: string;
  game: Game | null;
  game_id: string;
  market_type: string;
  side: string;
  sport: string;
  best: Opportunity;
  rest: Opportunity[];
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const SPORT_TABS = [
  { key: "all", label: "All" },
  { key: "basketball_ncaab", label: "CBB" },
  { key: "basketball_nba", label: "NBA" },
  { key: "icehockey_nhl", label: "NHL" },
] as const;

type SportFilter = (typeof SPORT_TABS)[number]["key"];

function sportLabel(sport: string): string {
  const map: Record<string, string> = {
    basketball_nba: "NBA",
    basketball_ncaab: "CBB",
    icehockey_nhl: "NHL",
    americanfootball_nfl: "NFL",
    americanfootball_ncaaf: "CFB",
    baseball_mlb: "MLB",
  };
  return map[sport] ?? sport.replace(/_/g, " ").toUpperCase();
}

function formatOdds(odds: number): string {
  return odds > 0 ? `+${odds}` : String(odds);
}

function pct(value: number): string {
  return `${value.toFixed(1)}%`;
}

function trueProbToAmericanOdds(prob: number): number {
  if (prob <= 0 || prob >= 1) return -110;
  if (prob > 0.5) return Math.round((-100 * prob) / (1 - prob));
  return Math.round((100 * (1 - prob)) / prob);
}

/** Determine the calendar date label for a start_time string. */
function dateLabel(isoString: string): string {
  const d = new Date(isoString);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const tomorrow = new Date(today);
  tomorrow.setDate(tomorrow.getDate() + 1);
  const dayAfter = new Date(tomorrow);
  dayAfter.setDate(dayAfter.getDate() + 1);

  const gameDay = new Date(d);
  gameDay.setHours(0, 0, 0, 0);

  if (gameDay.getTime() === today.getTime()) return "Today";
  if (gameDay.getTime() === tomorrow.getTime()) return "Tomorrow";
  return d.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });
}

/** Fix 6: Time badge for upcoming games */
function TimeBadge({ startTime }: { startTime: string }) {
  const diff = new Date(startTime).getTime() - Date.now();
  if (diff <= 0) return null;
  const minutes = diff / 60000;
  if (minutes <= 10) {
    return (
      <span className="ml-2 rounded bg-red-500/20 px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wider text-red-400 animate-pulse">
        Locking Soon
      </span>
    );
  }
  if (minutes <= 30) {
    return (
      <span className="ml-2 rounded bg-amber-500/20 px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wider text-amber-400">
        Starting Soon
      </span>
    );
  }
  return null;
}

/** Fix 5: Bet link button — links to sport-specific page when available */
function BetLink({ book, sport }: { book: string; sport?: string }) {
  const url = getSportsbookUrl(book, sport);
  if (!url) return null;
  return (
    <a
      href={url}
      target="_blank"
      rel="noopener noreferrer"
      className="ml-2 inline-flex items-center rounded bg-emerald-600/20 px-1.5 py-0.5 text-[9px] font-semibold text-emerald-400 transition-colors hover:bg-emerald-600/40"
      onClick={(e) => e.stopPropagation()}
    >
      Bet &rarr;
    </a>
  );
}

function groupOpportunities(opps: Opportunity[]): OppGroup[] {
  const map = new Map<string, Opportunity[]>();

  for (const opp of opps) {
    const key = `${opp.game_id}|${opp.market_type}|${opp.side}`;
    let list = map.get(key);
    if (!list) {
      list = [];
      map.set(key, list);
    }
    list.push(opp);
  }

  const groups: OppGroup[] = [];
  for (const [key, list] of Array.from(map.entries())) {
    // Sort by Kelly fraction descending within each group (best sizing first)
    list.sort((a, b) => (b.kelly_fraction ?? 0) - (a.kelly_fraction ?? 0));
    const best = list[0];
    groups.push({
      key,
      game: best.games ?? null,
      game_id: best.game_id,
      market_type: best.market_type,
      side: best.side,
      sport: best.games?.sport ?? "",
      best,
      rest: list.slice(1),
    });
  }

  // Sort groups by Kelly fraction descending (highest Kelly = best bet)
  groups.sort(
    (a, b) => (b.best.kelly_fraction ?? 0) - (a.best.kelly_fraction ?? 0),
  );
  return groups;
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function EVScannerPage() {
  const [opportunities, setOpportunities] = useState<Opportunity[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [sportFilter, setSportFilter] = useState<SportFilter>("all");
  const [expandedKeys, setExpandedKeys] = useState<Set<string>>(new Set());

  // Book filter state
  const [selectedBooks, setSelectedBooks] = useState<Set<string> | null>(null); // null = all
  // Day filter state
  const [selectedDays, setSelectedDays] = useState<Set<string> | null>(null); // null = all

  const { bankroll, kellyBetSize, kellyMultiplier, kellyLabel } = useBankroll();

  useEffect(() => {
    setLoading(true);
    setError(null);
    fetch(`${API_BASE}/api/ev-opportunities/`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((data) => {
        setOpportunities(data.opportunities ?? []);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  // Derive unique books & days from all opportunities, excluding blocked books
  const allBooks = useMemo(() => {
    const s = new Set<string>();
    for (const o of opportunities) {
      if (!BLOCKED_BOOKS.has(o.sportsbook)) s.add(o.sportsbook);
    }
    return Array.from(s).sort();
  }, [opportunities]);

  const allDays = useMemo(() => {
    const s = new Set<string>();
    for (const o of opportunities) {
      if (o.games?.start_time) s.add(dateLabel(o.games.start_time));
    }
    // Sort: Today first, Tomorrow second, then alphabetical
    const order = ["Today", "Tomorrow"];
    return Array.from(s).sort((a, b) => {
      const ai = order.indexOf(a);
      const bi = order.indexOf(b);
      if (ai !== -1 && bi !== -1) return ai - bi;
      if (ai !== -1) return -1;
      if (bi !== -1) return 1;
      return a.localeCompare(b);
    });
  }, [opportunities]);

  // Apply all filters: sport, book, day, blocked books, and live games (Fix 6)
  const filtered = useMemo(() => {
    const now = Date.now();
    return opportunities.filter((o) => {
      // Fix 2: Block books
      if (BLOCKED_BOOKS.has(o.sportsbook)) return false;
      // Fix 6: Hide live games
      if (o.games?.start_time) {
        const start = new Date(o.games.start_time).getTime();
        if (start <= now) return false;
      }
      // Sport filter
      if (sportFilter !== "all" && o.games?.sport !== sportFilter) return false;
      // Book filter
      if (selectedBooks != null && !selectedBooks.has(o.sportsbook)) return false;
      // Day filter
      if (selectedDays != null && o.games?.start_time) {
        if (!selectedDays.has(dateLabel(o.games.start_time))) return false;
      }
      return true;
    });
  }, [opportunities, sportFilter, selectedBooks, selectedDays]);

  const groups = groupOpportunities(filtered);

  function toggleExpanded(key: string) {
    setExpandedKeys((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  function toggleBook(book: string) {
    setSelectedBooks((prev) => {
      if (prev == null) {
        // Currently "all" — switch to all-except-this
        const next = new Set(allBooks);
        next.delete(book);
        return next;
      }
      const next = new Set(prev);
      if (next.has(book)) {
        next.delete(book);
      } else {
        next.add(book);
      }
      // If all are selected, go back to null (show all)
      if (next.size === allBooks.length) return null;
      return next;
    });
  }

  function toggleDay(day: string) {
    setSelectedDays((prev) => {
      if (prev == null) {
        const next = new Set(allDays);
        next.delete(day);
        return next;
      }
      const next = new Set(prev);
      if (next.has(day)) {
        next.delete(day);
      } else {
        next.add(day);
      }
      if (next.size === allDays.length) return null;
      return next;
    });
  }

  function isBookSelected(book: string): boolean {
    return selectedBooks == null || selectedBooks.has(book);
  }

  function isDaySelected(day: string): boolean {
    return selectedDays == null || selectedDays.has(day);
  }

  const effectiveBankroll = bankroll ?? 1000;

  return (
    <div>
      <h1 className="text-2xl font-bold">EV Scanner</h1>
      <p className="mt-1 text-sm text-gray-500">
        Real-time positive expected value opportunities across sportsbooks.
      </p>

      {/* Sport filter tabs */}
      <div className="mt-6 inline-flex rounded-xl bg-[#1c1c1e] p-1">
        {SPORT_TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => setSportFilter(t.key)}
            className={`rounded-lg px-5 py-2 text-sm font-medium transition-colors ${
              sportFilter === t.key
                ? "bg-[#2c2c2e] text-white shadow-sm"
                : "text-gray-400 hover:text-gray-200"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Day filter */}
      {allDays.length > 0 && (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <span className="text-[10px] font-medium uppercase tracking-wider text-gray-600">
            Day:
          </span>
          <button
            onClick={() => setSelectedDays(null)}
            className={`rounded-lg px-3 py-1 text-xs font-medium transition-colors ${
              selectedDays == null
                ? "bg-[#2c2c2e] text-white"
                : "text-gray-500 hover:text-gray-300"
            }`}
          >
            All
          </button>
          {allDays.map((day) => (
            <button
              key={day}
              onClick={() => toggleDay(day)}
              className={`rounded-lg px-3 py-1 text-xs font-medium transition-colors ${
                isDaySelected(day) && selectedDays != null
                  ? "bg-[#2c2c2e] text-white"
                  : isDaySelected(day)
                    ? "text-gray-400 hover:text-gray-200"
                    : "text-gray-600 hover:text-gray-400"
              }`}
            >
              {day}
            </button>
          ))}
        </div>
      )}

      {/* Book filter */}
      {allBooks.length > 0 && (
        <div className="mt-3 flex flex-wrap items-center gap-1.5">
          <span className="mr-1 text-[10px] font-medium uppercase tracking-wider text-gray-600">
            Books:
          </span>
          <button
            onClick={() => setSelectedBooks(null)}
            className={`rounded-full px-2.5 py-1 text-[11px] font-medium transition-colors ${
              selectedBooks == null
                ? "bg-emerald-600 text-white"
                : "bg-[#2c2c2e] text-gray-500 hover:text-gray-300"
            }`}
          >
            All
          </button>
          <button
            onClick={() => setSelectedBooks(new Set())}
            className="rounded-full bg-[#2c2c2e] px-2.5 py-1 text-[11px] text-gray-500 transition-colors hover:text-gray-300"
          >
            Clear
          </button>
          {allBooks.map((book) => (
            <button
              key={book}
              onClick={() => toggleBook(book)}
              className={`rounded-full px-2.5 py-1 text-[11px] font-medium transition-colors ${
                isBookSelected(book)
                  ? "bg-emerald-600/80 text-white"
                  : "bg-[#2c2c2e] text-gray-500 hover:text-gray-300"
              }`}
            >
              {book}
            </button>
          ))}
        </div>
      )}

      {/* Status bar */}
      <div className="mt-4 flex items-center gap-3">
        <span className="text-xs text-gray-500">
          Showing {filtered.length} of {opportunities.length} opportunit
          {opportunities.length === 1 ? "y" : "ies"} &middot; {groups.length}{" "}
          market{groups.length === 1 ? "" : "s"}
        </span>
        {!loading && !error && (
          <span className="inline-flex items-center gap-1 text-xs text-emerald-400">
            <span className="inline-block h-1.5 w-1.5 rounded-full bg-emerald-400" />
            Live
          </span>
        )}
        <span className="text-xs text-gray-600">
          {kellyLabel} &middot; Bankroll: ${effectiveBankroll.toLocaleString()}
        </span>
      </div>

      {/* Table */}
      {loading ? (
        <div className="mt-12 text-center text-gray-500">Loading...</div>
      ) : error ? (
        <div className="mt-12 text-center text-red-400">
          Failed to load: {error}
        </div>
      ) : groups.length === 0 ? (
        <div className="mt-12 text-center text-gray-500">
          No +EV opportunities found.
        </div>
      ) : (
        <div className="mt-4 overflow-x-auto rounded-2xl bg-[#1c1c1e]">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-gray-800 text-xs font-medium uppercase tracking-wider text-gray-500">
                <th className="px-4 py-3">Game</th>
                <th className="px-4 py-3">Market</th>
                <th className="px-4 py-3">Selection</th>
                <th className="px-4 py-3">Best Book</th>
                <th className="px-4 py-3 text-right">Odds</th>
                <th className="px-4 py-3 text-right">True%</th>
                <th className="px-4 py-3 text-right">Book%</th>
                <th className="px-4 py-3 text-right">EV%</th>
                <th className="px-4 py-3 text-right">Kelly</th>
                <th className="px-4 py-3 text-right">Bet Size</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800/50">
              {groups.map((g) => {
                const opp = g.best;
                const isExpanded = expandedKeys.has(g.key);
                const moreCount = g.rest.length;

                return (
                  <GroupRows
                    key={g.key}
                    group={g}
                    opp={opp}
                    isExpanded={isExpanded}
                    moreCount={moreCount}
                    onToggle={() => toggleExpanded(g.key)}
                    kellyBetSize={kellyBetSize}
                    kellyMultiplier={kellyMultiplier}
                  />
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Group row component (primary + expandable sub-rows)
// ---------------------------------------------------------------------------

function formatKellySize(kellyFraction: number, kellyMult: number, bankroll: number | null): string {
  const units = kellyFraction * kellyMult * 100;
  const dollars = bankroll != null ? kellyFraction * kellyMult * bankroll : null;
  if (units <= 0) return "\u2014";
  const unitStr = `${units.toFixed(2)}u`;
  if (dollars != null) return `${unitStr} ($${dollars.toFixed(0)})`;
  return unitStr;
}

function GroupRows({
  group,
  opp,
  isExpanded,
  moreCount,
  onToggle,
  kellyBetSize,
  kellyMultiplier,
}: {
  group: OppGroup;
  opp: Opportunity;
  isExpanded: boolean;
  moreCount: number;
  onToggle: () => void;
  kellyBetSize: (fraction: number) => number | null;
  kellyMultiplier: number;
}) {
  const betAmt = kellyBetSize(opp.kelly_fraction ?? 0);
  const kellyPct = (opp.kelly_fraction ?? 0) * kellyMultiplier * 100;
  const startTime = group.game?.start_time ?? null;

  return (
    <>
      {/* Primary row (best EV%) */}
      <tr
        className={`transition-colors ${
          moreCount > 0 ? "cursor-pointer" : ""
        } ${isExpanded ? "bg-[#242426]" : "hover:bg-[#2c2c2e]"}`}
        onClick={moreCount > 0 ? onToggle : undefined}
      >
        <td className="whitespace-nowrap px-4 py-3">
          <div className="flex items-center">
            <span className="font-medium text-gray-200">
              {group.game
                ? `${group.game.away_team} @ ${group.game.home_team}`
                : group.game_id}
            </span>
            {/* Fix 6: Time badge */}
            {startTime && <TimeBadge startTime={startTime} />}
          </div>
          <div className="text-xs text-gray-500">
            {sportLabel(group.sport)}
          </div>
        </td>
        <td className="whitespace-nowrap px-4 py-3 text-gray-400">
          {opp.market_type.replace(/_/g, " ")}
        </td>
        <td className="px-4 py-3 text-gray-300">{opp.side}</td>
        <td className="whitespace-nowrap px-4 py-3 text-gray-400">
          <span>{opp.sportsbook}</span>
          <BetLink book={opp.sportsbook} sport={opp.games?.sport} />
          {moreCount > 0 && (
            <span className="ml-2 rounded bg-[#2c2c2e] px-1.5 py-0.5 text-xs text-gray-500">
              +{moreCount} more
            </span>
          )}
        </td>
        <td className="whitespace-nowrap px-4 py-3 text-right font-mono text-gray-200">
          {formatOdds(opp.book_odds)}
        </td>
        <td className="whitespace-nowrap px-4 py-3 text-right font-mono text-gray-300">
          {pct((opp.true_prob ?? 0) * 100)}
        </td>
        <td className="whitespace-nowrap px-4 py-3 text-right font-mono text-gray-400">
          {pct((opp.book_implied_prob ?? 0) * 100)}
        </td>
        <td className="whitespace-nowrap px-4 py-3 text-right font-mono font-medium text-emerald-400">
          +{pct(opp.ev_percentage ?? 0)}
        </td>
        <td className="whitespace-nowrap px-4 py-3 text-right font-mono text-gray-300">
          {kellyPct > 0 ? pct(kellyPct) : "\u2014"}
        </td>
        <td className="whitespace-nowrap px-4 py-3 text-right font-mono text-emerald-300">
          {betAmt != null && betAmt > 0 ? `${kellyPct.toFixed(2)}u ($${betAmt.toFixed(0)})` : "\u2014"}
        </td>
      </tr>

      {/* Expanded: Pinnacle sharp reference row — Fix 3: always on top */}
      {isExpanded && (
        <tr className="border-l-2 border-l-blue-500 bg-[#18181b]">
          <td className="px-4 py-2" />
          <td className="px-4 py-2" />
          <td className="px-4 py-2" />
          <td className="whitespace-nowrap px-4 py-2 text-blue-400">
            <span className="font-medium">Pinnacle</span>
            <span className="ml-2 rounded bg-blue-500/20 px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider text-blue-400">
              Sharp
            </span>
          </td>
          <td className="whitespace-nowrap px-4 py-2 text-right font-mono text-blue-300">
            {formatOdds(trueProbToAmericanOdds(opp.true_prob ?? 0.5))}
          </td>
          <td className="whitespace-nowrap px-4 py-2 text-right font-mono text-blue-300/70">
            {pct((opp.true_prob ?? 0) * 100)}
          </td>
          <td className="whitespace-nowrap px-4 py-2 text-right font-mono text-blue-300/70">
            {pct((opp.true_prob ?? 0) * 100)}
          </td>
          <td className="whitespace-nowrap px-4 py-2 text-right font-mono text-gray-600">
            0.0%
          </td>
          <td className="whitespace-nowrap px-4 py-2 text-right font-mono text-gray-600">
            0.0%
          </td>
          <td className="px-4 py-2" />
        </tr>
      )}

      {/* Expanded sub-rows — sorted by Kelly descending */}
      {isExpanded &&
        group.rest.map((alt) => {
          const altBet = kellyBetSize(alt.kelly_fraction ?? 0);
          const altKellyPct = (alt.kelly_fraction ?? 0) * kellyMultiplier * 100;
          return (
            <tr key={alt.id} className="bg-[#1e1e20]">
              <td className="px-4 py-2" />
              <td className="px-4 py-2" />
              <td className="px-4 py-2" />
              <td className="whitespace-nowrap px-4 py-2 text-gray-500">
                {alt.sportsbook}
                <BetLink book={alt.sportsbook} sport={opp.games?.sport} />
              </td>
              <td className="whitespace-nowrap px-4 py-2 text-right font-mono text-gray-400">
                {formatOdds(alt.book_odds)}
              </td>
              <td className="whitespace-nowrap px-4 py-2 text-right font-mono text-gray-500">
                {pct((alt.true_prob ?? 0) * 100)}
              </td>
              <td className="whitespace-nowrap px-4 py-2 text-right font-mono text-gray-500">
                {pct((alt.book_implied_prob ?? 0) * 100)}
              </td>
              <td className="whitespace-nowrap px-4 py-2 text-right font-mono text-emerald-400/70">
                +{pct(alt.ev_percentage ?? 0)}
              </td>
              <td className="whitespace-nowrap px-4 py-2 text-right font-mono text-gray-500">
                {altKellyPct > 0 ? pct(altKellyPct) : "\u2014"}
              </td>
              <td className="whitespace-nowrap px-4 py-2 text-right font-mono text-emerald-300/60">
                {altBet != null && altBet > 0 ? `${altKellyPct.toFixed(2)}u ($${altBet.toFixed(0)})` : "\u2014"}
              </td>
            </tr>
          );
        })}
    </>
  );
}
