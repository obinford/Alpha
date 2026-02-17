"use client";

import { useEffect, useState } from "react";

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
  const pct = max ? Math.min(Math.abs(pnl) / max, 1) * 100 : 0;
  const color = pnl >= 0 ? "bg-emerald-500" : "bg-red-500";
  return (
    <div className="flex items-center gap-2">
      <div className="h-2 w-24 rounded-full bg-[#2c2c2e]">
        <div
          className={`h-2 rounded-full ${color}`}
          style={{ width: `${pct}%` }}
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
// Tabs
// ---------------------------------------------------------------------------

function SignalsTab({ data }: { data: SignalPerformance | null }) {
  if (!data) return <p className="text-center text-gray-500">Loading...</p>;

  const totalPnl = data.total_profit_loss ?? 0;
  const totalWagered = data.total_wagered ?? 0;
  const winRate = data.win_rate ?? 0;
  const roiPct = data.roi_percent ?? 0;
  const pending = data.pending ?? 0;
  const pnlColor = totalPnl >= 0 ? "green" : "red";
  const roiColor = roiPct >= 0 ? "green" : "red";
  const tiers = data.by_tier ?? {};
  const sports = data.by_sport ?? {};
  const tierMax = Math.max(
    ...Object.values(tiers).map((t) => Math.abs(t.pnl ?? 0)),
    1,
  );

  return (
    <div className="space-y-6">
      {/* Hero stats */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatCard
          label="Record"
          value={data.record ?? "0-0"}
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
        <StatCard label="Streak" value={data.streak ?? "\u2014"} />
        <StatCard
          label="Best Day"
          value={data.best_day ? `+$${(data.best_day.pnl ?? 0).toFixed(0)}` : "\u2014"}
          sub={data.best_day?.date}
          accent="green"
        />
        <StatCard
          label="Worst Day"
          value={
            data.worst_day ? `$${(data.worst_day.pnl ?? 0).toFixed(0)}` : "\u2014"
          }
          sub={data.worst_day?.date}
          accent="red"
        />
      </div>

      {/* Running P/L chart */}
      <div className="rounded-2xl bg-[#1c1c1e] p-5">
        <p className="mb-3 text-xs font-medium uppercase tracking-wider text-gray-500">
          Running P/L
        </p>
        <MiniChart data={data.running_pnl ?? []} />
      </div>

      {/* Tier breakdown */}
      <div className="rounded-2xl bg-[#1c1c1e] p-5">
        <p className="mb-3 text-xs font-medium uppercase tracking-wider text-gray-500">
          By Star Rating
        </p>
        <div className="space-y-3">
          {Object.entries(tiers).map(([tier, stats]) => (
            <div key={tier} className="flex items-center justify-between">
              <span className="text-sm text-gray-300">
                {tier.replace("_", " ")}
              </span>
              <div className="flex items-center gap-4">
                <span className="text-xs text-gray-400">{stats.record ?? "0-0"}</span>
                <span className="text-xs text-gray-400">{stats.win_rate ?? 0}%</span>
                <PnlBar pnl={stats.pnl ?? 0} max={tierMax} />
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
          {Object.entries(sports).map(([sport, stats]) => {
            const sportPnl = stats.pnl ?? 0;
            return (
              <div key={sport} className="flex items-center justify-between">
                <span className="text-sm text-gray-300">
                  {sport
                    .replace("_", " ")
                    .replace("basketball ", "")
                    .toUpperCase()}
                </span>
                <div className="flex items-center gap-4">
                  <span className="text-xs text-gray-400">{stats.record ?? "0-0"}</span>
                  <span className="text-xs text-gray-400">{stats.win_rate ?? 0}%</span>
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
        <StatCard label="Record" value={data.record ?? "0-0"} />
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

  useEffect(() => {
    fetch(`${API_BASE}/api/signals/performance?days=30`)
      .then((r) => r.json())
      .then(setSignalData)
      .catch(() => {});

    fetch(`${API_BASE}/api/performance/summary`)
      .then((r) => r.json())
      .then(setScannerData)
      .catch(() => {});
  }, []);

  return (
    <div className="mx-auto max-w-3xl">
      <h1 className="text-2xl font-bold">Performance</h1>
      <p className="mt-1 text-sm text-gray-500">
        Track your results. $100 flat bets on every RTM Signal.
      </p>

      {/* Tab bar - iOS segmented control style */}
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

      <div className="mt-6">
        {tab === "signals" ? (
          <SignalsTab data={signalData} />
        ) : (
          <ScannerTab data={scannerData} />
        )}
      </div>
    </div>
  );
}
