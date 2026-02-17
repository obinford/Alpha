"use client";

import { useEffect, useState } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface Signal {
  id: number;
  game_id: string;
  sport: string;
  market_type: string;
  side: string;
  player_name: string | null;
  sportsbook: string;
  book_odds: number;
  signal_strength: number;
  star_rating: number;
  ev_score: number;
  steam_score: number;
  projection_score: number | null;
  consensus_score: number;
  edge_percentage: number;
  kelly_size: number | null;
  created_at: string;
}

interface Game {
  sport: string;
  home_team: string;
  away_team: string;
  start_time: string;
}

interface Opportunity {
  id: number;
  game_id: string;
  ev_percentage: number;
  games: Game;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function StatCard({
  label,
  value,
  sub,
  accent,
}: {
  label: string;
  value: string;
  sub?: string;
  accent?: "green" | "red" | "neutral";
}) {
  const color =
    accent === "green"
      ? "text-emerald-400"
      : accent === "red"
        ? "text-red-400"
        : "text-white";
  return (
    <div className="rounded-2xl bg-[#1c1c1e] p-5">
      <p className="text-xs font-medium uppercase tracking-wider text-gray-500">
        {label}
      </p>
      <p className={`mt-1 text-2xl font-bold ${color}`}>{value}</p>
      {sub && <p className="mt-0.5 text-xs text-gray-500">{sub}</p>}
    </div>
  );
}

function Stars({ count }: { count: number }) {
  return (
    <span className="text-amber-400">
      {"★".repeat(count)}
      <span className="text-gray-700">{"★".repeat(5 - count)}</span>
    </span>
  );
}

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

function strengthColor(strength: number): string {
  if (strength >= 70) return "text-emerald-400";
  if (strength >= 55) return "text-amber-400";
  return "text-gray-300";
}

function formatTimeUntil(isoString: string): string {
  const diff = new Date(isoString).getTime() - Date.now();
  if (diff < 0) return "Live";
  const hours = Math.floor(diff / 3600000);
  const minutes = Math.floor((diff % 3600000) / 60000);
  if (hours > 0) return `${hours}h ${minutes}m`;
  return `${minutes}m`;
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function DashboardPage() {
  const [signals, setSignals] = useState<Signal[]>([]);
  const [oppCount, setOppCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      fetch(`${API_BASE}/api/signals/active`).then((r) => {
        if (!r.ok) throw new Error(`Signals: HTTP ${r.status}`);
        return r.json();
      }),
      fetch(`${API_BASE}/api/ev-opportunities/`).then((r) => {
        if (!r.ok) throw new Error(`Opportunities: HTTP ${r.status}`);
        return r.json();
      }),
    ])
      .then(([sigData, oppData]) => {
        setSignals(sigData.signals ?? []);
        setOppCount(oppData.count ?? 0);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  const topSignal = signals.length > 0 ? signals[0] : null;
  const nextGameTime = signals
    .map((s) => s.created_at)
    .filter(Boolean)
    .sort()[0];

  if (loading) {
    return (
      <div>
        <h1 className="text-2xl font-bold">Dashboard</h1>
        <div className="mt-12 text-center text-gray-500">Loading...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div>
        <h1 className="text-2xl font-bold">Dashboard</h1>
        <div className="mt-12 text-center text-red-400">
          Failed to load: {error}
        </div>
      </div>
    );
  }

  return (
    <div>
      <h1 className="text-2xl font-bold">Dashboard</h1>
      <p className="mt-1 text-sm text-gray-500">
        Overview of today&apos;s picks, active signals, and key metrics.
      </p>

      {/* Stat cards */}
      <div className="mt-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatCard
          label="Active Signals"
          value={String(signals.length)}
          accent={signals.length > 0 ? "green" : "neutral"}
        />
        <StatCard
          label="Opportunities"
          value={String(oppCount)}
          sub="Current scan"
        />
        <StatCard
          label="Top Signal"
          value={
            topSignal
              ? `${topSignal.signal_strength.toFixed(1)}`
              : "---"
          }
          sub={topSignal ? `${topSignal.star_rating}★ ${sportLabel(topSignal.sport)}` : undefined}
          accent={topSignal && topSignal.star_rating >= 4 ? "green" : "neutral"}
        />
        <StatCard
          label="Next Game"
          value={nextGameTime ? formatTimeUntil(nextGameTime) : "---"}
          sub={nextGameTime ? new Date(nextGameTime).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }) : undefined}
        />
      </div>

      {/* Active signals list */}
      <div className="mt-8">
        <h2 className="text-lg font-semibold">Active Signals</h2>
        {signals.length === 0 ? (
          <div className="mt-6 rounded-2xl bg-[#1c1c1e] p-8 text-center text-gray-500">
            No active signals right now. Signals fire when the confluence model
            detects high-confidence plays.
          </div>
        ) : (
          <div className="mt-3 space-y-2">
            {signals.map((sig) => (
              <div
                key={sig.id}
                className="flex items-center justify-between rounded-2xl bg-[#1c1c1e] px-5 py-4 transition-colors hover:bg-[#222224]"
              >
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <Stars count={sig.star_rating} />
                    <span className="rounded bg-[#2c2c2e] px-2 py-0.5 text-xs text-gray-400">
                      {sportLabel(sig.sport)}
                    </span>
                  </div>
                  <p className="mt-1 truncate font-medium text-gray-200">
                    {sig.side}
                  </p>
                  <p className="text-xs text-gray-500">
                    {sig.market_type.replace(/_/g, " ")} &middot; {sig.sportsbook}
                  </p>
                </div>
                <div className="ml-4 text-right">
                  <p className={`text-lg font-bold ${strengthColor(sig.signal_strength)}`}>
                    {sig.signal_strength.toFixed(1)}
                  </p>
                  <p className="font-mono text-sm text-gray-400">
                    {formatOdds(sig.book_odds)}
                  </p>
                  <p className="text-xs text-emerald-400">
                    +{sig.edge_percentage.toFixed(1)}% EV
                  </p>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
