"use client";

import { useEffect, useState } from "react";
import { useBankroll } from "@/lib/bankroll-context";

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
  status: string;
  created_at: string;
  other_books?: { sportsbook: string; book_odds: number; ev_pct: number }[];
}

// ---------------------------------------------------------------------------
// Score explanation content
// ---------------------------------------------------------------------------

const SCORE_EXPLANATIONS: Record<string, string> = {
  EV: "Measures how much positive expected value this bet has compared to the true probability derived from Pinnacle's devigged line. Higher means more mathematical edge. Score of 80+ means strong value, 50-79 moderate, below 50 marginal.",
  Steam:
    "Detects sharp money movement by tracking line changes across books. Score of 100 means significant odds drops detected (sharp bettors hammering this line). Score of 0 means no notable movement. Based on RTM's real-time line movement tracking.",
  Proj: "How strongly KenPom's independent game projection agrees with this bet. For h2h bets, measures if KenPom's win probability supports the bet side. For spreads, measures if KenPom's predicted margin covers the spread. For totals, measures if KenPom's predicted total agrees with over/under. Score of 0 means KenPom disagrees or is neutral.",
  Cons: "Measures how many other sportsbooks also show this as a +EV opportunity. High consensus (80+) means many books are mispriced on this line, suggesting the market broadly disagrees with Pinnacle. Low consensus means only 1-2 books have value, which could indicate stale odds.",
  Intel:
    "Combines intelligence signals: book reaction speed profiling (how fast each book moves after Pinnacle), stale line detection, and market timing patterns. Higher scores indicate the book is known to be slow to react, making the edge more likely to be real.",
};

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

function strengthColor(strength: number): string {
  if (strength >= 70) return "text-emerald-400";
  if (strength >= 55) return "text-amber-400";
  return "text-gray-300";
}

function scoreBarBg(score: number): string {
  if (score >= 61) return "bg-emerald-500";
  if (score >= 31) return "bg-amber-500";
  return "bg-gray-600";
}

function scoreTextColor(score: number): string {
  if (score >= 61) return "text-emerald-400";
  if (score >= 31) return "text-amber-400";
  return "text-gray-500";
}

function Stars({ count }: { count: number }) {
  return (
    <span className="text-amber-400">
      {"★".repeat(count)}
      <span className="text-gray-700">{"★".repeat(5 - count)}</span>
    </span>
  );
}

// ---------------------------------------------------------------------------
// KenPom data extraction
// ---------------------------------------------------------------------------

interface KenPomData {
  home_score: number;
  away_score: number;
  home_win_prob: number;
  home_team?: string;
  away_team?: string;
}

function extractKenPom(intelligenceContext: string | null): KenPomData | null {
  if (!intelligenceContext) return null;
  try {
    const ctx = JSON.parse(intelligenceContext);
    // Check various possible field structures
    const kp = ctx.kenpom ?? ctx.projection ?? ctx;
    if (
      typeof kp.home_score === "number" &&
      typeof kp.away_score === "number" &&
      typeof kp.home_win_prob === "number"
    ) {
      return {
        home_score: kp.home_score,
        away_score: kp.away_score,
        home_win_prob: kp.home_win_prob,
        home_team: kp.home_team ?? ctx.home_team,
        away_team: kp.away_team ?? ctx.away_team,
      };
    }
  } catch {
    // ignore parse errors
  }
  return null;
}

// ---------------------------------------------------------------------------
// Score bar with clickable explanation
// ---------------------------------------------------------------------------

