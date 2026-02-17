"use client";

import { useEffect, useMemo, useState } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface SignalPerformance {
  total_signals: number;
  wins: number;
  losses: number;
  pushes: number;
  pending: number;
  record: string;
  win_rate: number;
  total_wagered: number;
  total_profit_loss: number;
  roi_percent: number;
  streak: string;
  best_day: { date: string; pnl: number } | null;
  worst_day: { date: string; pnl: number } | null;
  running_pnl: { date: string; pnl: number }[];
  by_tier: Record<string, TierStats>;
  by_sport: Record<string, SportStats>;
}

interface TierStats {
  record: string;
  win_rate: number;
  pnl: number;
  roi: number;
  total: number;
}

interface SportStats {
  record: string;
  win_rate: number;
  pnl: number;
}

interface ScannerPerformance {
  total_bets: number;
  wins: number;
  losses: number;
  pushes: number;
  record: string;
  win_rate: number;
  units_profit: number;
  roi: number;
  avg_ev: number;
}

/** Individual graded signal from /api/signals/history */
interface GradedSignal {
  id: number;
  game_id: string;
  sport: string;
  market_type: string;
  side: string;
  sportsbook: string;
  book_odds: number;
  signal_strength: number;
  star_rating: number;
  edge_percentage: number;
  status: string;
  result: string | null;
  profit_loss: number | null;
  bet_amount: number | null;
  created_at: string;
  graded_at: string | null;
}

