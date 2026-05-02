import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api from "../api/client";
import type { SimplePairTrade, Credential } from "../types";

interface Market {
  market_id: number;
  symbol: string;
}

const defaults = {
  asset_a: "",
  asset_b: "",
  direction: 1,
  ratio: 1,
  margin_usd: 100,
  leverage: 5,
  stop_loss_pct: 15,
  take_profit_pct: 5,
  slice_chunks: 5,
  slice_delay_sec: 2,
  credential_id: null as number | null,
};

export default function QuickTradePage() {
  const qc = useQueryClient();
  const [form, setForm] = useState(defaults);
  const [error, setError] = useState("");

  const { data: markets = [] } = useQuery<Market[]>({
    queryKey: ["markets"],
    queryFn: () => api.get("/markets").then((r) => r.data),
  });

  const { data: credentials = [] } = useQuery<Credential[]>({
    queryKey: ["credentials"],
    queryFn: () => api.get("/credentials").then((r) => r.data),
  });

  const { data: trades = [] } = useQuery<SimplePairTrade[]>({
    queryKey: ["quick-trades"],
    queryFn: () => api.get("/quick-trades").then((r) => r.data),
    refetchInterval: 5000,
  });

  const openMut = useMutation({
    mutationFn: (data: typeof form) => api.post("/quick-trades", data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["quick-trades"] });
      setForm(defaults);
      setError("");
    },
    onError: (e: any) => setError(e.response?.data?.detail || "Failed to open trade"),
  });

  const closeMut = useMutation({
    mutationFn: (id: number) => api.post(`/quick-trades/${id}/close`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["quick-trades"] }),
    onError: (e: any) => setError(e.response?.data?.detail || "Failed to close trade"),
  });

  const set = (key: string, value: any) => setForm((f) => ({ ...f, [key]: value }));

  const openTrades = trades.filter((t) => t.status === "open");
  const closedTrades = trades.filter((t) => t.status === "closed" || t.status === "failed");

  return (
    <div className="space-y-6">
      <h1 className="text-lg font-semibold text-text-primary">Quick Trade</h1>

      {/* Open Trade Form */}
      <div className="bg-surface-1 border border-border-default rounded-lg p-4 space-y-4">
        <h2 className="text-sm font-medium text-text-primary">Open New Trade</h2>

        {error && (
          <div className="text-xs text-red-400 bg-red-400/10 border border-red-400/20 rounded px-3 py-2">
            {error}
          </div>
        )}

        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {/* Asset A */}
          <div>
            <label className="block text-[11px] text-text-muted mb-1">Asset A</label>
            <select
              className="w-full bg-surface-0 border border-border-default rounded px-2 py-1.5 text-xs text-text-primary"
              value={form.asset_a}
              onChange={(e) => set("asset_a", e.target.value)}
            >
              <option value="">Select...</option>
              {markets.map((m) => (
                <option key={m.market_id} value={m.symbol}>{m.symbol}</option>
              ))}
            </select>
          </div>

          {/* Asset B */}
          <div>
            <label className="block text-[11px] text-text-muted mb-1">Asset B</label>
            <select
              className="w-full bg-surface-0 border border-border-default rounded px-2 py-1.5 text-xs text-text-primary"
              value={form.asset_b}
              onChange={(e) => set("asset_b", e.target.value)}
            >
              <option value="">Select...</option>
              {markets.map((m) => (
                <option key={m.market_id} value={m.symbol}>{m.symbol}</option>
              ))}
            </select>
          </div>

          {/* Direction */}
          <div>
            <label className="block text-[11px] text-text-muted mb-1">Direction</label>
            <select
              className="w-full bg-surface-0 border border-border-default rounded px-2 py-1.5 text-xs text-text-primary"
              value={form.direction}
              onChange={(e) => set("direction", Number(e.target.value))}
            >
              <option value={1}>Long A / Short B</option>
              <option value={-1}>Long B / Short A</option>
            </select>
          </div>

          {/* Ratio */}
          <div>
            <label className="block text-[11px] text-text-muted mb-1">A/B Ratio</label>
            <input
              type="number"
              step="0.1"
              className="w-full bg-surface-0 border border-border-default rounded px-2 py-1.5 text-xs text-text-primary"
              value={form.ratio}
              onChange={(e) => set("ratio", Number(e.target.value))}
            />
          </div>

          {/* Margin */}
          <div>
            <label className="block text-[11px] text-text-muted mb-1">Margin ($)</label>
            <input
              type="number"
              step="10"
              className="w-full bg-surface-0 border border-border-default rounded px-2 py-1.5 text-xs text-text-primary"
              value={form.margin_usd}
              onChange={(e) => set("margin_usd", Number(e.target.value))}
            />
          </div>

          {/* Leverage */}
          <div>
            <label className="block text-[11px] text-text-muted mb-1">Leverage</label>
            <input
              type="number"
              step="1"
              className="w-full bg-surface-0 border border-border-default rounded px-2 py-1.5 text-xs text-text-primary"
              value={form.leverage}
              onChange={(e) => set("leverage", Number(e.target.value))}
            />
          </div>

          {/* Stop Loss */}
          <div>
            <label className="block text-[11px] text-text-muted mb-1">Stop Loss %</label>
            <input
              type="number"
              step="1"
              className="w-full bg-surface-0 border border-border-default rounded px-2 py-1.5 text-xs text-text-primary"
              value={form.stop_loss_pct}
              onChange={(e) => set("stop_loss_pct", Number(e.target.value))}
            />
          </div>

          {/* Take Profit */}
          <div>
            <label className="block text-[11px] text-text-muted mb-1">Take Profit %</label>
            <input
              type="number"
              step="1"
              className="w-full bg-surface-0 border border-border-default rounded px-2 py-1.5 text-xs text-text-primary"
              value={form.take_profit_pct}
              onChange={(e) => set("take_profit_pct", Number(e.target.value))}
            />
          </div>
        </div>

        {/* Credential selector + submit */}
        <div className="flex items-end gap-3">
          <div className="flex-1 max-w-[200px]">
            <label className="block text-[11px] text-text-muted mb-1">Credential</label>
            <select
              className="w-full bg-surface-0 border border-border-default rounded px-2 py-1.5 text-xs text-text-primary"
              value={form.credential_id ?? ""}
              onChange={(e) => set("credential_id", e.target.value ? Number(e.target.value) : null)}
            >
              <option value="">Default</option>
              {credentials.map((c) => (
                <option key={c.id} value={c.id}>{c.name}</option>
              ))}
            </select>
          </div>
          <button
            className="px-4 py-1.5 bg-accent text-surface-0 rounded text-xs font-medium hover:bg-accent/90 disabled:opacity-50"
            disabled={!form.asset_a || !form.asset_b || form.asset_a === form.asset_b || openMut.isPending}
            onClick={() => openMut.mutate(form)}
          >
            {openMut.isPending ? "Opening..." : "Open Trade"}
          </button>
        </div>
      </div>

      {/* Open Trades */}
      <div className="bg-surface-1 border border-border-default rounded-lg p-4">
        <h2 className="text-sm font-medium text-text-primary mb-3">
          Open Trades ({openTrades.length})
        </h2>
        {openTrades.length === 0 ? (
          <p className="text-xs text-text-muted">No open trades</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-text-muted border-b border-border-default">
                  <th className="text-left py-2 px-2">Pair</th>
                  <th className="text-left py-2 px-2">Direction</th>
                  <th className="text-right py-2 px-2">Margin</th>
                  <th className="text-right py-2 px-2">Leverage</th>
                  <th className="text-right py-2 px-2">SL / TP</th>
                  <th className="text-right py-2 px-2">Notional</th>
                  <th className="text-left py-2 px-2">Opened</th>
                  <th className="text-right py-2 px-2"></th>
                </tr>
              </thead>
              <tbody>
                {openTrades.map((t) => (
                  <tr key={t.id} className="border-b border-border-default/50 hover:bg-surface-0/50">
                    <td className="py-2 px-2 text-text-primary font-medium">
                      {t.asset_a}/{t.asset_b}
                    </td>
                    <td className="py-2 px-2">
                      <span className={t.direction === 1 ? "text-green-400" : "text-red-400"}>
                        {t.direction === 1 ? `L ${t.asset_a} / S ${t.asset_b}` : `L ${t.asset_b} / S ${t.asset_a}`}
                      </span>
                    </td>
                    <td className="py-2 px-2 text-right text-text-primary">${t.margin_usd}</td>
                    <td className="py-2 px-2 text-right text-text-primary">{t.leverage}x</td>
                    <td className="py-2 px-2 text-right text-text-muted">
                      -{t.stop_loss_pct}% / +{t.take_profit_pct}%
                    </td>
                    <td className="py-2 px-2 text-right text-text-primary">
                      ${t.entry_notional?.toFixed(0) ?? "—"}
                    </td>
                    <td className="py-2 px-2 text-text-muted">
                      {t.entry_time ? new Date(t.entry_time).toLocaleString() : "—"}
                    </td>
                    <td className="py-2 px-2 text-right">
                      <button
                        className="px-2 py-1 bg-red-500/10 text-red-400 border border-red-500/20 rounded text-[11px] hover:bg-red-500/20 disabled:opacity-50"
                        disabled={closeMut.isPending}
                        onClick={() => closeMut.mutate(t.id)}
                      >
                        Close
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Trade History */}
      <div className="bg-surface-1 border border-border-default rounded-lg p-4">
        <h2 className="text-sm font-medium text-text-primary mb-3">
          History ({closedTrades.length})
        </h2>
        {closedTrades.length === 0 ? (
          <p className="text-xs text-text-muted">No closed trades yet</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-text-muted border-b border-border-default">
                  <th className="text-left py-2 px-2">Pair</th>
                  <th className="text-left py-2 px-2">Direction</th>
                  <th className="text-right py-2 px-2">Margin</th>
                  <th className="text-right py-2 px-2">PnL</th>
                  <th className="text-right py-2 px-2">PnL %</th>
                  <th className="text-left py-2 px-2">Exit Reason</th>
                  <th className="text-left py-2 px-2">Closed</th>
                </tr>
              </thead>
              <tbody>
                {closedTrades.map((t) => (
                  <tr key={t.id} className="border-b border-border-default/50 hover:bg-surface-0/50">
                    <td className="py-2 px-2 text-text-primary font-medium">
                      {t.asset_a}/{t.asset_b}
                    </td>
                    <td className="py-2 px-2">
                      <span className={t.direction === 1 ? "text-green-400" : "text-red-400"}>
                        {t.direction === 1 ? `L ${t.asset_a} / S ${t.asset_b}` : `L ${t.asset_b} / S ${t.asset_a}`}
                      </span>
                    </td>
                    <td className="py-2 px-2 text-right text-text-primary">${t.margin_usd}</td>
                    <td className={`py-2 px-2 text-right font-medium ${(t.pnl ?? 0) >= 0 ? "text-green-400" : "text-red-400"}`}>
                      {t.pnl != null ? `$${t.pnl.toFixed(2)}` : "—"}
                    </td>
                    <td className={`py-2 px-2 text-right ${(t.pnl_pct ?? 0) >= 0 ? "text-green-400" : "text-red-400"}`}>
                      {t.pnl_pct != null ? `${t.pnl_pct.toFixed(2)}%` : "—"}
                    </td>
                    <td className="py-2 px-2 text-text-muted capitalize">
                      {t.exit_reason?.replace("_", " ") ?? t.status}
                    </td>
                    <td className="py-2 px-2 text-text-muted">
                      {t.exit_time ? new Date(t.exit_time).toLocaleString() : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