function ScoreBarWithExplanation({
  label,
  score,
  expandedScore,
  onToggle,
}: {
  label: string;
  score: number;
  expandedScore: string | null;
  onToggle: (label: string) => void;
}) {
  const isOpen = expandedScore === label;

  return (
    <div>
      <button
        onClick={() => onToggle(label)}
        className="flex w-full items-center gap-2 rounded-lg px-1 py-1 text-left transition-colors hover:bg-[#2c2c2e]/50"
      >
        <span className="w-10 text-xs font-medium text-gray-400">{label}</span>
        <div className="h-2 flex-1 rounded-full bg-[#2c2c2e]">
          <div
            className={`h-full rounded-full transition-all ${scoreBarBg(score)}`}
            style={{ width: `${Math.min(score, 100)}%` }}
          />
        </div>
        <span className={`w-8 text-right font-mono text-xs font-semibold ${scoreTextColor(score)}`}>
          {score}
        </span>
        <span className="text-[10px] text-gray-600">{isOpen ? "▲" : "?"}</span>
      </button>
      {isOpen && SCORE_EXPLANATIONS[label] && (
        <div className="mt-1 mb-1 ml-12 rounded-lg border border-gray-800/50 bg-[#1a1a1c] px-3 py-2 text-xs leading-relaxed text-gray-400">
          {SCORE_EXPLANATIONS[label]}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Signal Card
// ---------------------------------------------------------------------------

function SignalCard({
  sig,
  expandedScore,
  onToggleScore,
  unitSize,
  kellyBetSize,
}: {
  sig: Signal;
  expandedScore: string | null;
  onToggleScore: (label: string) => void;
  unitSize: number | null;
  kellyBetSize: (fraction: number) => number | null;
}) {
  const kenpom = extractKenPom(sig.intelligence_context);
  const pinOdds =
    sig.true_prob != null && sig.true_prob > 0
      ? trueProbToAmericanOdds(sig.true_prob)
      : null;

  const scores = [
    { label: "EV", score: sig.ev_score ?? 0 },
    { label: "Steam", score: sig.steam_score ?? 0 },
    { label: "Proj", score: sig.projection_score ?? 0 },
    { label: "Cons", score: sig.consensus_score ?? 0 },
    { label: "Intel", score: sig.intelligence_score ?? 0 },
  ];

  const kellyBet =
    sig.kelly_fraction != null ? kellyBetSize(sig.kelly_fraction) : null;

  return (
    <div className="rounded-2xl bg-[#1c1c1e] p-5 transition-colors hover:bg-[#1e1e20]">
      {/* Header row */}
      <div className="flex items-start justify-between">
        <div>
          <div className="flex items-center gap-2">
            <Stars count={sig.star_rating} />
            <span className="rounded bg-[#2c2c2e] px-2 py-0.5 text-xs text-gray-400">
              {sportLabel(sig.sport)}
            </span>
          </div>
        </div>
        <div className="text-right">
          <p
            className={`text-lg font-bold ${strengthColor(sig.signal_strength ?? 0)}`}
          >
            {(sig.signal_strength ?? 0).toFixed(1)}
          </p>
          <p className="text-xs text-emerald-400">
            +{(sig.edge_percentage ?? 0).toFixed(1)}% EV
          </p>
        </div>
      </div>

      {/* Side / selection */}
      <p className="mt-3 text-base font-semibold text-gray-100">{sig.side}</p>
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
          {pinOdds != null && (
            <span className="font-mono text-xs text-blue-400/70">
              PIN {formatOdds(pinOdds)}
            </span>
          )}
        </div>
      </div>

      {/* Bet sizing */}
      <div className="mt-2 flex items-center gap-3 text-xs text-gray-500">
        {unitSize != null ? (
          <>
            <span>
              1u (${unitSize.toFixed(2)})
            </span>
            {kellyBet != null && sig.kelly_fraction != null && (
              <span className="text-emerald-400/70">
                Kelly: {(sig.kelly_fraction * 100).toFixed(1)}% ($
                {kellyBet.toFixed(2)})
              </span>
            )}
          </>
        ) : (
          <span>${(sig.bet_amount ?? 100).toFixed(0)} flat bet</span>
        )}
      </div>

      {/* KenPom projection (Sub-feature 3A) */}
      {kenpom != null && (sig.projection_score ?? 0) > 0 && (
        <div className="mt-3 rounded-lg bg-[#2c2c2e]/50 px-3 py-2">
          <p className="text-[10px] font-medium uppercase tracking-wider text-gray-500">
            KenPom Projection
          </p>
          <p className="mt-0.5 font-mono text-sm text-gray-300">
            {kenpom.away_team ?? "Away"} {kenpom.away_score.toFixed(1)} -{" "}
            {kenpom.home_team ?? "Home"} {kenpom.home_score.toFixed(1)}
          </p>
          <p className="text-[11px] text-gray-500">
            Home WP: {(kenpom.home_win_prob * 100).toFixed(1)}%
          </p>
        </div>
      )}

      {/* Component scores (Sub-features 3B + 3C) */}
      <div className="mt-3 space-y-0.5">
        {scores.map((s) => (
          <ScoreBarWithExplanation
            key={s.label}
            label={s.label}
            score={s.score}
            expandedScore={expandedScore}
            onToggle={onToggleScore}
          />
        ))}
      </div>

      {/* Other books */}
      {sig.other_books && sig.other_books.length > 0 && (
        <div className="mt-3 border-t border-gray-800/50 pt-2">
          <p className="text-[10px] font-medium uppercase tracking-wider text-gray-600">
            Also available at
          </p>
          <div className="mt-1 flex flex-wrap gap-2">
            {sig.other_books.map((ob) => (
              <span
                key={ob.sportsbook}
                className="rounded bg-[#2c2c2e] px-2 py-0.5 text-xs text-gray-400"
              >
                {ob.sportsbook}{" "}
                <span className="font-mono">{formatOdds(ob.book_odds)}</span>
                <span className="ml-1 text-emerald-400/60">
                  +{ob.ev_pct.toFixed(1)}%
                </span>
              </span>
            ))}
          </div>
        </div>
      )}
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
  // Only one score explanation can be open at a time — tracked as "cardId:scoreLabel"
  const [expandedScore, setExpandedScore] = useState<string | null>(null);

  const { unitSize, kellyBetSize } = useBankroll();

  useEffect(() => {
    setLoading(true);
    setError(null);
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

  function handleToggleScore(sigId: number, label: string) {
    const key = `${sigId}:${label}`;
    setExpandedScore((prev) => (prev === key ? null : key));
  }

  return (
    <div>
      <h1 className="text-2xl font-bold">Picks</h1>
      <p className="mt-1 text-sm text-gray-500">
        Active signals with performance tracking and edge analysis.
        {unitSize != null && (
          <span className="ml-2 text-gray-600">
            1u = ${unitSize.toFixed(2)}
          </span>
        )}
      </p>

      {loading ? (
        <div className="mt-12 text-center text-gray-500">Loading...</div>
      ) : error ? (
        <div className="mt-12 text-center text-red-400">
          Failed to load: {error}
        </div>
      ) : signals.length === 0 ? (
        <div className="mt-12 text-center text-gray-500">
          No active picks right now.
        </div>
      ) : (
        <div className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {signals.map((sig) => (
            <SignalCard
              key={sig.id}
              sig={sig}
              expandedScore={
                expandedScore?.startsWith(`${sig.id}:`)
                  ? expandedScore.split(":")[1]
                  : null
              }
              onToggleScore={(label) => handleToggleScore(sig.id, label)}
              unitSize={unitSize}
              kellyBetSize={kellyBetSize}
            />
          ))}
        </div>
      )}
    </div>
  );
}
