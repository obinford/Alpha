"use client";

import { useEffect, useMemo, useState } from "react";
import { useBankroll, KellyMultiplier } from "@/lib/bankroll-context";
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

/** Fix 6: Time badge for upcoming games */
function TimeBadge({ startTime }: { startTime: string }) {
  const diff = new Date(startTime).getTime() - Date.now();
  if (diff <= 0) return null; // live — should already be filtered
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
// Bankroll card (always visible, not collapsible)
// ---------------------------------------------------------------------------

const KELLY_OPTIONS: { value: KellyMultiplier; label: string }[] = [
  { value: 1.0, label: "Full Kelly (1.0x)" },
  { value: 0.5, label: "Half Kelly (0.5x)" },
  { value: 0.25, label: "Quarter Kelly (0.25x)" },
  { value: 0.125, label: "Eighth Kelly (0.125x)" },
];

function BankrollCard() {
  const { bankroll, kellyMultiplier, unitSize, setBankroll, setKellyMultiplier, kellyLabel } =
    useBankroll();
  const [editing, setEditing] = useState(false);
  const [inputValue, setInputValue] = useState(
    bankroll != null ? String(bankroll) : "",
  );

  function handleSave() {
    const parsed = parseFloat(inputValue.replace(/[,$]/g, ""));
    if (!isNaN(parsed) && parsed > 0) {
      setBankroll(parsed);
    }
    setEditing(false);
  }

  return (
    <div className="rounded-2xl bg-[#1c1c1e] p-5">
      <div className="flex items-center justify-between">
        <p className="text-xs font-medium uppercase tracking-wider text-gray-500">
          Bankroll
        </p>
        {!editing && (
          <button
            onClick={() => {
              setInputValue(bankroll != null ? String(bankroll) : "");
              setEditing(true);
            }}
            className="text-[10px] text-gray-500 transition-colors hover:text-gray-300"
          >
            Edit
          </button>
        )}
      </div>

      {editing ? (
        <div className="mt-2 space-y-2">
          <input
            type="text"
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            placeholder="1000"
            className="w-full rounded-lg bg-[#2c2c2e] px-3 py-2 text-sm text-white placeholder-gray-600 outline-none focus:ring-1 focus:ring-emerald-500"
            autoFocus
          />
          <select
            value={kellyMultiplier}
            onChange={(e) =>
              setKellyMultiplier(parseFloat(e.target.value) as KellyMultiplier)
            }
            className="w-full rounded-lg bg-[#2c2c2e] px-3 py-2 text-sm text-white outline-none focus:ring-1 focus:ring-emerald-500"
          >
            {KELLY_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
          <div className="flex gap-2">
            <button
              onClick={handleSave}
              className="rounded-lg bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-emerald-500"
            >
              Save
            </button>
            <button
              onClick={() => setEditing(false)}
              className="rounded-lg px-3 py-1.5 text-xs text-gray-400 transition-colors hover:text-gray-200"
            >
              Cancel
            </button>
          </div>
        </div>
      ) : bankroll != null ? (
        <div className="mt-1">
          <p className="text-2xl font-bold text-white">
            ${bankroll.toLocaleString()}
          </p>
          <p className="mt-0.5 text-xs text-gray-500">
            {kellyLabel} &middot; 1u = ${unitSize?.toFixed(2) ?? "0"}
          </p>
        </div>
      ) : (
        <p className="mt-2 text-sm text-gray-500">
          Set your bankroll to see personalized bet sizing.
          <button
            onClick={() => setEditing(true)}
            className="ml-2 text-emerald-400 hover:text-emerald-300"
          >
            Set up
          </button>
        </p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Book filter
// ---------------------------------------------------------------------------

function BookFilter({
  allBooks,
  selectedBooks,
  onToggle,
  onSelectAll,
  onClear,
}: {
  allBooks: string[];
  selectedBooks: Set<string> | null;
  onToggle: (book: string) => void;
  onSelectAll: () => void;
  onClear: () => void;
}) {
  if (allBooks.length === 0) return null;

  function isSelected(book: string) {
    return selectedBooks == null || selectedBooks.has(book);
  }

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <span className="mr-1 text-[10px] font-medium uppercase tracking-wider text-gray-600">
        Books:
      </span>
      <button
        onClick={onSelectAll}
        className={`rounded-full px-2.5 py-1 text-[11px] font-medium transition-colors ${
          selectedBooks == null
            ? "bg-emerald-600 text-white"
            : "bg-[#2c2c2e] text-gray-500 hover:text-gray-300"
        }`}
      >
        All
      </button>
      <button
        onClick={onClear}
        className="rounded-full bg-[#2c2c2e] px-2.5 py-1 text-[11px] text-gray-500 transition-colors hover:text-gray-300"
      >
        Clear
      </button>
      {allBooks.map((book) => (
        <button
          key={book}
          onClick={() => onToggle(book)}
          className={`rounded-full px-2.5 py-1 text-[11px] font-medium transition-colors ${
            isSelected(book)
              ? "bg-emerald-600/80 text-white"
              : "bg-[#2c2c2e] text-gray-500 hover:text-gray-300"
          }`}
        >
          {book}
        </button>
      ))}
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
  const { bankroll, kellyBetSize, unitSize, kellyLabel } = useBankroll();

  // Fix 1: Flexible matching — try exact match first, then fuzzy (game_id only)
  let matchingOpps = opportunities.filter(
    (o) =>
      o.game_id === sig.game_id &&
      o.market_type === sig.market_type &&
      o.side === sig.side &&
      !BLOCKED_BOOKS.has(o.sportsbook),
  );

  // Fuzzy fallback: same game + market_type (relaxed side match)
  if (matchingOpps.length === 0) {
    matchingOpps = opportunities.filter(
      (o) =>
        o.game_id === sig.game_id &&
        o.market_type === sig.market_type &&
        !BLOCKED_BOOKS.has(o.sportsbook),
    );
  }

  // Fix 3: Sort by EV% descending, Pinnacle always on top handled separately
  matchingOpps.sort((a, b) => (b.ev_percentage ?? 0) - (a.ev_percentage ?? 0));

  const game = matchingOpps[0]?.games ?? null;

  const trueProb =
    sig.true_prob ?? (matchingOpps.length > 0 ? matchingOpps[0].true_prob : null);
  const pinOdds =
    trueProb != null && trueProb > 0 ? trueProbToAmericanOdds(trueProb) : null;

  const scores = [
    { label: "EV", score: sig.ev_score ?? 0 },
    { label: "Steam", score: sig.steam_score ?? 0 },
    { label: "Proj", score: sig.projection_score ?? 0 },
    { label: "Cons", score: sig.consensus_score ?? 0 },
    { label: "Intel", score: sig.intelligence_score ?? 0 },
  ];

  // Fix 4: Kelly calculations — read kelly_fraction correctly, compute dollar amount
  const kellyPct =
    sig.kelly_fraction != null && sig.kelly_fraction > 0
      ? sig.kelly_fraction * 100
      : null;
  const kellyDollar =
    sig.kelly_fraction != null && sig.kelly_fraction > 0
      ? kellyBetSize(sig.kelly_fraction)
      : null;

  // Fix 1: Build book rows — always show SOMETHING
  // Merge opportunities + signal's own data + other_books for a complete picture
  const otherBooks = (sig.other_books ?? []).filter(
    (ob) => !BLOCKED_BOOKS.has(ob.sportsbook),
  );

  // Determine if we should use opps or fallback
  const hasOpps = matchingOpps.length > 0;

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
              <BetLink book={sig.sportsbook} />
            </p>
            {pinOdds != null && (
              <p className="mt-0.5 text-xs text-blue-400/70">
                PIN {formatOdds(pinOdds)}
              </p>
            )}
          </div>
          {/* Fix 4: Enhanced stats with Kelly + Unit display */}
          <div className="grid grid-cols-2 gap-2 text-center sm:grid-cols-4">
            <div>
              <p className="text-[10px] uppercase text-gray-500">Edge</p>
              <p className="font-mono text-sm font-bold text-emerald-400">
                +{(sig.edge_percentage ?? 0).toFixed(1)}%
              </p>
            </div>
            <div>
              <p className="text-[10px] uppercase text-gray-500">Strength</p>
              <p
                className={`font-mono text-sm font-bold ${strengthColor(sig.signal_strength ?? 0)}`}
              >
                {(sig.signal_strength ?? 0).toFixed(1)}
              </p>
            </div>
            <div>
              <p className="text-[10px] uppercase text-gray-500">Kelly</p>
              <p className="font-mono text-sm text-gray-300">
                {kellyPct != null ? `${kellyPct.toFixed(1)}%` : "\u2014"}
              </p>
              {kellyDollar != null ? (
                <p className="text-[10px] text-emerald-400/70">
                  ${kellyDollar.toFixed(2)}
                </p>
              ) : bankroll == null && kellyPct != null ? (
                <p className="text-[10px] text-gray-600">Set bankroll</p>
              ) : null}
            </div>
            <div>
              <p className="text-[10px] uppercase text-gray-500">Unit</p>
              {unitSize != null ? (
                <>
                  <p className="font-mono text-sm text-gray-300">
                    {kellyPct != null
                      ? `${(kellyPct / 1).toFixed(1)}%`
                      : "1u"}
                  </p>
                  <p className="text-[10px] text-gray-500">
                    1u = ${unitSize.toFixed(2)}
                  </p>
                </>
              ) : (
                <p className="font-mono text-sm text-gray-500">{"\u2014"}</p>
              )}
            </div>
          </div>
        </div>

        {/* Component scores */}
        <div className="mb-4 space-y-1.5">
          {scores.map((s) => (
            <ScoreBar key={s.label} label={s.label} score={s.score} />
          ))}
        </div>

        {/* Odds comparison table — Fix 1: ALWAYS show data, never empty */}
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
              {/* Pinnacle reference row — Fix 3: always on top */}
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
                /* Fix 1: Fallback — always show signal's own data + other_books */
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
                      {trueProb != null ? pct(trueProb * 100) : "\u2014"}
                    </td>
                    <td className="px-3 py-2" />
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
                      <td className="px-3 py-2" />
                      <td className="px-3 py-2" />
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
  const [selectedBooks, setSelectedBooks] = useState<Set<string> | null>(null);

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

  // Fix 6: Filter out live games — compare game start_time from opportunities
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

  // Derive all unique books from signals (primary + other_books), excluding blocked
  const allBooks = useMemo(() => {
    const s = new Set<string>();
    for (const sig of signals) {
      if (!BLOCKED_BOOKS.has(sig.sportsbook)) s.add(sig.sportsbook);
      if (sig.other_books) {
        for (const ob of sig.other_books) {
          if (!BLOCKED_BOOKS.has(ob.sportsbook)) s.add(ob.sportsbook);
        }
      }
    }
    return Array.from(s).sort();
  }, [signals]);

  // Filter signals: remove blocked books, remove live games, apply user book filter
  // Fix 3: Sort by ev_score descending
  const filteredSignals = useMemo(() => {
    let filtered = signals.filter(
      (sig) =>
        !BLOCKED_BOOKS.has(sig.sportsbook) &&
        !liveGameIds.has(sig.game_id),
    );
    if (selectedBooks != null) {
      filtered = filtered.filter(
        (sig) =>
          selectedBooks.has(sig.sportsbook) ||
          (sig.other_books?.some(
            (ob) =>
              !BLOCKED_BOOKS.has(ob.sportsbook) &&
              selectedBooks.has(ob.sportsbook),
          ) ?? false),
      );
    }
    // Fix 3: Sort by ev_score descending
    filtered.sort((a, b) => (b.ev_score ?? 0) - (a.ev_score ?? 0));
    return filtered;
  }, [signals, selectedBooks, liveGameIds]);

  // Lookup game start_time for a signal
  function getGameStartTime(sig: Signal): string | null {
    const opp = opportunities.find((o) => o.game_id === sig.game_id);
    return opp?.games?.start_time ?? null;
  }

  function toggleBook(book: string) {
    setSelectedBooks((prev) => {
      if (prev == null) {
        const next = new Set(allBooks);
        next.delete(book);
        return next;
      }
      const next = new Set(prev);
      if (next.has(book)) next.delete(book);
      else next.add(book);
      if (next.size === allBooks.length) return null;
      return next;
    });
  }

  const topSignal = filteredSignals.length > 0 ? filteredSignals[0] : null;
  const nextGameTime = filteredSignals
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

      {/* Stat cards + Bankroll card */}
      <div className="mt-6 grid grid-cols-2 gap-3 sm:grid-cols-5">
        <StatCard
          label="Active Signals"
          value={String(filteredSignals.length)}
          accent={filteredSignals.length > 0 ? "green" : "neutral"}
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
              : "\u2014"
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
          value={nextGameTime ? formatTimeUntil(nextGameTime) : "\u2014"}
          sub={
            nextGameTime
              ? new Date(nextGameTime).toLocaleTimeString([], {
                  hour: "numeric",
                  minute: "2-digit",
                })
              : undefined
          }
        />
        <BankrollCard />
      </div>

      {/* Book filter */}
      {allBooks.length > 0 && (
        <div className="mt-4">
          <BookFilter
            allBooks={allBooks}
            selectedBooks={selectedBooks}
            onToggle={toggleBook}
            onSelectAll={() => setSelectedBooks(null)}
            onClear={() => setSelectedBooks(new Set())}
          />
        </div>
      )}

      {/* Active signals list */}
      <div className="mt-6">
        <h2 className="text-lg font-semibold">Active Signals</h2>
        {filteredSignals.length === 0 ? (
          <div className="mt-6 rounded-2xl bg-[#1c1c1e] p-8 text-center text-gray-500">
            {signals.length > 0
              ? "No signals match the selected books."
              : "No active signals right now. Signals fire when the confluence model detects high-confidence plays."}
          </div>
        ) : (
          <div className="mt-3 space-y-2">
            {filteredSignals.map((sig) => {
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
              const startTime = getGameStartTime(sig);

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
                        {/* Fix 6: Time badges */}
                        {startTime && <TimeBadge startTime={startTime} />}
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
