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
  prop_line: number | null;
  sportsbook: string;
  book_odds: number;
  signal_strength: number;
  star_rating: number;
  ev_score: number;
  steam_score: number;
  projection_score: number | null;
  consensus_score: number;
  true_prob: number | null;
  edge_percentage: number;
  kelly_size: number | null;
  status: string;
  created_at: string;
  other_books?: { sportsbook: string; book_odds: number; ev_pct: number }[];
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

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

/** Convert a true probability (0–1) to American odds. */
function trueProbToAmericanOdds(prob: number): number {
  if (prob <= 0 || prob >= 1) return -110; // fallback
  if (prob > 0.5) return Math.round((-100 * prob) / (1 - prob));
  return Math.round((100 * (1 - prob)) / prob);
}

function Stars({ count }: { count: number }) {
  return (
    <span className="text-amber-400">
      {"★".repeat(count)}
      <span className="text-gray-700">{"★".repeat(5 - count)}</span>
    </span>
  );
}

function tierLabel(strength: number): { text: string; color: string } {
  if (strength >= 70) return { text: "STRONG", color: "bg-emerald-500/20 text-emerald-400" };
  if (strength >= 55) return { text: "SIGNAL", color: "bg-amber-500/20 text-amber-400" };
  return { text: "LEAN", color: "bg-gray-500/20 text-gray-400" };
}

function ScoreBar({ label, value }: { label: string; value: number }) {
  const pct = Math.min(value, 100);
  return (
    <div className="flex items-center gap-2">
      <span className="w-12 text-right text-xs text-gray-500">{label}</span>
      <div className="h-1.5 flex-1 rounded-full bg-[#2c2c2e]">
        <div
          className="h-1.5 rounded-full bg-emerald-500"
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="w-6 text-right text-xs font-mono text-gray-400">
        {value}
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function PicksPage() {
  const [signals, setSignals] = useState<Signal[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch(`${API_BASE}/api/signals/active`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((data) => {
        setSignals(data.signals ?? []);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div>
      <h1 className="text-2xl font-bold">Picks</h1>
      <p className="mt-1 text-sm text-gray-500">
        Active RTM Signals — $100 flat bet on every qualifying play.
      </p>

      {/* Count */}
      <div className="mt-4 flex items-center gap-3">
        <span className="text-xs text-gray-500">
          {signals.length} active signal{signals.length !== 1 ? "s" : ""}
        </span>
        {!loading && !error && signals.length > 0 && (
          <span className="inline-flex items-center gap-1 text-xs text-emerald-400">
            <span className="inline-block h-1.5 w-1.5 rounded-full bg-emerald-400" />
            Live
          </span>
        )}
      </div>

      {loading ? (
        <div className="mt-12 text-center text-gray-500">Loading...</div>
      ) : error ? (
        <div className="mt-12 text-center text-red-400">
          Failed to load: {error}
        </div>
      ) : signals.length === 0 ? (
        <div className="mt-8 rounded-2xl bg-[#1c1c1e] p-8 text-center text-gray-500">
          No active signals right now. Signals fire when the confluence model
          detects high-confidence plays.
        </div>
      ) : (
        <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {signals.map((sig) => {
            const strength = sig.signal_strength ?? 0;
            const tier = tierLabel(strength);
            const betAmount = 100;
            return (
              <div
                key={sig.id}
                className="flex flex-col rounded-2xl bg-[#1c1c1e] p-5 transition-colors hover:bg-[#222224]"
              >
                {/* Header: stars + tier + sport */}
                <div className="flex items-center justify-between">
                  <Stars count={sig.star_rating ?? 0} />
                  <div className="flex items-center gap-2">
                    <span
                      className={`rounded px-2 py-0.5 text-xs font-semibold ${tier.color}`}
                    >
                      {tier.text}
                    </span>
                    <span className="rounded bg-[#2c2c2e] px-2 py-0.5 text-xs text-gray-400">
                      {sportLabel(sig.sport)}
                    </span>
                  </div>
                </div>

                {/* Side / selection */}
                <p className="mt-3 text-base font-semibold text-gray-100">
                  {sig.side}
                </p>
                <p className="mt-0.5 text-xs text-gray-500">
                  {sig.market_type.replace(/_/g, " ")}
                </p>

                {/* Book + odds row */}
                <div className="mt-3 flex items-center justify-between">
                  <span className="text-sm text-gray-400">{sig.sportsbook}</span>
                  <div className="flex items-baseline gap-2">
                    <span className="font-mono text-lg font-bold text-gray-200">
                      {formatOdds(sig.book_odds ?? -110)}
                    </span>
                    {sig.true_prob != null && sig.true_prob > 0 && (
                      <span className="font-mono text-xs text-blue-400/70">
                        PIN {formatOdds(trueProbToAmericanOdds(sig.true_prob))}
                      </span>
                    )}
                  </div>
                </div>

                {/* Strength + bet info */}
                <div className="mt-3 flex items-center justify-between rounded-xl bg-[#2c2c2e] px-4 py-3">
                  <div>
                    <p className="text-xs text-gray-500">Strength</p>
                    <p className="text-xl font-bold text-white">
                      {strength.toFixed(1)}
                    </p>
                  </div>
                  <div className="text-right">
                    <p className="text-xs text-gray-500">Bet</p>
                    <p className="text-lg font-bold text-emerald-400">
                      ${betAmount}
                    </p>
                  </div>
                  {sig.kelly_size != null && (
                    <div className="text-right">
                      <p className="text-xs text-gray-500">Kelly</p>
                      <p className="font-mono text-sm font-medium text-gray-300">
                        {(sig.kelly_size * 100).toFixed(1)}%
                      </p>
                    </div>
                  )}
                </div>

                {/* Component scores */}
                <div className="mt-3 space-y-1.5">
                  <ScoreBar label="EV" value={sig.ev_score ?? 0} />
                  <ScoreBar label="Steam" value={sig.steam_score ?? 0} />
                  {sig.projection_score != null && sig.projection_score > 0 && (
                    <ScoreBar label="Proj" value={sig.projection_score} />
                  )}
                  <ScoreBar label="Cons" value={sig.consensus_score ?? 0} />
                </div>

                {/* Edge */}
                <div className="mt-3 flex items-center justify-between border-t border-gray-800/50 pt-3">
                  <span className="text-xs text-gray-500">Edge</span>
                  <span className="font-mono text-sm font-medium text-emerald-400">
                    +{(sig.edge_percentage ?? 0).toFixed(1)}%
                  </span>
                </div>

                {/* Other books (filter out betopenly/novig) */}
                {(() => {
                  const HIDDEN_BOOKS = new Set(["betopenly", "novig"]);
                  const visible = (sig.other_books ?? []).filter(
                    (alt) => !HIDDEN_BOOKS.has(alt.sportsbook?.toLowerCase() ?? ""),
                  );
                  if (visible.length === 0) return null;
                  return (
                    <div className="mt-2 flex flex-wrap gap-1">
                      {visible.map((alt, i) => (
                        <span
                          key={i}
                          className="rounded bg-[#2c2c2e] px-2 py-0.5 text-xs text-gray-500"
                        >
                          {alt.sportsbook} {formatOdds(alt.book_odds)}
                        </span>
                      ))}
                    </div>
                  );
                })()}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
