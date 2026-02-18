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
// Score explanation content
// ---------------------------------------------------------------------------

const SCORE_EXPLANATIONS: Record<string, string> = {
  EV: "Measures how much positive expected value this bet has compared to the true probability derived from Pinnacle's devigged line. Higher means more mathematical edge. Score of 80+ means strong value, 50\u201179 moderate, below 50 marginal.",
  Steam:
    "Detects sharp money movement by tracking line changes across books. Score of 100 means significant odds drops detected (sharp bettors hammering this line). Score of 0 means no notable movement. Based on RTM's real-time line movement tracking.",
  Proj: "How strongly KenPom's independent game projection agrees with this bet. For h2h bets, measures if KenPom's win probability supports the bet side. For spreads, measures if KenPom's predicted margin covers the spread. For totals, measures if KenPom's predicted total agrees with over/under. Score of 0 means KenPom disagrees or is neutral.",
  Cons: "Measures how many other sportsbooks also show this as a +EV opportunity. High consensus (80+) means many books are mispriced on this line, suggesting the market broadly disagrees with Pinnacle. Low consensus means only 1\u20112 books have value, which could indicate stale odds.",
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

/** Convert American odds to implied probability (0–1). */
function americanOddsToImpliedProb(odds: number): number {
  if (odds < 0) return -odds / (-odds + 100);
  if (odds > 0) return 100 / (odds + 100);
  return 0.5;
}

/** Pick first positive true_prob from a list of opportunities. */
function findTrueProb(opps: Opportunity[], gameId: string): number | null {
  for (const o of opps) {
    if (o.game_id === gameId && o.true_prob != null && o.true_prob > 0) {
      return o.true_prob;
    }
  }
  return null;
}

function pct(value: number): string {
  return `${value.toFixed(1)}%`;
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

/** Fix 5: Bet link button */
function BetLink({ book }: { book: string }) {
  const url = getSportsbookUrl(book);
  if (!url) return null;
  return (
    <a
      href={url}
      target="_blank"
      rel="noopener noreferrer"
      className="ml-2 inline-flex items-center rounded bg-emerald-600/20 px-1.5 py-0.5 text-[9px] font-semibold text-emerald-400 transition-colors hover:bg-emerald-600/40"
    >
      Bet &rarr;
    </a>
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
// KenPom edge analysis
// ---------------------------------------------------------------------------

function KenPomEdge({
  sig,
  kenpom,
}: {
  sig: Signal;
  kenpom: KenPomData;
}) {
  const margin = kenpom.home_score - kenpom.away_score;
  const kpTotal = kenpom.home_score + kenpom.away_score;

  const scoreText = `${kenpom.away_team ?? "Away"} ${kenpom.away_score.toFixed(1)} \u2013 ${kenpom.home_team ?? "Home"} ${kenpom.home_score.toFixed(1)}`;

  if (sig.market_type === "spreads") {
    const spreadLine = sig.prop_line ?? 0;
    const edge = Math.abs(spreadLine) - Math.abs(margin);
    const absEdge = Math.abs(edge).toFixed(1);

    return (
      <div className="mt-2 space-y-1 text-[11px] text-gray-400">
        <p>
          <span className="text-gray-500">KenPom:</span> {scoreText}
        </p>
        <p>
          <span className="text-gray-500">KenPom Margin:</span>{" "}
          {margin > 0
            ? `${kenpom.home_team ?? "Home"} by ${margin.toFixed(1)}`
            : margin < 0
              ? `${kenpom.away_team ?? "Away"} by ${Math.abs(margin).toFixed(1)}`
              : "Pick"}
        </p>
        <p>
          <span className="text-gray-500">Line:</span> {sig.side}{" "}
          {spreadLine > 0 ? "+" : ""}
          {spreadLine}
        </p>
        <p>
          <span className="text-gray-500">Edge:</span>{" "}
          <span className={edge > 0 ? "text-emerald-400" : "text-amber-400"}>
            {absEdge} points
          </span>
        </p>
      </div>
    );
  }

  if (sig.market_type === "totals") {
    const totalLine = sig.prop_line ?? 0;
    const diff = kpTotal - totalLine;
    const direction = diff > 0 ? "over" : "under";
    const absDiff = Math.abs(diff).toFixed(1);

    return (
      <div className="mt-2 space-y-1 text-[11px] text-gray-400">
        <p>
          <span className="text-gray-500">KenPom:</span> {scoreText}
        </p>
        <p>
          <span className="text-gray-500">KenPom Total:</span>{" "}
          {kpTotal.toFixed(1)}
        </p>
        <p>
          <span className="text-gray-500">Line:</span> {totalLine}
        </p>
        <p>
          <span className="text-gray-500">Edge:</span>{" "}
          <span className={Math.abs(diff) > 1 ? "text-emerald-400" : "text-amber-400"}>
            {absDiff} points {direction}
          </span>
        </p>
      </div>
    );
  }

  // h2h (moneyline)
  const pinImplied = sig.true_prob != null ? sig.true_prob * 100 : null;
  const kpWp = kenpom.home_win_prob * 100;
  const isHome =
    sig.side === kenpom.home_team ||
    sig.side.toLowerCase().includes("home");
  const kpSideWp = isHome ? kpWp : 100 - kpWp;
  const edge =
    pinImplied != null ? kpSideWp - (100 - pinImplied) : null;

  return (
    <div className="mt-2 space-y-1 text-[11px] text-gray-400">
      <p>
        <span className="text-gray-500">KenPom:</span> {scoreText}
      </p>
      <p>
        <span className="text-gray-500">KenPom WP:</span> {kpSideWp.toFixed(1)}%
      </p>
      {pinImplied != null && (
        <p>
          <span className="text-gray-500">PIN Implied:</span>{" "}
          {(100 - pinImplied).toFixed(1)}%
        </p>
      )}
      {edge != null && (
        <p>
          <span className="text-gray-500">Edge:</span>{" "}
          <span
            className={edge > 0 ? "text-emerald-400" : "text-amber-400"}
          >
            {edge > 0 ? "+" : ""}
            {edge.toFixed(1)}%
          </span>
        </p>
      )}
    </div>
  );
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
        onClick={(e) => {
          e.stopPropagation();
          onToggle(label);
        }}
        className="flex w-full items-center gap-2 rounded-lg px-1 py-1 text-left transition-colors hover:bg-[#2c2c2e]/50"
      >
        <span className="w-10 text-xs font-medium text-gray-400">{label}</span>
        <div className="h-2 flex-1 rounded-full bg-[#2c2c2e]">
          <div
            className={`h-full rounded-full transition-all ${scoreBarBg(score)}`}
            style={{ width: `${Math.min(score, 100)}%` }}
          />
        </div>
        <span
          className={`w-8 text-right font-mono text-xs font-semibold ${scoreTextColor(score)}`}
        >
          {score}
        </span>
        <span className="text-[10px] text-gray-600">{isOpen ? "\u25B2" : "?"}</span>
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
// Books comparison table — Fix 1: always show data, never empty
// ---------------------------------------------------------------------------

function BooksTable({
  sig,
  opportunities,
  oppsLoading,
}: {
  sig: Signal;
  opportunities: Opportunity[];
  oppsLoading: boolean;
}) {
  // Flexible matching — try exact, then fuzzy (relaxed side), then broadest (game_id only)
  let matchingOpps = opportunities.filter(
    (o) =>
      o.game_id === sig.game_id &&
      o.market_type === sig.market_type &&
      o.side === sig.side &&
      !BLOCKED_BOOKS.has(o.sportsbook),
  );

  if (matchingOpps.length === 0) {
    matchingOpps = opportunities.filter(
      (o) =>
        o.game_id === sig.game_id &&
        o.market_type === sig.market_type &&
        !BLOCKED_BOOKS.has(o.sportsbook),
    );
  }

  // Sort by EV% descending
  matchingOpps.sort((a, b) => (b.ev_percentage ?? 0) - (a.ev_percentage ?? 0));

  // Robust trueProb — explicitly require positive values at each step.
  // Using > 0 checks instead of ?? to avoid 0 values short-circuiting the chain.
  let trueProb: number | null = null;
  if (sig.true_prob != null && sig.true_prob > 0) {
    trueProb = sig.true_prob;
  }
  if (trueProb == null) {
    for (const opp of matchingOpps) {
      if (opp.true_prob != null && opp.true_prob > 0) {
        trueProb = opp.true_prob;
        break;
      }
    }
  }
  if (trueProb == null && sig.fair_odds != null) {
    const derived = americanOddsToImpliedProb(sig.fair_odds);
    if (derived > 0 && derived < 1) trueProb = derived;
  }
  if (trueProb == null) {
    trueProb = findTrueProb(opportunities, sig.game_id);
  }

  const hasOpps = matchingOpps.length > 0;

  // other_books fallback, excluding blocked
  const otherBooks = (sig.other_books ?? []).filter(
    (ob) => !BLOCKED_BOOKS.has(ob.sportsbook),
  );

  return (
    <div className="mt-3 overflow-x-auto rounded-xl bg-[#1a1a1c]">
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
          {/* Pinnacle reference row — always on top (trueProb guaranteed > 0 by resolution) */}
          {trueProb != null && (
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

          {oppsLoading ? (
            <tr>
              <td colSpan={6} className="px-3 py-3 text-center text-gray-600">
                Loading books...
              </td>
            </tr>
          ) : hasOpps ? (
            matchingOpps.map((opp, i) => (
              <tr key={opp.id} className={i % 2 === 0 ? "bg-[#1e1e20]" : ""}>
                <td className="whitespace-nowrap px-3 py-2 text-gray-400">
                  {opp.sportsbook}
                  <BetLink book={opp.sportsbook} />
                </td>
                <td className="whitespace-nowrap px-3 py-2 text-right font-mono text-gray-300">
                  {formatOdds(opp.book_odds)}
                </td>
                <td className="whitespace-nowrap px-3 py-2 text-right font-mono text-gray-500">
                  {pct((opp.true_prob ?? trueProb ?? 0) * 100)}
                </td>
                <td className="whitespace-nowrap px-3 py-2 text-right font-mono text-gray-500">
                  {pct(
                    (opp.book_implied_prob ?? americanOddsToImpliedProb(opp.book_odds)) * 100,
                  )}
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
            /* Fallback — always show signal's own data + other_books */
            <>
              <tr className="bg-[#1e1e20]">
                <td className="whitespace-nowrap px-3 py-2 text-gray-300">
                  {sig.sportsbook}
                  <BetLink book={sig.sportsbook} />
                </td>
                <td className="whitespace-nowrap px-3 py-2 text-right font-mono text-gray-300">
                  {formatOdds(sig.book_odds)}
                </td>
                <td className="whitespace-nowrap px-3 py-2 text-right font-mono text-gray-500">
                  {trueProb != null ? pct(trueProb * 100) : pct(americanOddsToImpliedProb(sig.book_odds) * 100)}
                </td>
                <td className="whitespace-nowrap px-3 py-2 text-right font-mono text-gray-500">
                  {pct(americanOddsToImpliedProb(sig.book_odds) * 100)}
                </td>
                <td className="whitespace-nowrap px-3 py-2 text-right font-mono text-emerald-400/80">
                  +{pct(sig.edge_percentage ?? 0)}
                </td>
                <td className="whitespace-nowrap px-3 py-2 text-right font-mono text-gray-500">
                  {sig.kelly_fraction != null
                    ? pct(sig.kelly_fraction * 100)
                    : "\u2014"}
                </td>
              </tr>
              {otherBooks.map((ob) => (
                <tr key={ob.sportsbook}>
                  <td className="whitespace-nowrap px-3 py-2 text-gray-400">
                    {ob.sportsbook}
                    <BetLink book={ob.sportsbook} />
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 text-right font-mono text-gray-400">
                    {formatOdds(ob.book_odds)}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 text-right font-mono text-gray-500">
                    {trueProb != null ? pct(trueProb * 100) : pct(americanOddsToImpliedProb(ob.book_odds) * 100)}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 text-right font-mono text-gray-500">
                    {pct(americanOddsToImpliedProb(ob.book_odds) * 100)}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 text-right font-mono text-emerald-400/60">
                    +{pct(ob.ev_pct ?? 0)}
                  </td>
                  <td className="px-3 py-2" />
                </tr>
              ))}
            </>
          )}
        </tbody>
      </table>
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
  expandedCardId,
  onToggleCard,
  unitSize,
  kellyBetSize,
  opportunities,
  oppsLoading,
  gameStartTime,
}: {
  sig: Signal;
  expandedScore: string | null;
  onToggleScore: (label: string) => void;
  expandedCardId: number | null;
  onToggleCard: (id: number) => void;
  unitSize: number | null;
  kellyBetSize: (fraction: number) => number | null;
  opportunities: Opportunity[];
  oppsLoading: boolean;
  gameStartTime: string | null;
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
    sig.kelly_fraction != null && sig.kelly_fraction > 0
      ? kellyBetSize(sig.kelly_fraction)
      : null;
  const isCardExpanded = expandedCardId === sig.id;

  const otherBookCount =
    (sig.other_books?.filter((ob) => !BLOCKED_BOOKS.has(ob.sportsbook))
      .length ?? 0) > 0
      ? sig.other_books!.filter((ob) => !BLOCKED_BOOKS.has(ob.sportsbook))
          .length
      : 0;

  return (
    <div className="rounded-2xl bg-[#1c1c1e] transition-colors hover:bg-[#1e1e20]">
      <div className="p-5">
        {/* Header row */}
        <div className="flex items-start justify-between">
          <div>
            <div className="flex items-center gap-2">
              <Stars count={sig.star_rating} />
              <span className="rounded bg-[#2c2c2e] px-2 py-0.5 text-xs text-gray-400">
                {sportLabel(sig.sport)}
              </span>
              {/* Fix 6: Time badge */}
              {gameStartTime && <TimeBadge startTime={gameStartTime} />}
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
        <p className="mt-3 text-base font-semibold text-gray-100">
          {sig.side}
        </p>
        <p className="mt-0.5 text-xs text-gray-500">
          {sig.market_type.replace(/_/g, " ")}
        </p>

        {/* Book + odds row */}
        <div className="mt-3 flex items-center justify-between">
          <span className="text-sm text-gray-400">
            {sig.sportsbook}
            <BetLink book={sig.sportsbook} />
          </span>
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
              <span>1u (${unitSize.toFixed(2)})</span>
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

        {/* KenPom projection */}
        {kenpom != null && (sig.projection_score ?? 0) > 0 && (
          <div className="mt-3 rounded-lg bg-[#2c2c2e]/50 px-3 py-2">
            <p className="text-[10px] font-medium uppercase tracking-wider text-gray-500">
              KenPom Projection
            </p>
            <KenPomEdge sig={sig} kenpom={kenpom} />
          </div>
        )}

        {/* Component scores */}
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

        {/* View all books button */}
        <button
          onClick={() => onToggleCard(sig.id)}
          className="mt-3 w-full rounded-lg bg-[#2c2c2e]/50 py-1.5 text-center text-xs text-gray-400 transition-colors hover:bg-[#2c2c2e] hover:text-gray-200"
        >
          {isCardExpanded
            ? "Hide book comparison"
            : `View all books${otherBookCount > 0 ? ` (${otherBookCount + 1})` : ""}`}
        </button>
      </div>

      {/* Expanded books table */}
      {isCardExpanded && (
        <div className="border-t border-gray-800/50 px-5 pb-5">
          <BooksTable
            sig={sig}
            opportunities={opportunities}
            oppsLoading={oppsLoading}
          />
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
  const [opportunities, setOpportunities] = useState<Opportunity[]>([]);
  const [loading, setLoading] = useState(true);
  const [oppsLoading, setOppsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedScore, setExpandedScore] = useState<string | null>(null);
  const [expandedCardId, setExpandedCardId] = useState<number | null>(null);

  const { unitSize, kellyBetSize } = useBankroll();

  useEffect(() => {
    setLoading(true);
    setError(null);
    Promise.all([
      fetch(`${API_BASE}/api/signals/active`).then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
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
        setOppsLoading(false);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  // Fix 6: Determine live game IDs to filter out
  const liveGameIds = useMemo(() => {
    const ids = new Set<string>();
    for (const opp of opportunities) {
      if (opp.games?.start_time) {
        const start = new Date(opp.games.start_time).getTime();
        if (start <= Date.now()) ids.add(opp.game_id);
      }
    }
    return ids;
  }, [opportunities]);

  // Fix 2 + Fix 3 + Fix 6: Filter out blocked books & live games, sort by ev_score desc
  const filteredSignals = useMemo(() => {
    const filtered = signals.filter(
      (sig) =>
        !BLOCKED_BOOKS.has(sig.sportsbook) &&
        !liveGameIds.has(sig.game_id),
    );
    // Fix 3: Sort by ev_score descending
    filtered.sort((a, b) => (b.ev_score ?? 0) - (a.ev_score ?? 0));
    return filtered;
  }, [signals, liveGameIds]);

  // Lookup game start_time for a signal
  function getGameStartTime(sig: Signal): string | null {
    const opp = opportunities.find((o) => o.game_id === sig.game_id);
    return opp?.games?.start_time ?? null;
  }

  function handleToggleScore(sigId: number, label: string) {
    const key = `${sigId}:${label}`;
    setExpandedScore((prev) => (prev === key ? null : key));
  }

  function handleToggleCard(id: number) {
    setExpandedCardId((prev) => (prev === id ? null : id));
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
      ) : filteredSignals.length === 0 ? (
        <div className="mt-12 text-center text-gray-500">
          No active picks right now.
        </div>
      ) : (
        <div className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {filteredSignals.map((sig) => (
            <SignalCard
              key={sig.id}
              sig={sig}
              expandedScore={
                expandedScore?.startsWith(`${sig.id}:`)
                  ? expandedScore.split(":")[1]
                  : null
              }
              onToggleScore={(label) => handleToggleScore(sig.id, label)}
              expandedCardId={expandedCardId}
              onToggleCard={handleToggleCard}
              unitSize={unitSize}
              kellyBetSize={kellyBetSize}
              opportunities={opportunities}
              oppsLoading={oppsLoading}
              gameStartTime={getGameStartTime(sig)}
            />
          ))}
        </div>
      )}
    </div>
  );
}