/** Computed per-book stats */
interface BookStats {
  sportsbook: string;
  bets: number;
  wins: number;
  losses: number;
  pushes: number;
  winRate: number;
  roi: number;
  profitLoss: number;
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

function PnlBar({ pnl, max }: { pnl: number; max: number }) {
  const barPct = max ? Math.min(Math.abs(pnl) / max, 1) * 100 : 0;
  const color = pnl >= 0 ? "bg-emerald-500" : "bg-red-500";
  return (
    <div className="flex items-center gap-2">
      <div className="h-2 w-24 rounded-full bg-[#2c2c2e]">
        <div
          className={`h-2 rounded-full ${color}`}
          style={{ width: `${barPct}%` }}
        />
      </div>
      <span
        className={`text-xs font-medium ${pnl >= 0 ? "text-emerald-400" : "text-red-400"}`}
      >
        {pnl >= 0 ? "+" : ""}${pnl.toFixed(0)}
      </span>
    </div>
  );
}

function MiniChart({ data }: { data: { date: string; pnl: number }[] }) {
  if (!data.length)
    return <p className="text-sm text-gray-500">No data yet</p>;

  const values = data.map((d) => d.pnl);
  const min = Math.min(0, ...values);
  const max = Math.max(0, ...values);
  const range = max - min || 1;
  const h = 120;
  const w = 400;
  const step = data.length > 1 ? w / (data.length - 1) : 0;

  const points = data
    .map((d, i) => `${i * step},${h - ((d.pnl - min) / range) * h}`)
    .join(" ");

  const zeroY = h - ((0 - min) / range) * h;

  return (
    <svg
      viewBox={`0 0 ${w} ${h}`}
      className="w-full"
      preserveAspectRatio="none"
    >
      <line
        x1={0}
        y1={zeroY}
        x2={w}
        y2={zeroY}
        stroke="#3a3a3c"
        strokeWidth={1}
      />
      <polyline
        points={points}
        fill="none"
        stroke={values[values.length - 1] >= 0 ? "#34d399" : "#f87171"}
        strokeWidth={2}
      />
    </svg>
  );
}

// ---------------------------------------------------------------------------
// Compute filtered stats from individual signals
// ---------------------------------------------------------------------------

function computeStats(signals: GradedSignal[]) {
  const graded = signals.filter(
    (s) => s.result === "win" || s.result === "loss" || s.result === "push",
  );
  const wins = graded.filter((s) => s.result === "win").length;
  const losses = graded.filter((s) => s.result === "loss").length;
  const pushes = graded.filter((s) => s.result === "push").length;
  const pending = signals.filter((s) => !s.result || s.result === "pending").length;
  const decided = wins + losses;
  const winRate = decided > 0 ? (wins / decided) * 100 : 0;
  const totalPnl = graded.reduce((sum, s) => sum + (s.profit_loss ?? 0), 0);
  const totalWagered = graded.reduce((sum, s) => sum + (s.bet_amount ?? 100), 0);
  const roi = totalWagered > 0 ? (totalPnl / totalWagered) * 100 : 0;

  const record =
    pushes > 0
      ? `${wins}\u2011${losses}\u2011${pushes}`
      : `${wins}\u2011${losses}`;

  // By tier
  const tierMap: Record<string, GradedSignal[]> = {};
  for (const s of graded) {
    const tier = `${s.star_rating}_star`;
    if (!tierMap[tier]) tierMap[tier] = [];
    tierMap[tier].push(s);
  }
  const byTier: Record<string, TierStats> = {};
  for (const [tier, sigs] of Object.entries(tierMap)) {
    const tw = sigs.filter((s) => s.result === "win").length;
    const tl = sigs.filter((s) => s.result === "loss").length;
    const tp = sigs.filter((s) => s.result === "push").length;
    const td = tw + tl;
    const tPnl = sigs.reduce((sum, s) => sum + (s.profit_loss ?? 0), 0);
    const tWag = sigs.reduce((sum, s) => sum + (s.bet_amount ?? 100), 0);
    byTier[tier] = {
      record: tp > 0 ? `${tw}\u2011${tl}\u2011${tp}` : `${tw}\u2011${tl}`,
      win_rate: td > 0 ? Math.round((tw / td) * 100) : 0,
      pnl: tPnl,
      roi: tWag > 0 ? Math.round((tPnl / tWag) * 100) : 0,
      total: sigs.length,
    };
  }

  // By sport
  const sportMap: Record<string, GradedSignal[]> = {};
  for (const s of graded) {
    if (!sportMap[s.sport]) sportMap[s.sport] = [];
    sportMap[s.sport].push(s);
  }
  const bySport: Record<string, SportStats> = {};
  for (const [sport, sigs] of Object.entries(sportMap)) {
    const sw = sigs.filter((s) => s.result === "win").length;
    const sl = sigs.filter((s) => s.result === "loss").length;
    const sp = sigs.filter((s) => s.result === "push").length;
    const sd = sw + sl;
    const sPnl = sigs.reduce((sum, s) => sum + (s.profit_loss ?? 0), 0);
    bySport[sport] = {
      record: sp > 0 ? `${sw}\u2011${sl}\u2011${sp}` : `${sw}\u2011${sl}`,
      win_rate: sd > 0 ? Math.round((sw / sd) * 100) : 0,
      pnl: sPnl,
    };
  }

  // Running P/L
  const sorted = [...graded]
    .filter((s) => s.graded_at)
    .sort((a, b) => (a.graded_at ?? "").localeCompare(b.graded_at ?? ""));
  let cumPnl = 0;
  const dateMap = new Map<string, number>();
  for (const s of sorted) {
    const date = (s.graded_at ?? s.created_at).slice(0, 10);
    cumPnl += s.profit_loss ?? 0;
    dateMap.set(date, cumPnl);
  }
  const runningPnl = Array.from(dateMap.entries()).map(([date, pnl]) => ({
    date,
    pnl,
  }));

  return {
    total_signals: signals.length,
    wins,
    losses,
    pushes,
    pending,
    record,
    win_rate: Math.round(winRate * 10) / 10,
    total_wagered: totalWagered,
    total_profit_loss: totalPnl,
    roi_percent: Math.round(roi * 10) / 10,
    streak: "",
    best_day: null as { date: string; pnl: number } | null,
    worst_day: null as { date: string; pnl: number } | null,
    running_pnl: runningPnl,
    by_tier: byTier,
    by_sport: bySport,
  };
}

function computeBookStats(signals: GradedSignal[]): BookStats[] {
  const graded = signals.filter(
    (s) => s.result === "win" || s.result === "loss" || s.result === "push",
  );
  const bookMap: Record<string, GradedSignal[]> = {};
  for (const s of graded) {
    if (!bookMap[s.sportsbook]) bookMap[s.sportsbook] = [];
    bookMap[s.sportsbook].push(s);
  }

  const stats: BookStats[] = [];
  for (const [book, sigs] of Object.entries(bookMap)) {
    const w = sigs.filter((s) => s.result === "win").length;
    const l = sigs.filter((s) => s.result === "loss").length;
    const p = sigs.filter((s) => s.result === "push").length;
    const d = w + l;
    const pnl = sigs.reduce((sum, s) => sum + (s.profit_loss ?? 0), 0);
    const wag = sigs.reduce((sum, s) => sum + (s.bet_amount ?? 100), 0);
    stats.push({
      sportsbook: book,
      bets: sigs.length,
      wins: w,
      losses: l,
      pushes: p,
      winRate: d > 0 ? Math.round((w / d) * 1000) / 10 : 0,
      roi: wag > 0 ? Math.round((pnl / wag) * 1000) / 10 : 0,
      profitLoss: pnl,
    });
  }

  stats.sort((a, b) => b.roi - a.roi);
  return stats;
}

// ---------------------------------------------------------------------------
// Book filter component
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
// Tabs
// ---------------------------------------------------------------------------

function SignalsTab({
  data,
  allSignals,
  selectedBooks,
}: {
  data: SignalPerformance | null;
  allSignals: GradedSignal[];
  selectedBooks: Set<string> | null;
}) {
  // When books are filtered, compute stats from individual signals
  const stats = useMemo(() => {
    if (selectedBooks == null && data) return data;
    if (allSignals.length === 0) return data;
    const filtered =
      selectedBooks != null
        ? allSignals.filter((s) => selectedBooks.has(s.sportsbook))
        : allSignals;
    return computeStats(filtered);
  }, [data, allSignals, selectedBooks]);

  if (!stats) return <p className="text-center text-gray-500">Loading...</p>;

  const totalPnl = stats.total_profit_loss ?? 0;
  const totalWagered = stats.total_wagered ?? 0;
  const winRate = stats.win_rate ?? 0;
  const roiPct = stats.roi_percent ?? 0;
  const pending = stats.pending ?? 0;
  const pnlColor = totalPnl >= 0 ? "green" : "red";
  const roiColor = roiPct >= 0 ? "green" : "red";
  const tiers = stats.by_tier ?? {};
  const sports = stats.by_sport ?? {};
  const tierMax = Math.max(
    ...Object.values(tiers).map((t) => Math.abs(t.pnl ?? 0)),
    1,
  );

  // Per-book breakdown
  const filteredSignals =
    selectedBooks != null
      ? allSignals.filter((s) => selectedBooks.has(s.sportsbook))
      : allSignals;
  const bookStats = computeBookStats(filteredSignals);

  return (
    <div className="space-y-6">
      {/* Hero stats */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatCard
          label="Record"
          value={stats.record ?? "0\u20110"}
          sub={`${pending} pending`}
        />
        <StatCard
          label="Win Rate"
          value={`${winRate}%`}
          accent={winRate >= 52 ? "green" : "neutral"}
        />
        <StatCard
          label="Profit / Loss"
          value={`${totalPnl >= 0 ? "+" : ""}$${totalPnl.toFixed(0)}`}
          sub={`$${totalWagered.toFixed(0)} wagered`}
          accent={pnlColor as "green" | "red"}
        />
        <StatCard
          label="ROI"
          value={`${roiPct >= 0 ? "+" : ""}${roiPct}%`}
          accent={roiColor as "green" | "red"}
        />
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        <StatCard label="Streak" value={stats.streak || "\u2014"} />
        <StatCard
          label="Best Day"
          value={stats.best_day ? `+$${(stats.best_day.pnl ?? 0).toFixed(0)}` : "\u2014"}
          sub={stats.best_day?.date}
          accent="green"
        />
        <StatCard
          label="Worst Day"
          value={
            stats.worst_day ? `$${(stats.worst_day.pnl ?? 0).toFixed(0)}` : "\u2014"
          }
          sub={stats.worst_day?.date}
          accent="red"
        />
      </div>

      {/* Running P/L chart */}
      <div className="rounded-2xl bg-[#1c1c1e] p-5">
        <p className="mb-3 text-xs font-medium uppercase tracking-wider text-gray-500">
          Running P/L
        </p>
        <MiniChart data={stats.running_pnl ?? []} />
      </div>

      {/* Tier breakdown */}
      <div className="rounded-2xl bg-[#1c1c1e] p-5">
        <p className="mb-3 text-xs font-medium uppercase tracking-wider text-gray-500">
          By Star Rating
        </p>
        <div className="space-y-3">
          {Object.entries(tiers).map(([tier, tStats]) => (
            <div key={tier} className="flex items-center justify-between">
              <span className="text-sm text-gray-300">
                {tier.replace("_", " ")}
              </span>
              <div className="flex items-center gap-4">
                <span className="text-xs text-gray-400">{tStats.record ?? "0\u20110"}</span>
                <span className="text-xs text-gray-400">{tStats.win_rate ?? 0}%</span>
                <PnlBar pnl={tStats.pnl ?? 0} max={tierMax} />
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Sport breakdown */}
      <div className="rounded-2xl bg-[#1c1c1e] p-5">
        <p className="mb-3 text-xs font-medium uppercase tracking-wider text-gray-500">
          By Sport
        </p>
        <div className="space-y-3">
          {Object.entries(sports).map(([sport, sStats]) => {
            const sportPnl = sStats.pnl ?? 0;
            return (
              <div key={sport} className="flex items-center justify-between">
                <span className="text-sm text-gray-300">
                  {sport
                    .replace("_", " ")
                    .replace("basketball ", "")
                    .toUpperCase()}
                </span>
                <div className="flex items-center gap-4">
                  <span className="text-xs text-gray-400">{sStats.record ?? "0\u20110"}</span>
                  <span className="text-xs text-gray-400">{sStats.win_rate ?? 0}%</span>
                  <span
                    className={`text-xs font-medium ${sportPnl >= 0 ? "text-emerald-400" : "text-red-400"}`}
                  >
                    {sportPnl >= 0 ? "+" : ""}${sportPnl.toFixed(0)}
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Per-book breakdown table */}
      {bookStats.length > 0 && (
        <div className="rounded-2xl bg-[#1c1c1e] p-5">
          <p className="mb-3 text-xs font-medium uppercase tracking-wider text-gray-500">
            By Sportsbook
          </p>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-gray-800 text-[10px] font-medium uppercase tracking-wider text-gray-500">
                  <th className="pb-2 pr-4">Book</th>
                  <th className="pb-2 pr-4 text-right">Bets</th>
                  <th className="pb-2 pr-4 text-right">Record</th>
                  <th className="pb-2 pr-4 text-right">Win%</th>
                  <th className="pb-2 pr-4 text-right">ROI%</th>
                  <th className="pb-2 text-right">P/L</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-800/50">
                {bookStats.map((bs) => (
                  <tr key={bs.sportsbook}>
                    <td className="py-2 pr-4 text-gray-300">{bs.sportsbook}</td>
                    <td className="py-2 pr-4 text-right font-mono text-gray-400">
                      {bs.bets}
                    </td>
                    <td className="py-2 pr-4 text-right font-mono text-gray-400">
                      {bs.pushes > 0
                        ? `${bs.wins}\u2011${bs.losses}\u2011${bs.pushes}`
                        : `${bs.wins}\u2011${bs.losses}`}
                    </td>
                    <td className="py-2 pr-4 text-right font-mono text-gray-400">
                      {bs.winRate}%
                    </td>
                    <td
                      className={`py-2 pr-4 text-right font-mono font-medium ${bs.roi >= 0 ? "text-emerald-400" : "text-red-400"}`}
                    >
                      {bs.roi >= 0 ? "+" : ""}{bs.roi}%
                    </td>
                    <td
                      className={`py-2 text-right font-mono font-medium ${bs.profitLoss >= 0 ? "text-emerald-400" : "text-red-400"}`}
                    >
                      {bs.profitLoss >= 0 ? "+" : ""}${bs.profitLoss.toFixed(0)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

function ScannerTab({ data }: { data: ScannerPerformance | null }) {
  if (!data) return <p className="text-center text-gray-500">Loading...</p>;

  const unitsProfit = data.units_profit ?? 0;
  const winRate = data.win_rate ?? 0;
  const roi = data.roi ?? 0;
  const avgEv = data.avg_ev ?? 0;
  const wins = data.wins ?? 0;
  const losses = data.losses ?? 0;
  const pushes = data.pushes ?? 0;

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatCard label="Total Bets" value={String(data.total_bets ?? 0)} />
        <StatCard label="Record" value={data.record ?? "0\u20110"} />
        <StatCard
          label="Win Rate"
          value={`${winRate}%`}
          accent={winRate >= 52 ? "green" : "neutral"}
        />
        <StatCard
          label="Units P/L"
          value={`${unitsProfit >= 0 ? "+" : ""}${unitsProfit.toFixed(2)}u`}
          accent={unitsProfit >= 0 ? "green" : "red"}
        />
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        <StatCard
          label="ROI"
          value={`${roi >= 0 ? "+" : ""}${roi}%`}
          accent={roi >= 0 ? "green" : "red"}
        />
        <StatCard label="Avg EV" value={`${avgEv}%`} accent="green" />
        <StatCard
          label="Decided"
          value={`${wins + losses}`}
          sub={pushes ? `${pushes} pushes` : undefined}
        />
      </div>

      <div className="rounded-2xl bg-[#1c1c1e] p-5">
        <p className="mb-2 text-xs font-medium uppercase tracking-wider text-gray-500">
          About EV Scanner
        </p>
        <p className="text-sm leading-relaxed text-gray-400">
          The EV Scanner tracks every positive expected value opportunity found
          across all odds ranges using Kelly-criterion sizing. CLV (Closing Line
          Value) is the gold-standard metric &mdash; it proves long-term edge
          regardless of short-term variance.
        </p>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

type Tab = "signals" | "scanner";

export default function PerformancePage() {
  const [tab, setTab] = useState<Tab>("signals");
  const [signalData, setSignalData] = useState<SignalPerformance | null>(null);
  const [scannerData, setScannerData] = useState<ScannerPerformance | null>(
    null,
  );
  const [allSignals, setAllSignals] = useState<GradedSignal[]>([]);
  const [selectedBooks, setSelectedBooks] = useState<Set<string> | null>(null);

  useEffect(() => {
    fetch(`${API_BASE}/api/signals/performance?days=30`)
      .then((r) => r.json())
      .then(setSignalData)
      .catch(() => {});

    fetch(`${API_BASE}/api/performance/summary`)
      .then((r) => r.json())
      .then(setScannerData)
      .catch(() => {});

    // Fetch individual signal history for book filtering
    fetch(`${API_BASE}/api/signals/history?days=30`)
      .then((r) => r.json())
      .then((data) => setAllSignals(data.signals ?? []))
      .catch(() => {});
  }, []);

  const allBooks = useMemo(() => {
    const s = new Set<string>();
    for (const sig of allSignals) s.add(sig.sportsbook);
    return Array.from(s).sort();
  }, [allSignals]);

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

  return (
    <div className="mx-auto max-w-3xl">
      <h1 className="text-2xl font-bold">Performance</h1>
      <p className="mt-1 text-sm text-gray-500">
        Track your results. $100 flat bets on every RTM Signal.
      </p>

      {/* Tab bar */}
      <div className="mt-6 inline-flex rounded-xl bg-[#1c1c1e] p-1">
        {(
          [
            { key: "signals" as Tab, label: "RTM Signals" },
            { key: "scanner" as Tab, label: "EV Scanner" },
          ] as const
        ).map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`rounded-lg px-5 py-2 text-sm font-medium transition-colors ${
              tab === t.key
                ? "bg-[#2c2c2e] text-white shadow-sm"
                : "text-gray-400 hover:text-gray-200"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Book filter (signals tab only) */}
      {tab === "signals" && allBooks.length > 0 && (
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

      <div className="mt-6">
        {tab === "signals" ? (
          <SignalsTab
            data={signalData}
            allSignals={allSignals}
            selectedBooks={selectedBooks}
          />
        ) : (
          <ScannerTab data={scannerData} />
        )}
      </div>
    </div>
  );
}
