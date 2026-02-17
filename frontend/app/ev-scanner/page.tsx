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

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function EVScannerPage() {
  const [opportunities, setOpportunities] = useState<Opportunity[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [sportFilter, setSportFilter] = useState<SportFilter>("all");

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
      ) : filtered.length === 0 ? (
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
                <th className="px-4 py-3">Book</th>
                <th className="px-4 py-3 text-right">Odds</th>
                <th className="px-4 py-3 text-right">True%</th>
                <th className="px-4 py-3 text-right">Book%</th>
                <th className="px-4 py-3 text-right">EV%</th>
                <th className="px-4 py-3 text-right">Kelly%</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800/50">
              {filtered.map((opp) => (
                <tr
                  key={opp.id}
                  className="transition-colors hover:bg-[#2c2c2e]"
                >
                  <td className="whitespace-nowrap px-4 py-3">
                    <div className="font-medium text-gray-200">
                      {opp.games
                        ? `${opp.games.away_team} @ ${opp.games.home_team}`
                        : opp.game_id}
                    </div>
                    <div className="text-xs text-gray-500">
                      {sportLabel(opp.games?.sport ?? "")}
                    </div>
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-gray-400">
                    {opp.market_type.replace(/_/g, " ")}
                  </td>
                  <td className="px-4 py-3 text-gray-300">{opp.side}</td>
                  <td className="whitespace-nowrap px-4 py-3 text-gray-400">
                    {opp.sportsbook}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-right font-mono text-gray-200">
                    {formatOdds(opp.book_odds)}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-right font-mono text-gray-300">
                    {pct(opp.true_prob * 100)}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-right font-mono text-gray-400">
                    {pct(opp.book_implied_prob * 100)}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-right font-mono font-medium text-emerald-400">
                    +{pct(opp.ev_percentage)}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-right font-mono text-gray-300">
                    {pct(opp.kelly_fraction * 100)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
