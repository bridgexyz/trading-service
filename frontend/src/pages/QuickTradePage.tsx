import { useState, useRef, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api from "../api/client";
import type { SimplePairTrade, Credential } from "../types";

interface Market {
  market_id: number;
  symbol: string;
}

function AssetAutocomplete({
  label,
  value,
  onChange,
  markets,
  onSelect,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  markets: Market[];
  onSelect: (market: Market) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const filtered = value
    ? markets.filter((m) =>
        m.symbol.toLowerCase().includes(value.toLowerCase())
      )
    : markets;

  return (
    <div ref={ref} className="relative">
      <label className="text-[10px] text-text-secondary uppercase tracking-[0.12em] block mb-1.5 font-mono">
        {label}
      </label>
      <input
        type="text"
        value={value}
        onChange={(e) => {
          onChange(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        className="bg-surface-2/80 border border-border-default rounded-md px-3 py-2 text-[13px] font-mono text-text-primary placeholder:text-text-muted/50 hover:border-border-hover focus:border-accent/40 focus:outline-none transition-all w-36"
        placeholder="Search..."
      />
      {open && filtered.length > 0 && (
        <div className="absolute z-10 mt-1 w-52 max-h-48 overflow-auto bg-surface-1 border border-border-default rounded-lg shadow-2xl shadow-black/40">
          {filtered.map((m) => (
            <button
              key={m.market_id}
              type="button"
              onClick={() => {
                onSelect(m);
                setOpen(false);
              }}
              className="w-full text-left px-3.5 py-2 text-[13px] font-mono hover:bg-surface-2 transition-colors text-text-primary"
            >
              {m.symbol}{" "}
              <span className="text-text-muted text-[10px]">#{m.market_id}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function NumberField({
  label,
  value,
  onChange,
  step = 1,
  min,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  step?: number;
  min?: number;
}) {
  return (
    <div>
      <label className="text-[10px] text-text-secondary uppercase tracking-[0.12em] block mb-1.5 font-mono">
        {label}
      </label>
      <input
        type="number"
        step={step}
        min={min}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        onWheel={(e) => {
          e.preventDefault();
          const delta = e.deltaY < 0 ? step : -step;
          const newVal = Math.round((value + delta) * 1000) / 1000;
          onChange(min !== undefined ? Math.max(min, newVal) : newVal);
        }}
        className="bg-surface-2/80 border border-border-default rounded-md px-3 py-2 text-[13px] font-mono text-text-primary hover:border-border-hover focus:border-accent/40 focus:outline-none transition-all w-24"
      />
    </div>
  );
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
      <div className="bg-surface-1 border border-border-default rounded-lg p-5 space-y-5">
        <h2 className="text-[11px] font-mono uppercase tracking-[0.15em] text-text-secondary">New Trade</h2>

        {error && (
          <div className="text-xs text-red-400 bg-red-400/10 border border-red-400/20 rounded px-3 py-2">
            {error}
          </div>
        )}

        {/* Assets row */}
        <div className="flex flex-wrap items-end gap-4">
          <AssetAutocomplete
            label="Asset A"
            value={form.asset_a}
            onChange={(v) => set("asset_a", v)}
            markets={markets}
            onSelect={(m) => set("asset_a", m.symbol)}
          />
          <AssetAutocomplete
            label="Asset B"
            value={form.asset_b}
            onChange={(v) => set("asset_b", v)}
            markets={markets}
            onSelect={(m) => set("asset_b", m.symbol)}
          />
          <div>
            <label className="text-[10px] text-text-secondary uppercase tracking-[0.12em] block mb-1.5 font-mono">
              Direction
            </label>
            <select
              className="bg-surface-2/80 border border-border-default rounded-md px-3 py-2 text-[13px] font-mono text-text-primary hover:border-border-hover focus:border-accent/40 focus:outline-none transition-all"
              value={form.direction}
              onChange={(e) => set("direction", Number(e.target.value))}
            >
              <option value={1}>Long A / Short B</option>
              <option value={-1}>Long B / Short A</option>
            </select>
          </div>
        </div>

        {/* Parameters row */}
        <div className="flex flex-wrap items-end gap-4">
          <NumberField label="A/B Ratio" value={form.ratio} onChange={(v) => set("ratio", v)} step={0.1} min={0.1} />
          <NumberField label="Margin ($)" value={form.margin_usd} onChange={(v) => set("margin_usd", v)} step={10} min={1} />
          <NumberField label="Leverage" value={form.leverage} onChange={(v) => set("leverage", v)} step={1} min={1} />
          <NumberField label="Stop Loss %" value={form.stop_loss_pct} onChange={(v) => set("stop_loss_pct", v)} step={1} min={1} />
          <NumberField label="Take Profit %" value={form.take_profit_pct} onChange={(v) => set("take_profit_pct", v)} step={1} min={1} />
        </div>

        {/* Credential + submit */}
        <div className="flex items-end gap-4 pt-1">
          <div>
            <label className="text-[10px] text-text-secondary uppercase tracking-[0.12em] block mb-1.5 font-mono">
              Credential
            </label>
            <select
              className="bg-surface-2/80 border border-border-default rounded-md px-3 py-2 text-[13px] font-mono text-text-primary hover:border-border-hover focus:border-accent/40 focus:outline-none transition-all"
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
            className="px-5 py-2 bg-accent text-surface-0 rounded-md text-[12px] font-semibold tracking-wide hover:bg-accent/90 disabled:opacity-50 transition-all"
            disabled={!form.asset_a || !form.asset_b || form.asset_a === form.asset_b || openMut.isPending}
            onClick={() => openMut.mutate(form)}
          >
            {openMut.isPending ? "Opening..." : "Open Trade"}
          </button>
        </div>
      </div>

      {/* Open Trades */}
      <div className="bg-surface-1 border border-border-default rounded-lg p-4">
        <h2 className="text-[11px] font-mono uppercase tracking-[0.15em] text-text-secondary mb-3">
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
                    <td className="py-2 px-2 text-text-primary font-medium font-mono">
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
        <h2 className="text-[11px] font-mono uppercase tracking-[0.15em] text-text-secondary mb-3">
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
                    <td className="py-2 px-2 text-text-primary font-medium font-mono">
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
