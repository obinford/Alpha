"use client";

import { useEffect, useState } from "react";
import { useBankroll, KellyMultiplier } from "@/lib/bankroll-context";

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
  intelligence_score: number | null;
  intelligence_context: string | null;
  true_prob: number | null;
  fair_odds: number | null;
  edge_percentage: number;
  kelly_fraction: number | null;
  kelly_size: number | null;
  bet_amount: number | null;
  created_at: string;
  other_books?: { sportsbook: string; book_odds: number; ev_pct: number }[];
}

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

function trueProbToAmericanOdds(prob: number): number {
  if (prob <= 0 || prob >= 1) return -110;
  if (prob > 0.5) return Math.round((-100 * prob) / (1 - prob));
  return Math.round((100 * (1 - prob)) / prob);
}

function pct(value: number): string {
  return `${value.toFixed(1)}%`;
}

function strengthColor(strength: number): string {
  if (strength >= 70) return "text-emerald-400";
  if (strength >= 55) return "text-amber-400";
  return "text-gray-300";
}

function scoreBarColor(score: number): string {
  if (score >= 61) return "bg-emerald-500";
  if (score >= 31) return "bg-amber-500";
  return "bg-gray-600";
}

function formatTimeUntil(isoString: string): string {
  const diff = new Date(isoString).getTime() - Date.now();
  if (diff < 0) return "Live";
  const hours = Math.floor(diff / 3600000);
  const minutes = Math.floor((diff % 3600000) / 60000);
  if (hours > 0) return `${hours}h ${minutes}m`;
  return `${minutes}m`;
}

function Stars({ count }: { count: number }) {
  return (
    <span className="text-amber-400">
      {"★".repeat(count)}
      <span className="text-gray-700">{"★".repeat(5 - count)}</span>
    </span>
  );
}

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

// ---------------------------------------------------------------------------
// Score bar component
// ---------------------------------------------------------------------------

