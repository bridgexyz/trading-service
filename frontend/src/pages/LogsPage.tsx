import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import api from "../api/client";
import StatusBadge from "../components/StatusBadge";
import { formatDateTime } from "../utils/formatDate";
import type { JobLog, TradingPair } from "../types";

export default function LogsPage() {
  const [pairFilter, setPairFilter] = useState<string>("");
  const [statusFilter, setStatusFilter] = useState<string>("");

  const { data: pairs } = useQuery<TradingPair[]>({
    queryKey: ["pairs"],
    queryFn: () => api.get("/pairs").then((r) => r.data),
  });

  const params = new URLSearchParams({ limit: "100" });
  if (pairFilter) params.set("pair_id", pairFilter);
  if (statusFilter) params.set("status", statusFilter);

  const { data: logs } = useQuery<JobLog[]>({
    queryKey: ["logs", pairFilter, statusFilter],
    queryFn: () =>
      api.get(`/system/logs?${params}`).then((r) => r.data),
  });

  return (
    <div className="space-y-6 max-w-7xl">
      <div className="flex items-baseline gap-3">
        <h2 className="text-xl font-semibold tracking-tight">Job Logs</h2>
        <span className="text-[10px] font-mono text-text-secondary tracking-[0.2em]">HISTORY</span>
      </div>

      {/* Filters */}
      <div className="flex gap-2 flex-wrap">
        <select
          value={pairFilter}
          onChange={(e) => setPairFilter(e.target.value)}
          className="bg-surface-2 border border-border-default rounded-lg px-3 py-2 text-[12px] text-text-primary hover:border-border-hover transition-colors font-mono min-h-[44px] md:min-h-0"
        >
          <option value="">All Pairs</option>
          {pairs?.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="bg-surface-2 border border-border-default rounded-lg px-3 py-2 text-[12px] text-text-primary hover:border-border-hover transition-colors font-mono min-h-[44px] md:min-h-0"
        >
          <option value="">All Statuses</option>
          <option value="success">Success</option>
          <option value="error">Error</option>
          <option value="skipped">Skipped</option>
        </select>
      </div>

      {/* Mobile card layout */}
      <div className="md:hidden space-y-2">
        {logs?.map((l) => {
          const pairName =
            pairs?.find((p) => p.id === l.pair_id)?.name ?? `#${l.pair_id}`;
          return (
            <div
              key={l.id}
              className="bg-surface-1 border border-border-default rounded-xl p-4 space-y-2 card-hover"
            >
              <div className="flex items-center justify-between">
                <span className="text-[13px] font-medium text-text-primary">
                  {pairName}
                </span>
                <StatusBadge
                  status={l.status === "success" ? "success" : "error"}
                />
              </div>
              <div className="text-[11px] text-text-muted font-mono">
                {formatDateTime(l.timestamp)}
              </div>
              <div className="flex gap-4 text-xs">
                <span className="text-text-secondary">
                  Z: <span className="font-mono text-text-primary">{l.z_score?.toFixed(3) ?? "-"}</span>
                </span>
                <span className="text-text-secondary">
                  A: <span className="font-mono">{l.close_a != null ? (l.close_a < 0.01 ? l.close_a.toFixed(6) : l.close_a.toFixed(2)) : "-"}</span>
                </span>
                <span className="text-text-secondary">
                  B: <span className="font-mono">{l.close_b != null ? (l.close_b < 0.01 ? l.close_b.toFixed(6) : l.close_b.toFixed(2)) : "-"}</span>
                </span>
              </div>
              {l.action && (
                <div className="text-xs text-text-primary font-mono">{l.action}</div>
              )}
              {l.message && (
                <div className="text-xs text-text-muted truncate">
                  {l.message}
                </div>
              )}
            </div>
          );
        })}
        {(!logs || logs.length === 0) && (
          <p className="text-center text-text-muted py-12 text-sm">
            No logs found.
          </p>
        )}
      </div>

      {/* Desktop table */}
      <div className="hidden md:block bg-surface-1 border border-border-default rounded-xl overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-[13px]">
            <thead>
              <tr className="border-b border-border-default">
                <th className="text-left px-5 py-2.5 text-[10px] font-mono font-medium text-text-secondary uppercase tracking-[0.15em]">Time</th>
                <th className="text-left px-5 py-2.5 text-[10px] font-mono font-medium text-text-secondary uppercase tracking-[0.15em]">Pair</th>
                <th className="text-left px-5 py-2.5 text-[10px] font-mono font-medium text-text-secondary uppercase tracking-[0.15em]">Status</th>
                <th className="text-right px-5 py-2.5 text-[10px] font-mono font-medium text-text-secondary uppercase tracking-[0.15em]">Z-Score</th>
                <th className="text-right px-5 py-2.5 text-[10px] font-mono font-medium text-text-secondary uppercase tracking-[0.15em]">Close A</th>
                <th className="text-right px-5 py-2.5 text-[10px] font-mono font-medium text-text-secondary uppercase tracking-[0.15em]">Close B</th>
                <th className="text-left px-5 py-2.5 text-[10px] font-mono font-medium text-text-secondary uppercase tracking-[0.15em]">Action</th>
                <th className="text-left px-5 py-2.5 text-[10px] font-mono font-medium text-text-secondary uppercase tracking-[0.15em]">Message</th>
              </tr>
            </thead>
            <tbody>
              {logs?.map((l) => {
                const pairName =
                  pairs?.find((p) => p.id === l.pair_id)?.name ?? `#${l.pair_id}`;
                return (
                  <tr
                    key={l.id}
                    className="border-b border-border-default/50 hover:bg-surface-2/30"
                  >
                    <td className="px-5 py-2.5 text-text-secondary text-xs font-mono whitespace-nowrap">
                      {formatDateTime(l.timestamp)}
                    </td>
                    <td className="px-5 py-2.5 text-text-primary text-xs font-medium">
                      {pairName}
                    </td>
                    <td className="px-5 py-2.5">
                      <StatusBadge
                        status={l.status === "success" ? "success" : "error"}
                      />
                    </td>
                    <td className="px-5 py-2.5 text-right font-mono text-xs text-text-primary">
                      {l.z_score?.toFixed(3) ?? "-"}
                    </td>
                    <td className="px-5 py-2.5 text-right font-mono text-xs text-text-secondary">
                      {l.close_a != null
                        ? l.close_a < 0.01
                          ? l.close_a.toFixed(6)
                          : l.close_a.toFixed(2)
                        : "-"}
                    </td>
                    <td className="px-5 py-2.5 text-right font-mono text-xs text-text-secondary">
                      {l.close_b != null
                        ? l.close_b < 0.01
                          ? l.close_b.toFixed(6)
                          : l.close_b.toFixed(2)
                        : "-"}
                    </td>
                    <td className="px-5 py-2.5 text-text-primary text-xs font-mono">
                      {l.action ?? "-"}
                    </td>
                    <td className="px-5 py-2.5 text-text-muted text-xs truncate max-w-[250px]">
                      {l.message ?? ""}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {(!logs || logs.length === 0) && (
            <p className="text-center text-text-muted py-12 text-sm">
              No logs found.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
