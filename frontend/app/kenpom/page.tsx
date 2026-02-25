"use client";

import { useEffect, useState, useCallback } from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
  BarChart,
  Bar,
  Cell,
  Legend,
} from "recharts";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface Snapshot {
  id: string;
  snapshot_date: string;
  game_id: string;
  home_team: string;
  away_team: string;
  commence_time: string | null;
  kp_home_score: number;
  kp_away_score: number;
  kp_home_win_prob: number;
  kp_projected_total: number;
  kp_projected_spread: number;
  pinnacle_spread_home: number | null;
  pinnacle_total: number | null;
  pinnacle_home_ml: number | null;
  pinnacle_away_ml: number | null;
  pinnacle_home_implied_prob: number | null;
  pinnacle_spread_home_odds: number | null;
  pinnacle_spread_away_odds: number | null;
  pinnacle_over_odds: number | null;
  pinnacle_under_odds: number | null;
  spread_edge: number | null;
  total_edge: number | null;
  ml_edge: number | null;
  result_home_score: number | null;
  result_away_score: number | null;
  result_spread_correct: boolean | null;
  result_total_correct: boolean | null;
  result_ml_correct: boolean | null;
  spread_unit_result: number | null;
  total_unit_result: number | null;
  ml_unit_result: number | null;
  graded: boolean;
  projection_source?: string | null;
  status?: string;
  hours_until_start?: number;
}

interface SeasonStats {
  total_games_graded: number;
  spread_wins: number;
  spread_losses: number;
  spread_pct: number;
  spread_record: string | null;
  spread_units: number | null;
  total_wins: number;
  total_losses: number;
  total_pct: number;
  total_record: string | null;
  total_units: number | null;
  ml_wins: number;
  ml_losses: number;
  ml_pct: number;
  ml_record: string | null;
  ml_units: number;
  last_updated: string;
}

interface EdgeBucket {
  bucket: string;
  games: number;
  spread_accuracy: number;
  total_accuracy: number;
  spread_units: number;
  total_units: number;
}

interface RollingPoint {
  date: string;
  accuracy: number;
}

