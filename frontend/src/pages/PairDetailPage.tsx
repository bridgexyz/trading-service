import { useParams, Link } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import api from "../api/client";
import StatCard from "../components/StatCard";
import StatusBadge from "../components/StatusBadge";
import { formatDateTime } from "../utils/formatDate";
import type { TradingPair, Trade, JobLog } from "../types";

export default function PairDetailPage() {
  const { id } = useParams<{ id: string }>();
  const qc = useQueryClient();

  const { data: pair } = useQuery<TradingPair>({
    queryKey: ["pair", id],
    queryFn: () => api.get(`/pairs/${id}`).then((r) => r.data),
  });

  const { data: trades } = useQuery<Trade[]>({
    queryKey: ["trades", id],
    queryFn: () =>
      api.get(`/trades?pair_id=${id}&limit=50`).then((r) => r.data),
  });

  const { data: equity } = useQuery({
    queryKey: ["equity", id],
    queryFn: () =>
      api.get(`/dashboard/equity/${id}`).then((r) => r.data),
  });

  const { data: logs } = useQuery<JobLog[]>({
    queryKey: ["logs", id],
    queryFn: () =>
      api.get(`/system/logs?pair_id=${id}&limit=20`).then((r) => r.data),
  });

  const triggerMut = useMutation({
    mutationFn: () => api.post(`/system/trigger/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["logs", id] });
      qc.invalidateQueries({ queryKey: ["pair", id] });
    },
  });

  const toggleMut = useMutation({
    mutationFn: () => api.post(`/pairs/${id}/toggle`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["pair", id] }),
  });

  if (!pair)
    return (
      <div className="flex items-center justify-center h-40 text-text-muted text-sm font-mono">
        Loading...
      </div>
    );

  const totalPnl = trades?.reduce((sum, t) => sum + t.pnl, 0) ?? 0;
  const wins = trades?.filter((t) => t.pnl > 0).length ?? 0;
  const winRate = trades?.length
    ? ((wins / trades.length) * 100).toFixed(1)
    : "0";

  return (
    <div className="space-y-6 max-w-7xl">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <Link
            to="/pairs"
            className="w-8 h-8 rounded-lg bg-surface-2 border border-border-default flex items-center justify-center text-text-muted hover:text-text-primary hover:border-border-hover transition-all"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M15 18l-6-6 6-6" />
            </svg>
          </Link>
          <div>
            <div className="flex items-center gap-2.5">
              <h2 className="text-xl font-semibold tracking-tight">{pair.name}</h2>
              <StatusBadge status={pair.is_enabled ? "active" : "paused"} />
            </div>
            <span className="text-[10px] font-mono text-text-muted tracking-[0.2em]">
              {pair.asset_a}/{pair.asset_b}
            </span>
          </div>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => triggerMut.mutate()}
            disabled={triggerMut.isPending}
            className="bg-surface-2 hover:bg-surface-3 border border-border-default hover:border-border-hover text-text-secondary hover:text-text-primary px-3.5 py-2 rounded-lg text-[12px] font-medium font-mono tracking-wide transition-all disabled:opacity-40 min-h-[44px] sm:min-h-0"
          >
            {triggerMut.isPending ? "RUNNING..." : "TRIGGER"}
          </button>
          <button
            onClick={() => toggleMut.mutate()}
            className={`border px-3.5 py-2 rounded-lg text-[12px] font-medium font-mono tracking-wide transition-all min-h-[44px] sm:min-h-0 ${
              pair.is_enabled
                ? "bg-warning/8 border-warning/20 text-warning hover:bg-warning/15 hover:border-warning/40"
                : "bg-accent/8 border-accent/20 text-accent hover:bg-accent/15 hover:border-accent/40"
            }`}
          >
            {pair.is_enabled ? "PAUSE" : "RESUME"}
          </button>
        </div>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
        <StatCard label="Equity" value={`$${pair.current_equity.toFixed(0)}`} />
        <StatCard
          label="Total PnL"
          value={`$${totalPnl.toFixed(2)}`}
          color={totalPnl >= 0 ? "text-accent" : "text-negative"}
        />
        <StatCard label="Trades" value={trades?.length ?? 0} />
        <StatCard
          label="Win Rate"
          value={`${winRate}%`}
          color={Number(winRate) >= 50 ? "text-accent" : "text-text-secondary"}
        />
        <StatCard label="Leverage" value={`${pair.leverage}x`} />
        <StatCard label="Interval" value={pair.schedule_interval} />
      </div>

      {/* Equity chart */}
      {equity && equity.length > 0 && (
        <div className="bg-surface-1 border border-border-default rounded-xl p-5 card-hover">
          <h3 className="text-[10px] font-mono font-medium text-text-muted uppercase tracking-[0.15em] mb-4">
            Equity Curve
          </h3>
          <ResponsiveContainer width="100%" height={240}>
            <AreaChart data={equity}>
              <defs>
                <linearGradient id="equityGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="var(--color-accent)" stopOpacity={0.15} />
                  <stop offset="100%" stopColor="var(--color-accent)" stopOpacity={0} />
                </linearGradient>
              </defs>
              <XAxis
                dataKey="timestamp"
                tick={{ fontSize: 10, fill: "var(--color-text-muted)" }}
                tickFormatter={(v: string) => v.slice(5, 16)}
                axisLine={{ stroke: "var(--color-border-default)" }}
                tickLine={false}
              />
              <YAxis
                tick={{ fontSize: 10, fill: "var(--color-text-muted)" }}
                axisLine={false}
                tickLine={false}
              />
              <Tooltip
                contentStyle={{
                  backgroundColor: "var(--color-surface-2)",
                  border: "1px solid var(--color-border-default)",
                  borderRadius: "10px",
                  fontSize: "12px",
                  fontFamily: "'IBM Plex Mono', monospace",
                }}
                labelStyle={{ color: "var(--color-text-muted)" }}
                itemStyle={{ color: "var(--color-accent)" }}
              />
              <Area
                type="monotone"
                dataKey="equity"
                stroke="var(--color-accent)"
                fill="url(#equityGrad)"
                strokeWidth={1.5}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Trade history */}
      <div className="bg-surface-1 border border-border-default rounded-xl overflow-hidden">
        <div className="px-5 py-3.5 border-b border-border-default">
          <h3 className="text-[10px] font-mono font-medium text-text-muted uppercase tracking-[0.15em]">
            Trade History
          </h3>
        </div>

        {/* Mobile cards */}
        <div className="md:hidden divide-y divide-border-default/50">
          {trades?.map((t) => (
            <div key={t.id} className="px-4 py-3 space-y-1.5">
              <div className="flex items-center justify-between">
                <span
                  className={`text-[11px] font-mono font-medium px-2 py-0.5 rounded-full border ${
                    t.direction.includes("Long A")
                      ? "bg-accent/8 border-accent/20 text-accent"
                      : "bg-negative/8 border-negative/20 text-negative"
                  }`}
                >
                  {t.direction}
                </span>
                <span
                  className={`text-[13px] font-mono font-medium ${
                    t.pnl >= 0 ? "text-accent" : "text-negative"
                  }`}
                >
                  ${t.pnl.toFixed(2)}
                </span>
              </div>
              <div className="flex items-center justify-between text-[11px]">
                <span className="text-text-muted font-mono">{formatDateTime(t.exit_time)}</span>
                <span className={`font-mono ${t.pnl_pct >= 0 ? "text-accent" : "text-negative"}`}>
                  {t.pnl_pct.toFixed(2)}%
                </span>
              </div>
              {t.exit_reason && (
                <div className="text-[11px] text-text-secondary">{t.exit_reason}</div>
              )}
            </div>
          ))}
          {(!trades || trades.length === 0) && (
            <p className="text-center text-text-muted py-12 text-sm">No trades yet.</p>
          )}
        </div>

        {/* Desktop table */}
        <div className="hidden md:block overflow-x-auto">
          <table className="w-full text-[13px]">
            <thead>
              <tr className="border-b border-border-default">
                <th className="text-left px-5 py-2.5 text-[10px] font-mono font-medium text-text-muted uppercase tracking-[0.15em]">Exit Date</th>
                <th className="text-left px-5 py-2.5 text-[10px] font-mono font-medium text-text-muted uppercase tracking-[0.15em]">Direction</th>
                <th className="text-right px-5 py-2.5 text-[10px] font-mono font-medium text-text-muted uppercase tracking-[0.15em]">PnL</th>
                <th className="text-right px-5 py-2.5 text-[10px] font-mono font-medium text-text-muted uppercase tracking-[0.15em]">PnL %</th>
                <th className="text-left px-5 py-2.5 text-[10px] font-mono font-medium text-text-muted uppercase tracking-[0.15em]">Reason</th>
              </tr>
            </thead>
            <tbody>
              {trades?.map((t) => (
                <tr
                  key={t.id}
                  className="border-b border-border-default/50 hover:bg-surface-2/30"
                >
                  <td className="px-5 py-2.5 text-text-secondary text-xs font-mono whitespace-nowrap">
                    {formatDateTime(t.exit_time)}
                  </td>
                  <td className="px-5 py-2.5">
                    <span
                      className={`text-[10px] font-mono font-medium px-2 py-0.5 rounded-full border ${
                        t.direction.includes("Long A")
                          ? "bg-accent/8 border-accent/20 text-accent"
                          : "bg-negative/8 border-negative/20 text-negative"
                      }`}
                    >
                      {t.direction}
                    </span>
                  </td>
                  <td
                    className={`px-5 py-2.5 text-right font-mono text-xs ${
                      t.pnl >= 0 ? "text-accent" : "text-negative"
                    }`}
                  >
                    ${t.pnl.toFixed(2)}
                  </td>
                  <td
                    className={`px-5 py-2.5 text-right font-mono text-xs ${
                      t.pnl_pct >= 0 ? "text-accent" : "text-negative"
                    }`}
                  >
                    {t.pnl_pct.toFixed(2)}%
                  </td>
                  <td className="px-5 py-2.5 text-text-secondary text-xs">
                    {t.exit_reason}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {(!trades || trades.length === 0) && (
            <p className="text-center text-text-muted py-12 text-sm">
              No trades yet.
            </p>
          )}
        </div>
      </div>

      {/* Job logs */}
      <div className="bg-surface-1 border border-border-default rounded-xl overflow-hidden">
        <div className="px-5 py-3.5 border-b border-border-default">
          <h3 className="text-[10px] font-mono font-medium text-text-muted uppercase tracking-[0.15em]">
            Recent Job Logs
          </h3>
        </div>

        {/* Mobile cards */}
        <div className="md:hidden divide-y divide-border-default/50">
          {logs?.map((l) => (
            <div key={l.id} className="px-4 py-3 space-y-1.5">
              <div className="flex items-center justify-between">
                <StatusBadge status={l.status === "success" ? "active" : "error"} />
                <span className="text-[11px] text-text-muted font-mono">{formatDateTime(l.timestamp)}</span>
              </div>
              <div className="flex gap-3 text-[11px]">
                <span className="text-text-secondary">
                  Z: <span className="font-mono text-text-primary">{l.z_score?.toFixed(3) ?? "-"}</span>
                </span>
                {l.action && (
                  <span className="font-mono text-text-primary">{l.action}</span>
                )}
              </div>
              {l.message && (
                <div className="text-[11px] text-text-muted truncate">{l.message}</div>
              )}
            </div>
          ))}
          {(!logs || logs.length === 0) && (
            <p className="text-center text-text-muted py-12 text-sm">No logs yet.</p>
          )}
        </div>

        {/* Desktop table */}
        <div className="hidden md:block overflow-x-auto">
          <table className="w-full text-[13px]">
            <thead>
              <tr className="border-b border-border-default">
                <th className="text-left px-5 py-2.5 text-[10px] font-mono font-medium text-text-muted uppercase tracking-[0.15em]">Time</th>
                <th className="text-left px-5 py-2.5 text-[10px] font-mono font-medium text-text-muted uppercase tracking-[0.15em]">Status</th>
                <th className="text-right px-5 py-2.5 text-[10px] font-mono font-medium text-text-muted uppercase tracking-[0.15em]">Z-Score</th>
                <th className="text-left px-5 py-2.5 text-[10px] font-mono font-medium text-text-muted uppercase tracking-[0.15em]">Action</th>
                <th className="text-left px-5 py-2.5 text-[10px] font-mono font-medium text-text-muted uppercase tracking-[0.15em]">Message</th>
              </tr>
            </thead>
            <tbody>
              {logs?.map((l) => (
                <tr
                  key={l.id}
                  className="border-b border-border-default/50 hover:bg-surface-2/30"
                >
                  <td className="px-5 py-2.5 text-text-secondary text-xs font-mono whitespace-nowrap">
                    {formatDateTime(l.timestamp)}
                  </td>
                  <td className="px-5 py-2.5">
                    <StatusBadge status={l.status === "success" ? "active" : "error"} />
                  </td>
                  <td className="px-5 py-2.5 text-right font-mono text-xs text-text-primary">
                    {l.z_score?.toFixed(3) ?? "-"}
                  </td>
                  <td className="px-5 py-2.5 text-text-primary text-xs font-mono">
                    {l.action ?? "-"}
                  </td>
                  <td className="px-5 py-2.5 text-text-muted text-xs truncate max-w-[250px]">
                    {l.message ?? ""}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {(!logs || logs.length === 0) && (
            <p className="text-center text-text-muted py-12 text-sm">
              No logs yet.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