function ScoreBar({ label, score }: { label: string; score: number }) {
  return (
    <div className="flex items-center gap-2">
      <span className="w-10 text-[10px] text-gray-500">{label}</span>
      <div className="h-1.5 flex-1 rounded-full bg-[#2c2c2e]">
        <div
          className={`h-full rounded-full ${scoreBarColor(score)}`}
          style={{ width: `${Math.min(score, 100)}%` }}
        />
      </div>
      <span className="w-6 text-right text-[10px] font-mono text-gray-500">
        {score}
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Bankroll settings panel
// ---------------------------------------------------------------------------

const KELLY_OPTIONS: { value: KellyMultiplier; label: string }[] = [
  { value: 1.0, label: "Full Kelly (1.0x)" },
  { value: 0.5, label: "Half Kelly (0.5x)" },
  { value: 0.25, label: "Quarter Kelly (0.25x)" },
  { value: 0.125, label: "Eighth Kelly (0.125x)" },
];

function BankrollPanel() {
  const { bankroll, kellyMultiplier, unitSize, setBankroll, setKellyMultiplier } =
    useBankroll();
  const [open, setOpen] = useState(false);
  const [inputValue, setInputValue] = useState(bankroll != null ? String(bankroll) : "");

  function handleSave() {
    const parsed = parseFloat(inputValue.replace(/[,$]/g, ""));
    if (!isNaN(parsed) && parsed > 0) {
      setBankroll(parsed);
    }
    setOpen(false);
  }

  return (
    <div className="mb-6">
      {/* Toggle button */}
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-2 rounded-lg px-3 py-1.5 text-xs text-gray-400 transition-colors hover:bg-[#1c1c1e] hover:text-gray-200"
      >
        <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
        </svg>
        {bankroll != null ? (
          <span>
            Bankroll: <span className="text-emerald-400">${bankroll.toLocaleString()}</span>
            {" | "}
            <span className="text-gray-300">{KELLY_OPTIONS.find((o) => o.value === kellyMultiplier)?.label ?? "Quarter Kelly"}</span>
            {unitSize != null && (
              <span className="text-gray-500"> | 1u = ${unitSize.toFixed(2)}</span>
            )}
          </span>
        ) : (
          <span>Set your bankroll to see personalized bet sizing</span>
        )}
      </button>

      {/* Collapsible panel */}
      {open && (
        <div className="mt-2 rounded-2xl bg-[#1c1c1e] p-5">
          <h3 className="text-sm font-semibold text-gray-200">Bankroll Settings</h3>
          <div className="mt-3 grid gap-4 sm:grid-cols-3">
            {/* Bankroll input */}
            <div>
              <label className="text-xs text-gray-500">Your Bankroll ($)</label>
              <input
                type="text"
                value={inputValue}
                onChange={(e) => setInputValue(e.target.value)}
                placeholder="1000"
                className="mt-1 w-full rounded-lg bg-[#2c2c2e] px-3 py-2 text-sm text-white placeholder-gray-600 outline-none focus:ring-1 focus:ring-emerald-500"
              />
            </div>
            {/* Kelly selector */}
            <div>
              <label className="text-xs text-gray-500">Kelly Fraction</label>
              <select
                value={kellyMultiplier}
                onChange={(e) => setKellyMultiplier(parseFloat(e.target.value) as KellyMultiplier)}
                className="mt-1 w-full rounded-lg bg-[#2c2c2e] px-3 py-2 text-sm text-white outline-none focus:ring-1 focus:ring-emerald-500"
              >
                {KELLY_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </div>
            {/* Unit size display + save */}
            <div className="flex items-end gap-3">
              <div className="flex-1">
                <label className="text-xs text-gray-500">Unit Size (1%)</label>
                <div className="mt-1 rounded-lg bg-[#2c2c2e] px-3 py-2 text-sm text-gray-300">
                  {unitSize != null ? `$${unitSize.toFixed(2)}` : "—"}
                </div>
              </div>
              <button
                onClick={handleSave}
                className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-emerald-500"
              >
                Save
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Expanded signal detail panel
// ---------------------------------------------------------------------------

function SignalDetail({
  sig,
  opportunities,
  oppsLoading,
}: {
  sig: Signal;
  opportunities: Opportunity[];
  oppsLoading: boolean;
}) {
  // Filter opportunities matching this signal's game+market+side
  const matchingOpps = opportunities.filter(
    (o) =>
      o.game_id === sig.game_id &&
      o.market_type === sig.market_type &&
      o.side === sig.side,
  );
  matchingOpps.sort((a, b) => (b.ev_percentage ?? 0) - (a.ev_percentage ?? 0));

  // Try to find game info from opportunities
  const game = matchingOpps[0]?.games ?? null;

  // Parse intelligence_context if available
  let intelContext: Record<string, unknown> | null = null;
  if (sig.intelligence_context) {
    try {
      intelContext = JSON.parse(sig.intelligence_context);
    } catch {
      // ignore
    }
  }

  const trueProb =
    sig.true_prob ?? (matchingOpps.length > 0 ? matchingOpps[0].true_prob : null);
  const pinOdds = trueProb != null && trueProb > 0 ? trueProbToAmericanOdds(trueProb) : null;

  const scores = [
    { label: "EV", score: sig.ev_score ?? 0 },
    { label: "Steam", score: sig.steam_score ?? 0 },
    { label: "Proj", score: sig.projection_score ?? 0 },
    { label: "Cons", score: sig.consensus_score ?? 0 },
    { label: "Intel", score: sig.intelligence_score ?? 0 },
  ];

  return (
    <div className="overflow-hidden transition-all duration-300">
      <div className="rounded-b-2xl bg-[#161618] px-5 pb-5 pt-2">
        {/* Signal summary header */}
        <div className="mb-4 grid gap-3 sm:grid-cols-2">
          <div>
            {game && (
              <p className="text-sm font-medium text-gray-200">
                {game.away_team} @ {game.home_team}
              </p>
            )}
            <p className="text-xs text-gray-500">
              {sig.market_type.replace(/_/g, " ")} &middot; {sportLabel(sig.sport)}
            </p>
            <p className="mt-1 text-sm text-gray-300">
              {sig.side}{" "}
              <span className="font-mono font-semibold text-gray-200">
                {formatOdds(sig.book_odds ?? -110)}
              </span>
              <span className="text-gray-500"> at {sig.sportsbook}</span>
            </p>
            {pinOdds != null && (
              <p className="mt-0.5 text-xs text-blue-400/70">
                PIN {formatOdds(pinOdds)}
              </p>
            )}
          </div>
          <div className="grid grid-cols-3 gap-2 text-center">
            <div>
              <p className="text-[10px] uppercase text-gray-500">Edge</p>
              <p className="font-mono text-sm font-bold text-emerald-400">
                +{(sig.edge_percentage ?? 0).toFixed(1)}%
              </p>
            </div>
            <div>
              <p className="text-[10px] uppercase text-gray-500">Strength</p>
              <p className={`font-mono text-sm font-bold ${strengthColor(sig.signal_strength ?? 0)}`}>
                {(sig.signal_strength ?? 0).toFixed(1)}
              </p>
            </div>
            <div>
              <p className="text-[10px] uppercase text-gray-500">Kelly</p>
              <p className="font-mono text-sm text-gray-300">
                {sig.kelly_fraction != null ? pct(sig.kelly_fraction * 100) : "—"}
              </p>
            </div>
          </div>
        </div>

        {/* Component scores */}
        <div className="mb-4 space-y-1.5">
          {scores.map((s) => (
            <ScoreBar key={s.label} label={s.label} score={s.score} />
          ))}
        </div>

        {/* Odds comparison table */}
        <div className="overflow-x-auto rounded-xl bg-[#1c1c1e]">
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="border-b border-gray-800 text-[10px] font-medium uppercase tracking-wider text-gray-500">
                <th className="px-3 py-2">Book</th>
                <th className="px-3 py-2 text-right">Odds</th>
                <th className="px-3 py-2 text-right">True%</th>
                <th className="px-3 py-2 text-right">Book%</th>
                <th className="px-3 py-2 text-right">EV%</th>
                <th className="px-3 py-2 text-right">Kelly%</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800/50">
              {/* Pinnacle reference row */}
              {trueProb != null && trueProb > 0 && (
                <tr className="border-l-2 border-l-blue-500 bg-[#18181b]">
                  <td className="whitespace-nowrap px-3 py-2 text-blue-400">
                    <span className="font-medium">Pinnacle</span>
                    <span className="ml-1.5 rounded bg-blue-500/20 px-1 py-0.5 text-[9px] font-bold uppercase tracking-wider text-blue-400">
                      Sharp
                    </span>
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 text-right font-mono text-blue-300">
                    {formatOdds(trueProbToAmericanOdds(trueProb))}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 text-right font-mono text-blue-300/70">
                    {pct(trueProb * 100)}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 text-right font-mono text-blue-300/70">
                    {pct(trueProb * 100)}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 text-right font-mono text-gray-600">
                    0.0%
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 text-right font-mono text-gray-600">
                    0.0%
                  </td>
                </tr>
              )}

              {/* Matching opportunities from other books */}
              {oppsLoading ? (
                <tr>
                  <td colSpan={6} className="px-3 py-3 text-center text-gray-600">
                    Loading books...
                  </td>
                </tr>
              ) : matchingOpps.length > 0 ? (
                matchingOpps.map((opp, i) => (
                  <tr key={opp.id} className={i % 2 === 0 ? "bg-[#1e1e20]" : ""}>
                    <td className="whitespace-nowrap px-3 py-2 text-gray-400">
                      {opp.sportsbook}
                    </td>
                    <td className="whitespace-nowrap px-3 py-2 text-right font-mono text-gray-300">
                      {formatOdds(opp.book_odds)}
                    </td>
                    <td className="whitespace-nowrap px-3 py-2 text-right font-mono text-gray-500">
                      {pct((opp.true_prob ?? 0) * 100)}
                    </td>
                    <td className="whitespace-nowrap px-3 py-2 text-right font-mono text-gray-500">
                      {pct((opp.book_implied_prob ?? 0) * 100)}
                    </td>
                    <td className="whitespace-nowrap px-3 py-2 text-right font-mono text-emerald-400/80">
                      +{pct(opp.ev_percentage ?? 0)}
                    </td>
                    <td className="whitespace-nowrap px-3 py-2 text-right font-mono text-gray-500">
                      {pct((opp.kelly_fraction ?? 0) * 100)}
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={6} className="px-3 py-3 text-center text-gray-600">
                    No book comparison data available
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function DashboardPage() {
  const [signals, setSignals] = useState<Signal[]>([]);
  const [opportunities, setOpportunities] = useState<Opportunity[]>([]);
  const [oppCount, setOppCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [oppsLoading, setOppsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const { bankroll } = useBankroll();

  useEffect(() => {
    setLoading(true);
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
        setOpportunities(oppData.opportunities ?? []);
        setOppCount(oppData.count ?? 0);
        setOppsLoading(false);
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

      {/* Bankroll settings */}
      <div className="mt-4">
        <BankrollPanel />
      </div>

      {/* Stat cards */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
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
              ? `${(topSignal.signal_strength ?? 0).toFixed(1)}`
              : "---"
          }
          sub={
            topSignal
              ? `${topSignal.star_rating ?? 0}★ ${sportLabel(topSignal.sport ?? "")}`
              : undefined
          }
          accent={
            topSignal && (topSignal.star_rating ?? 0) >= 4 ? "green" : "neutral"
          }
        />
        <StatCard
          label="Next Game"
          value={nextGameTime ? formatTimeUntil(nextGameTime) : "---"}
          sub={
            nextGameTime
              ? new Date(nextGameTime).toLocaleTimeString([], {
                  hour: "numeric",
                  minute: "2-digit",
                })
              : undefined
          }
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
            {signals.map((sig) => {
              const isExpanded = expandedId === sig.id;
              const trueProb =
                sig.true_prob ??
                opportunities.find(
                  (o) =>
                    o.game_id === sig.game_id &&
                    o.market_type === sig.market_type &&
                    o.side === sig.side,
                )?.true_prob ??
                null;
              const pinOdds =
                trueProb != null && trueProb > 0
                  ? trueProbToAmericanOdds(trueProb)
                  : null;

              return (
                <div key={sig.id}>
                  <div
                    className={`flex cursor-pointer items-center justify-between rounded-2xl px-5 py-4 transition-colors ${
                      isExpanded
                        ? "rounded-b-none bg-[#222224]"
                        : "bg-[#1c1c1e] hover:bg-[#222224]"
                    }`}
                    onClick={() =>
                      setExpandedId(isExpanded ? null : sig.id)
                    }
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
                        {sig.market_type.replace(/_/g, " ")} &middot;{" "}
                        {sig.sportsbook}
                      </p>
                    </div>
                    <div className="ml-4 text-right">
                      <p
                        className={`text-lg font-bold ${strengthColor(sig.signal_strength ?? 0)}`}
                      >
                        {(sig.signal_strength ?? 0).toFixed(1)}
                      </p>
                      <div className="flex items-baseline justify-end gap-1.5">
                        <span className="font-mono text-sm text-gray-400">
                          {formatOdds(sig.book_odds ?? -110)}
                        </span>
                        {pinOdds != null && (
                          <span className="font-mono text-[11px] text-blue-400/70">
                            PIN {formatOdds(pinOdds)}
                          </span>
                        )}
                      </div>
                      <p className="text-xs text-emerald-400">
                        +{(sig.edge_percentage ?? 0).toFixed(1)}% EV
                      </p>
                    </div>
                  </div>

                  {/* Expanded detail panel */}
                  {isExpanded && (
                    <SignalDetail
                      sig={sig}
                      opportunities={opportunities}
                      oppsLoading={oppsLoading}
                    />
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