interface DailyStats {
  date: string;
  games_graded: number;
  spread_wins: number;
  spread_losses: number;
  spread_pct: number;
  spread_units: number | null;
  total_wins: number;
  total_losses: number;
  total_pct: number;
  total_units: number | null;
  ml_wins: number;
  ml_losses: number;
  ml_pct: number;
  ml_units: number;
  avg_spread_edge_winners: number;
  avg_total_edge_winners: number;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function edgeColor(edge: number | null): string {
  if (edge == null) return "text-gray-500";
  const abs = Math.abs(edge);
  if (abs >= 3) return "text-emerald-400 font-bold";
  if (abs >= 1.5) return "text-amber-400";
  return "text-gray-400";
}

function formatEdge(edge: number | null): string {
  if (edge == null) return "\u2014";
  return `${edge > 0 ? "+" : ""}${edge.toFixed(1)}`;
}

function formatPct(p: number): string {
  return `${p.toFixed(1)}%`;
}

function formatUnits(u: number): string {
  return `${u >= 0 ? "+" : ""}${u.toFixed(2)}u`;
}

function spreadPickText(snap: Snapshot): string {
  if (snap.spread_edge == null || snap.pinnacle_spread_home == null) return "\u2014";
  const pinSpread = snap.pinnacle_spread_home;
  if (snap.spread_edge > 0) {
    // Take home at Pinnacle's home spread
    const fmt = pinSpread > 0 ? `+${pinSpread.toFixed(1)}` : pinSpread.toFixed(1);
    return `Take ${snap.home_team} ${fmt}`;
  }
  // Take away = opposite of home spread
  const awaySpread = -pinSpread;
  const fmt = awaySpread > 0 ? `+${awaySpread.toFixed(1)}` : awaySpread.toFixed(1);
  return `Take ${snap.away_team} ${fmt}`;
}

function totalPickText(snap: Snapshot): string {
  if (snap.total_edge == null || snap.pinnacle_total == null) return "\u2014";
  if (snap.total_edge > 0) {
    return `Take Over ${snap.pinnacle_total.toFixed(1)}`;
  }
  return `Take Under ${snap.pinnacle_total.toFixed(1)}`;
}

function sourceBadge(snap: Snapshot): JSX.Element | null {
  const src = snap.projection_source;
  if (!src) return null;
  if (src.includes("fanmatch")) {
    return <span className="ml-1 rounded bg-emerald-900/40 px-1 py-0.5 text-[9px] font-medium text-emerald-400">FM</span>;
  }
  if (src.includes("ratings")) {
    return <span className="ml-1 rounded bg-amber-900/40 px-1 py-0.5 text-[9px] font-medium text-amber-400">RTG</span>;
  }
  return null;
}

function timeLabel(snap: Snapshot): JSX.Element | null {
  if (snap.status === "final") return <span className="rounded bg-gray-700 px-1.5 py-0.5 text-[9px] text-gray-400">FINAL</span>;
  if (snap.status === "live") return <span className="rounded bg-red-600/30 px-1.5 py-0.5 text-[9px] text-red-400">LIVE</span>;
  if (snap.hours_until_start != null && snap.hours_until_start < 2)
    return <span className="rounded bg-amber-600/30 px-1.5 py-0.5 text-[9px] text-amber-400">SOON</span>;
  return null;
}

// ---------------------------------------------------------------------------
// Components
// ---------------------------------------------------------------------------

function StatCard({ title, value, sub, accent }: {
  title: string;
  value: string;
  sub?: string;
  accent?: "green" | "red" | "default";
}) {
  const accentColor =
    accent === "green" ? "text-emerald-400" :
    accent === "red" ? "text-red-400" :
    "text-gray-200";
  return (
    <div className="rounded-2xl bg-[#1c1c1e] p-4">
      <p className="text-[10px] font-medium uppercase tracking-wider text-gray-500">{title}</p>
      <p className={`mt-1 text-2xl font-bold ${accentColor}`}>{value}</p>
      {sub && <p className="mt-0.5 text-xs text-gray-500">{sub}</p>}
    </div>
  );
}

function SpreadEdgesTable({ snapshots, label }: { snapshots: Snapshot[]; label: string }) {
  const filtered = snapshots
    .filter((s) => s.spread_edge != null && s.status !== "final" && s.status !== "live")
    .sort((a, b) => Math.abs(b.spread_edge!) - Math.abs(a.spread_edge!));

  return (
    <div className="rounded-2xl bg-[#1c1c1e] p-5">
      <h3 className="mb-3 text-sm font-semibold text-gray-300">{label}: Spread Edges</h3>
      {filtered.length === 0 ? (
        <p className="text-xs text-gray-600">No spread edges available</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="border-b border-gray-800 text-[10px] font-medium uppercase tracking-wider text-gray-500">
                <th className="px-2 py-2">Game</th>
                <th className="px-2 py-2 text-right">KP Spread</th>
                <th className="px-2 py-2 text-right">PIN Spread</th>
                <th className="px-2 py-2 text-right">Edge</th>
                <th className="px-2 py-2">Pick Direction</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800/50">
              {filtered.map((s) => (
                <tr key={s.game_id}>
                  <td className="px-2 py-2">
                    <div className="text-gray-300">
                      {s.away_team} @ {s.home_team}
                      {sourceBadge(s)}
                    </div>
                    <div className="text-[10px] text-gray-600">
                      KP: {s.away_team.split(" ").pop()} {s.kp_away_score.toFixed(0)}, {s.home_team.split(" ").pop()} {s.kp_home_score.toFixed(0)}
                    </div>
                    {timeLabel(s)}
                  </td>
                  <td className="whitespace-nowrap px-2 py-2 text-right font-mono text-gray-400">
                    {s.kp_projected_spread > 0 ? "+" : ""}{s.kp_projected_spread.toFixed(1)}
                  </td>
                  <td className="whitespace-nowrap px-2 py-2 text-right font-mono text-gray-500">
                    {s.pinnacle_spread_home != null
                      ? `${s.pinnacle_spread_home > 0 ? "+" : ""}${s.pinnacle_spread_home.toFixed(1)}`
                      : "\u2014"}
                  </td>
                  <td className={`whitespace-nowrap px-2 py-2 text-right font-mono ${edgeColor(s.spread_edge)}`}>
                    {formatEdge(s.spread_edge)}
                  </td>
                  <td className="px-2 py-2 text-[11px] text-gray-400">{spreadPickText(s)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function TotalEdgesTable({ snapshots, label }: { snapshots: Snapshot[]; label: string }) {
  const filtered = snapshots
    .filter((s) => s.total_edge != null && s.status !== "final" && s.status !== "live")
    .sort((a, b) => Math.abs(b.total_edge!) - Math.abs(a.total_edge!));

  return (
    <div className="rounded-2xl bg-[#1c1c1e] p-5">
      <h3 className="mb-3 text-sm font-semibold text-gray-300">{label}: Total Edges</h3>
      {filtered.length === 0 ? (
        <p className="text-xs text-gray-600">No total edges available</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="border-b border-gray-800 text-[10px] font-medium uppercase tracking-wider text-gray-500">
                <th className="px-2 py-2">Game</th>
                <th className="px-2 py-2 text-right">KP Total</th>
                <th className="px-2 py-2 text-right">PIN Total</th>
                <th className="px-2 py-2 text-right">Edge</th>
                <th className="px-2 py-2">Pick Direction</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800/50">
              {filtered.map((s) => (
                <tr key={s.game_id}>
                  <td className="px-2 py-2">
                    <div className="text-gray-300">
                      {s.away_team} @ {s.home_team}
                      {sourceBadge(s)}
                    </div>
                    <div className="text-[10px] text-gray-600">
                      KP: {s.away_team.split(" ").pop()} {s.kp_away_score.toFixed(0)}, {s.home_team.split(" ").pop()} {s.kp_home_score.toFixed(0)}
                    </div>
                    {timeLabel(s)}
                  </td>
                  <td className="whitespace-nowrap px-2 py-2 text-right font-mono text-gray-400">
                    {s.kp_projected_total.toFixed(1)}
                  </td>
                  <td className="whitespace-nowrap px-2 py-2 text-right font-mono text-gray-500">
                    {s.pinnacle_total?.toFixed(1) ?? "\u2014"}
                  </td>
                  <td className={`whitespace-nowrap px-2 py-2 text-right font-mono ${edgeColor(s.total_edge)}`}>
                    {formatEdge(s.total_edge)}
                  </td>
                  <td className="px-2 py-2 text-[11px] text-gray-400">{totalPickText(s)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function KenPomPage() {
  const [todaySnaps, setTodaySnaps] = useState<Snapshot[]>([]);
  const [tomorrowSnaps, setTomorrowSnaps] = useState<Snapshot[]>([]);
  const [tomorrowMsg, setTomorrowMsg] = useState<string | null>(null);
  const [season, setSeason] = useState<SeasonStats | null>(null);
  const [edgeBuckets, setEdgeBuckets] = useState<EdgeBucket[]>([]);
  const [rolling, setRolling] = useState<{ spread: RollingPoint[]; total: RollingPoint[]; ml: RollingPoint[] } | null>(null);
  const [daily, setDaily] = useState<DailyStats[]>([]);
  const [expandedDay, setExpandedDay] = useState<string | null>(null);
  const [dayGames, setDayGames] = useState<Snapshot[]>([]);
  const [loading, setLoading] = useState(true);

  // Filters
  const [fanmatchOnly, setFanmatchOnly] = useState(true);
  const [minEdge, setMinEdge] = useState(1.0);

  const fetchData = useCallback(() => {
    Promise.all([
      fetch(`${API_BASE}/api/kenpom/today`).then((r) => r.json()).catch(() => null),
      fetch(`${API_BASE}/api/kenpom/tomorrow`).then((r) => r.json()).catch(() => null),
      fetch(`${API_BASE}/api/kenpom/performance/season`).then((r) => r.json()).catch(() => null),
      fetch(`${API_BASE}/api/kenpom/performance?days=30`).then((r) => r.json()).catch(() => null),
    ]).then(([todayData, tomorrowData, seasonData, perfData]) => {
      if (todayData?.snapshots) setTodaySnaps(todayData.snapshots);
      if (tomorrowData?.snapshots) setTomorrowSnaps(tomorrowData.snapshots);
      if (tomorrowData?.message) setTomorrowMsg(tomorrowData.message);
      if (seasonData?.season) setSeason(seasonData.season);
      if (seasonData?.edge_buckets) setEdgeBuckets(seasonData.edge_buckets);
      if (seasonData?.rolling_7day) setRolling(seasonData.rolling_7day);
      if (perfData?.daily) setDaily(perfData.daily);
      setLoading(false);
    });
  }, []);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 120_000); // 2min refresh
    return () => clearInterval(interval);
  }, [fetchData]);

  const handleExpandDay = (dt: string) => {
    if (expandedDay === dt) {
      setExpandedDay(null);
      setDayGames([]);
      return;
    }
    setExpandedDay(dt);
    fetch(`${API_BASE}/api/kenpom/edges?date=${dt}`)
      .then((r) => r.json())
      .then((data) => setDayGames([...(data.spread_edges || []), ...(data.total_edges || [])]))
      .catch(() => setDayGames([]));
  };

  // Apply filters to snapshots.
  function filterSnaps(snaps: Snapshot[]): Snapshot[] {
    return snaps.filter((s) => {
      if (fanmatchOnly && s.projection_source !== "kenpom_fanmatch") return false;
      // Keep if any edge meets the minimum threshold.
      const maxEdge = Math.max(
        Math.abs(s.spread_edge ?? 0),
        Math.abs(s.total_edge ?? 0),
        Math.abs((s.ml_edge ?? 0) * 10), // scale ML edge to be comparable
      );
      if (maxEdge < minEdge) return false;
      return true;
    });
  }

  const filteredToday = filterSnaps(todaySnaps);
  const filteredTomorrow = filterSnaps(tomorrowSnaps);

  // Merge rolling data for the chart.
  const chartData = rolling
    ? rolling.spread.map((s, i) => ({
        date: s.date.slice(5), // "MM-DD"
        Spread: s.accuracy,
        Total: rolling.total[i]?.accuracy ?? 0,
        ML: rolling.ml[i]?.accuracy ?? 0,
      }))
    : [];

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <p className="text-gray-500">Loading KenPom data...</p>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-7xl space-y-8 p-6">
      {/* SECTION 1: HEADER */}
      <div>
        <h1 className="text-2xl font-bold text-gray-100">KP Edge Finder</h1>
        <p className="mt-1 text-sm text-gray-500">
          KenPom projections vs Pinnacle sharp lines. Find where the model disagrees with the market.
        </p>
        {season && season.total_games_graded > 0 && (
          <div className="mt-3 flex flex-wrap items-center gap-4 rounded-xl bg-[#1c1c1e] px-4 py-2.5">
            <span className="text-xs font-semibold text-gray-300">Season:</span>
            {season.spread_record && (
              <span className="text-xs text-gray-400">
                Spread {season.spread_record} ({season.spread_units != null ? formatUnits(season.spread_units) : "\u2014"})
              </span>
            )}
            {season.spread_record && season.total_record && <span className="text-xs text-gray-600">|</span>}
            {season.total_record && (
              <span className="text-xs text-gray-400">
                Total {season.total_record} ({season.total_units != null ? formatUnits(season.total_units) : "\u2014"})
              </span>
            )}
            {season.total_record && season.ml_record && <span className="text-xs text-gray-600">|</span>}
            {season.ml_record && (
              <span className="text-xs text-gray-400">
                ML {season.ml_record} ({formatUnits(season.ml_units ?? 0)})
              </span>
            )}
            <span className="ml-auto text-[10px] text-gray-600">
              Games graded: {season.total_games_graded}
            </span>
          </div>
        )}
      </div>

      {/* FILTER CONTROLS */}
      <div className="flex flex-wrap items-center gap-4 rounded-xl bg-[#1c1c1e] px-4 py-3">
        <label className="flex cursor-pointer items-center gap-2">
          <div
            role="switch"
            aria-checked={fanmatchOnly}
            tabIndex={0}
            className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${fanmatchOnly ? "bg-emerald-600" : "bg-gray-600"}`}
            onClick={() => setFanmatchOnly(!fanmatchOnly)}
            onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") setFanmatchOnly(!fanmatchOnly); }}
          >
            <span className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform ${fanmatchOnly ? "translate-x-[18px]" : "translate-x-[3px]"}`} />
          </div>
          <span className="text-xs font-medium text-gray-300">Fanmatch Only</span>
        </label>
        <div className="flex items-center gap-2">
          <span className="text-xs text-gray-500">Min Edge:</span>
          <input
            type="range"
            min={0}
            max={5}
            step={0.5}
            value={minEdge}
            onChange={(e) => setMinEdge(parseFloat(e.target.value))}
            className="h-1.5 w-24 cursor-pointer appearance-none rounded-full bg-gray-700 accent-emerald-500"
          />
          <span className="w-10 text-xs font-mono text-gray-400">{minEdge.toFixed(1)}</span>
        </div>
        <span className="ml-auto text-[10px] text-gray-500">
          Showing {filteredToday.length} of {todaySnaps.length} today
          {tomorrowSnaps.length > 0 && ` · ${filteredTomorrow.length} of ${tomorrowSnaps.length} tomorrow`}
        </span>
      </div>

      {/* SECTION 2: TODAY'S EDGES */}
      <div>
        <h2 className="mb-3 text-lg font-semibold text-gray-200">Today&apos;s Edges</h2>
        <div className="grid gap-4 lg:grid-cols-2">
          <SpreadEdgesTable snapshots={filteredToday} label="Today" />
          <TotalEdgesTable snapshots={filteredToday} label="Today" />
        </div>
      </div>

      {/* SECTION 3: TOMORROW'S EDGES */}
      <div>
        <h2 className="mb-3 text-lg font-semibold text-gray-200">Tomorrow&apos;s Edges</h2>
        {filteredTomorrow.length > 0 ? (
          <div className="grid gap-4 lg:grid-cols-2">
            <SpreadEdgesTable snapshots={filteredTomorrow} label="Tomorrow" />
            <TotalEdgesTable snapshots={filteredTomorrow} label="Tomorrow" />
          </div>
        ) : (
          <div className="rounded-2xl bg-[#1c1c1e] p-6 text-center">
            <p className="text-sm text-gray-500">
              {tomorrowMsg || "Tomorrow's lines not yet available. Pinnacle typically opens lines 12 to 24 hours before tip."}
            </p>
          </div>
        )}
      </div>

      {/* SECTION 4: 30-DAY PERFORMANCE DASHBOARD */}
      {season && season.total_games_graded > 0 && (
        <div>
          <h2 className="mb-3 text-lg font-semibold text-gray-200">30-Day Performance</h2>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <StatCard
              title="Spread ATS"
              value={season.spread_record ?? "\u2014"}
              sub={`${formatPct(season.spread_pct)} | ${season.spread_units != null ? formatUnits(season.spread_units) : "\u2014"}`}
              accent={season.spread_pct >= 52.4 ? "green" : "red"}
            />
            <StatCard
              title="Totals O/U"
              value={season.total_record ?? "\u2014"}
              sub={`${formatPct(season.total_pct)} | ${season.total_units != null ? formatUnits(season.total_units) : "\u2014"}`}
              accent={season.total_pct >= 52.4 ? "green" : "red"}
            />
            <StatCard
              title="Moneyline"
              value={season.ml_record ?? "\u2014"}
              sub={`${formatPct(season.ml_pct)} | ${formatUnits(season.ml_units ?? 0)}`}
              accent={season.ml_pct >= 50 ? "green" : "red"}
            />
            <StatCard
              title="Games Graded"
              value={String(season.total_games_graded)}
              sub={`Last updated: ${season.last_updated ? new Date(season.last_updated).toLocaleTimeString() : "N/A"}`}
            />
          </div>

          {/* Rolling 7-day chart */}
          {chartData.length > 2 && (
            <div className="mt-4 rounded-2xl bg-[#1c1c1e] p-5">
              <h3 className="mb-3 text-sm font-semibold text-gray-300">Rolling 7-Day Accuracy</h3>
              <ResponsiveContainer width="100%" height={260}>
                <LineChart data={chartData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#333" />
                  <XAxis dataKey="date" tick={{ fontSize: 10, fill: "#888" }} />
                  <YAxis domain={[40, 70]} tick={{ fontSize: 10, fill: "#888" }} tickFormatter={(v: number) => `${v}%`} />
                  <Tooltip
                    contentStyle={{ backgroundColor: "#1c1c1e", border: "1px solid #333", borderRadius: 8 }}
                    formatter={(value: number | undefined) => value != null ? `${value.toFixed(1)}%` : ""}
                  />
                  <ReferenceLine y={52.4} stroke="#555" strokeDasharray="4 4" label={{ value: "52.4% BE", fill: "#666", fontSize: 10 }} />
                  <Line type="monotone" dataKey="Spread" stroke="#34d399" strokeWidth={2} dot={false} />
                  <Line type="monotone" dataKey="Total" stroke="#60a5fa" strokeWidth={2} dot={false} />
                  <Line type="monotone" dataKey="ML" stroke="#fbbf24" strokeWidth={2} dot={false} />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>
      )}

      {/* SECTION 5: EDGE ANALYSIS */}
      {edgeBuckets.length > 0 && (
        <div>
          <h2 className="mb-3 text-lg font-semibold text-gray-200">Edge Size vs Accuracy</h2>
          <div className="rounded-2xl bg-[#1c1c1e] p-5">
            <p className="mb-3 text-xs text-gray-500">Accuracy vs 52.4% breakeven — green above, red below</p>
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={edgeBuckets.map(b => ({
                ...b,
                spread_vs_be: +(b.spread_accuracy - 52.4).toFixed(1),
                total_vs_be: +(b.total_accuracy - 52.4).toFixed(1),
              }))}>
                <CartesianGrid strokeDasharray="3 3" stroke="#333" />
                <XAxis dataKey="bucket" tick={{ fontSize: 10, fill: "#888" }} label={{ value: "Edge (pts)", position: "insideBottom", offset: -2, fontSize: 10, fill: "#666" }} />
                <YAxis tick={{ fontSize: 10, fill: "#888" }} tickFormatter={(v: number) => `${v > 0 ? "+" : ""}${v}%`} />
                <Tooltip
                  contentStyle={{ backgroundColor: "#1c1c1e", border: "1px solid #333", borderRadius: 8 }}
                  formatter={(value: number | undefined) => value != null ? `${value > 0 ? "+" : ""}${value.toFixed(1)}% vs BE` : ""}
                />
                <ReferenceLine y={0} stroke="#555" strokeDasharray="4 4" label={{ value: "52.4% BE", fill: "#666", fontSize: 10 }} />
                <Bar dataKey="spread_vs_be" name="Spread vs BE">
                  {edgeBuckets.map((b, i) => (
                    <Cell key={i} fill={b.spread_accuracy >= 52.4 ? "#34d399" : "#f87171"} />
                  ))}
                </Bar>
                <Bar dataKey="total_vs_be" name="Total vs BE">
                  {edgeBuckets.map((b, i) => (
                    <Cell key={i} fill={b.total_accuracy >= 52.4 ? "#60a5fa" : "#f87171"} />
                  ))}
                </Bar>
                <Legend wrapperStyle={{ fontSize: 11 }} />
              </BarChart>
            </ResponsiveContainer>
            <div className="mt-2 overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead>
                  <tr className="border-b border-gray-800 text-[10px] font-medium uppercase tracking-wider text-gray-500">
                    <th className="px-2 py-1">Edge Bucket</th>
                    <th className="px-2 py-1 text-right">Games</th>
                    <th className="px-2 py-1 text-right">Spread %</th>
                    <th className="px-2 py-1 text-right">Spread U</th>
                    <th className="px-2 py-1 text-right">Total %</th>
                    <th className="px-2 py-1 text-right">Total U</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-800/50">
                  {edgeBuckets.map((b) => (
                    <tr key={b.bucket}>
                      <td className="px-2 py-1 text-gray-400">{b.bucket} pts</td>
                      <td className="px-2 py-1 text-right font-mono text-gray-500">{b.games}</td>
                      <td className="px-2 py-1 text-right font-mono text-gray-400">{formatPct(b.spread_accuracy)}</td>
                      <td className={`px-2 py-1 text-right font-mono ${(b.spread_units ?? 0) >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                        {formatUnits(b.spread_units ?? 0)}
                      </td>
                      <td className="px-2 py-1 text-right font-mono text-gray-400">{formatPct(b.total_accuracy)}</td>
                      <td className={`px-2 py-1 text-right font-mono ${(b.total_units ?? 0) >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                        {formatUnits(b.total_units ?? 0)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* SECTION 6: DAILY LOG */}
      {daily.length > 0 && (
        <div>
          <h2 className="mb-3 text-lg font-semibold text-gray-200">Daily Log</h2>
          <div className="rounded-2xl bg-[#1c1c1e] p-5">
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead>
                  <tr className="border-b border-gray-800 text-[10px] font-medium uppercase tracking-wider text-gray-500">
                    <th className="px-2 py-2">Date</th>
                    <th className="px-2 py-2 text-right">Games</th>
                    <th className="px-2 py-2 text-right">Spread</th>
                    <th className="px-2 py-2 text-right">Total</th>
                    <th className="px-2 py-2 text-right">ML</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-800/50">
                  {[...daily].reverse().map((d) => (
                    <>
                      <tr
                        key={d.date}
                        className="cursor-pointer hover:bg-[#2c2c2e]"
                        onClick={() => handleExpandDay(d.date)}
                      >
                        <td className="px-2 py-2 text-gray-300">
                          {d.date}
                          <span className="ml-1 text-gray-600">{expandedDay === d.date ? "\u25B2" : "\u25BC"}</span>
                        </td>
                        <td className="px-2 py-2 text-right font-mono text-gray-500">{d.games_graded}</td>
                        <td className="px-2 py-2 text-right font-mono text-gray-400">
                          {(d.spread_wins + d.spread_losses) > 0 ? (
                            <>
                              {d.spread_wins}-{d.spread_losses}
                              <span className={`ml-1 ${(d.spread_units ?? 0) >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                                {d.spread_units != null ? formatUnits(d.spread_units) : ""}
                              </span>
                            </>
                          ) : (
                            <span className="text-gray-600">{"\u2014"}</span>
                          )}
                        </td>
                        <td className="px-2 py-2 text-right font-mono text-gray-400">
                          {(d.total_wins + d.total_losses) > 0 ? (
                            <>
                              {d.total_wins}-{d.total_losses}
                              <span className={`ml-1 ${(d.total_units ?? 0) >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                                {d.total_units != null ? formatUnits(d.total_units) : ""}
                              </span>
                            </>
                          ) : (
                            <span className="text-gray-600">{"\u2014"}</span>
                          )}
                        </td>
                        <td className="px-2 py-2 text-right font-mono text-gray-400">
                          {(d.ml_wins + d.ml_losses) > 0 ? (
                            <>
                              {d.ml_wins}-{d.ml_losses}
                              <span className={`ml-1 ${(d.ml_units ?? 0) >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                                {formatUnits(d.ml_units ?? 0)}
                              </span>
                            </>
                          ) : (
                            <span className="text-gray-600">{"\u2014"}</span>
                          )}
                        </td>
                      </tr>
                      {expandedDay === d.date && dayGames.length > 0 && (
                        <tr key={`${d.date}-detail`}>
                          <td colSpan={5} className="bg-[#161618] px-4 py-3">
                            <table className="w-full text-[11px]">
                              <thead>
                                <tr className="text-[9px] uppercase text-gray-600">
                                  <th className="py-1 text-left">Game</th>
                                  <th className="py-1 text-right">Score</th>
                                  <th className="py-1 text-right">Spread Edge</th>
                                  <th className="py-1 text-right">ATS</th>
                                  <th className="py-1 text-right">Spr U</th>
                                  <th className="py-1 text-right">Total Edge</th>
                                  <th className="py-1 text-right">O/U</th>
                                  <th className="py-1 text-right">Tot U</th>
                                </tr>
                              </thead>
                              <tbody>
                                {/* Deduplicate by game_id */}
                                {Array.from(new Map(dayGames.map((g) => [g.game_id, g])).values()).map((g) => (
                                  <tr key={g.game_id} className="border-t border-gray-800/30">
                                    <td className="py-1 text-gray-400">{g.away_team} @ {g.home_team}</td>
                                    <td className="py-1 text-right font-mono text-gray-500">
                                      {g.result_home_score != null ? `${g.result_away_score}-${g.result_home_score}` : "\u2014"}
                                    </td>
                                    <td className={`py-1 text-right font-mono ${edgeColor(g.spread_edge)}`}>
                                      {formatEdge(g.spread_edge)}
                                    </td>
                                    <td className="py-1 text-right">
                                      {g.result_spread_correct === true && <span className="text-emerald-400">W</span>}
                                      {g.result_spread_correct === false && <span className="text-red-400">L</span>}
                                      {g.result_spread_correct == null && <span className="text-gray-600">\u2014</span>}
                                    </td>
                                    <td className={`py-1 text-right font-mono text-[10px] ${(g.spread_unit_result ?? 0) >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                                      {g.spread_unit_result != null ? formatUnits(g.spread_unit_result) : "\u2014"}
                                    </td>
                                    <td className={`py-1 text-right font-mono ${edgeColor(g.total_edge)}`}>
                                      {formatEdge(g.total_edge)}
                                    </td>
                                    <td className="py-1 text-right">
                                      {g.result_total_correct === true && <span className="text-emerald-400">W</span>}
                                      {g.result_total_correct === false && <span className="text-red-400">L</span>}
                                      {g.result_total_correct == null && <span className="text-gray-600">\u2014</span>}
                                    </td>
                                    <td className={`py-1 text-right font-mono text-[10px] ${(g.total_unit_result ?? 0) >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                                      {g.total_unit_result != null ? formatUnits(g.total_unit_result) : "\u2014"}
                                    </td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </td>
                        </tr>
                      )}
                    </>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
