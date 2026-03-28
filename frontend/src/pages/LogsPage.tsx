import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import api from "../api/client";
import StatusBadge from "../components/StatusBadge";
import { formatDateTime } from "../utils/formatDate";
import { fmtPrice } from "../utils/formatNumber";
import type { JobLog, TradingPair } from "../types";

const PAGE_SIZE = 50;

export default function LogsPage() {
  const [pairFilter, setPairFilter] = useState<string>("");
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [actionFilter, setActionFilter] = useState<string>("");
  const [zMin, setZMin] = useState("");
  const [zMax, setZMax] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [page, setPage] = useState(0);

  const { data: pairs } = useQuery<TradingPair[]>({
    queryKey: ["pairs"],
    queryFn: () => api.get("/pairs").then((r) => r.data),
  });

  const { data: actions } = useQuery<string[]>({
    queryKey: ["log-actions"],
    queryFn: () => api.get("/system/logs/actions").then((r) => r.data),
  });

  const params = new URLSearchParams({
    limit: String(PAGE_SIZE),
    offset: String(page * PAGE_SIZE),
  });
  if (pairFilter) params.set("pair_id", pairFilter);
  if (statusFilter) params.set("status", statusFilter);
  if (actionFilter) params.set("action", actionFilter);
  if (zMin) params.set("z_min", zMin);
  if (zMax) params.set("z_max", zMax);
  if (dateFrom) params.set("date_from", dateFrom);
  if (dateTo) params.set("date_to", dateTo);

  const { data } = useQuery<{ items: JobLog[]; total: number }>({
    queryKey: ["logs", pairFilter, statusFilter, actionFilter, zMin, zMax, dateFrom, dateTo, page],
    queryFn: () =>
      api.get(`/system/logs?${params}`).then((r) => r.data),
  });

  const logs = data?.items;
  const total = data?.total ?? 0;
  const totalPages = Math.ceil(total / PAGE_SIZE);
  const showFrom = total === 0 ? 0 : page * PAGE_SIZE + 1;
  const showTo = Math.min((page + 1) * PAGE_SIZE, total);

  const resetPage = () => setPage(0);

  const inputCls =
    "bg-surface-2 border border-border-default rounded-md px-3 py-2 text-[12px] text-text-primary hover:border-border-hover transition-colors font-mono min-h-[44px] md:min-h-0";
  const selectCls = inputCls;

  const hasAdvancedFilters = actionFilter || zMin || zMax || dateFrom || dateTo;

  return (
    <div className="space-y-6 max-w-7xl">
      <div className="flex items-baseline gap-3">
        <h2 className="text-xl font-semibold tracking-tight">Job Logs</h2>
        <span className="text-[10px] font-mono text-text-secondary tracking-[0.2em]">HISTORY</span>
      </div>

      {/* Filters */}
      <div className="space-y-2">
        <div className="flex gap-2 flex-wrap">
          <select
            value={pairFilter}
            onChange={(e) => { setPairFilter(e.target.value); resetPage(); }}
            className={selectCls}
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
            onChange={(e) => { setStatusFilter(e.target.value); resetPage(); }}
            className={selectCls}
          >
            <option value="">All Statuses</option>
            <option value="success">Success</option>
            <option value="error">Error</option>
            <option value="skipped">Skipped</option>
          </select>
          <select
            value={actionFilter}
            onChange={(e) => { setActionFilter(e.target.value); resetPage(); }}
            className={selectCls}
          >
            <option value="">All Actions</option>
            {actions?.map((a) => (
              <option key={a} value={a}>
                {a}
              </option>
            ))}
          </select>

          <input
            type="text"
            inputMode="decimal"
            placeholder="|Z| Min"
            value={zMin}
            onChange={(e) => { setZMin(e.target.value); resetPage(); }}
            className={`${inputCls} w-20`}
          />
          <input
            type="text"
            inputMode="decimal"
            placeholder="|Z| Max"
            value={zMax}
            onChange={(e) => { setZMax(e.target.value); resetPage(); }}
            className={`${inputCls} w-20`}
          />

          <input
            type="date"
            value={dateFrom}
            onChange={(e) => { setDateFrom(e.target.value); resetPage(); }}
            className={inputCls}
          />
          <input
            type="date"
            value={dateTo}
            onChange={(e) => { setDateTo(e.target.value); resetPage(); }}
            className={inputCls}
          />

          {hasAdvancedFilters && (
            <button
              onClick={() => { setActionFilter(""); setZMin(""); setZMax(""); setDateFrom(""); setDateTo(""); resetPage(); }}
              className="px-3 py-2 text-[12px] font-mono text-text-secondary hover:text-text-primary transition-colors"
            >
              Clear Filters
            </button>
          )}
        </div>
      </div>

      {/* Mobile card layout */}
      <div className="md:hidden space-y-2">
        {logs?.map((l) => {
          const pairName =
            pairs?.find((p) => p.id === l.pair_id)?.name ?? `#${l.pair_id}`;
          return (
            <div
              key={l.id}
              className="bg-surface-1 border border-border-default rounded-lg p-4 space-y-2 card-hover"
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
                  A: <span className="font-mono">{l.close_a != null ? fmtPrice(l.close_a) : "-"}</span>
                </span>
                <span className="text-text-secondary">
                  B: <span className="font-mono">{l.close_b != null ? fmtPrice(l.close_b) : "-"}</span>
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
      <div className="hidden md:block bg-surface-1 border border-border-default rounded-lg overflow-hidden">
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
                      {l.close_a != null ? fmtPrice(l.close_a) : "-"}
                    </td>
                    <td className="px-5 py-2.5 text-right font-mono text-xs text-text-secondary">
                      {l.close_b != null ? fmtPrice(l.close_b) : "-"}
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

      {/* Pagination */}
      {totalPages > 0 && (
        <div className="flex items-center justify-between text-[12px] font-mono text-text-secondary">
          <span>
            Showing {showFrom}–{showTo} of {total}
          </span>
          <div className="flex items-center gap-3">
            <button
              disabled={page === 0}
              onClick={() => setPage((p) => p - 1)}
              className="px-3 py-1.5 rounded-md border border-border-default bg-surface-2 hover:border-border-hover disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              Previous
            </button>
            <span className="text-text-primary">
              Page {page + 1} of {totalPages}
            </span>
            <button
              disabled={page >= totalPages - 1}
              onClick={() => setPage((p) => p + 1)}
              className="px-3 py-1.5 rounded-md border border-border-default bg-surface-2 hover:border-border-hover disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              Next
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
