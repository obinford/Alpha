"use client";

import { useEffect, useState } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "";

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

/** A group of opportunities for the same game + market + side. */
interface OppGroup {
  key: string;
  game: Game | null;
  game_id: string;
  market_type: string;
  side: string;
  sport: string;
  /** Best opportunity (highest EV%) shown in the collapsed row. */
  best: Opportunity;
  /** All other opportunities sorted by EV% descending. */
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

/** Group flat opportunity list into OppGroup[] keyed by game+market+side. */
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
    // Sort by EV% descending — first item is the best.
    list.sort((a, b) => (b.ev_percentage ?? 0) - (a.ev_percentage ?? 0));
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

  // Sort groups by best EV% descending.
  groups.sort((a, b) => (b.best.ev_percentage ?? 0) - (a.best.ev_percentage ?? 0));
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

  const filtered =
    sportFilter === "all"
      ? opportunities
      : opportunities.filter(
          (o) => o.games?.sport === sportFilter,
        );

  const groups = groupOpportunities(filtered);

  function toggleExpanded(key: string) {
    setExpandedKeys((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

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

      {/* Status bar */}
      <div className="mt-4 flex items-center gap-3">
        <span className="text-xs text-gray-500">
          {groups.length} market{groups.length === 1 ? "" : "s"} &middot;{" "}
          {filtered.length} opportunit{filtered.length === 1 ? "y" : "ies"}
        </span>
        {!loading && !error && (
          <span className="inline-flex items-center gap-1 text-xs text-emerald-400">
            <span className="inline-block h-1.5 w-1.5 rounded-full bg-emerald-400" />
            Live
          </span>
        )}
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
                <th className="px-4 py-3 text-right">Kelly%</th>
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

function GroupRows({
  group,
  opp,
  isExpanded,
  moreCount,
  onToggle,
}: {
  group: OppGroup;
  opp: Opportunity;
  isExpanded: boolean;
  moreCount: number;
  onToggle: () => void;
}) {
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
          <div className="font-medium text-gray-200">
            {group.game
              ? `${group.game.away_team} @ ${group.game.home_team}`
              : group.game_id}
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
          {pct((opp.kelly_fraction ?? 0) * 100)}
        </td>
      </tr>

      {/* Expanded sub-rows */}
      {isExpanded &&
        group.rest.map((alt) => (
          <tr key={alt.id} className="bg-[#1e1e20]">
            <td className="px-4 py-2" />
            <td className="px-4 py-2" />
            <td className="px-4 py-2" />
            <td className="whitespace-nowrap px-4 py-2 text-gray-500">
              {alt.sportsbook}
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
              {pct((alt.kelly_fraction ?? 0) * 100)}
            </td>
          </tr>
        ))}
    </>
  );
}
