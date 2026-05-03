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
  min,
}: {
  label: string;
  value: number | "";
  onChange: (v: number | "") => void;
  step?: number;
  min?: number;
}) {
  const [displayValue, setDisplayValue] = useState(String(value));

  useEffect(() => {
    setDisplayValue(String(value));
  }, [value]);

  return (
    <div>
      <label className="text-[10px] text-text-secondary uppercase tracking-[0.12em] block mb-1.5 font-mono">
        {label}
      </label>
      <input
        type="text"
        inputMode="decimal"
        value={displayValue}
        onChange={(e) => {
          const next = e.target.value;
          if (!/^\d*\.?\d*$/.test(next)) return;

          setDisplayValue(next);
          if (next === "") {
            onChange("");
            return;
          }
          if (next === ".") return;

          const parsed = Number(next);
          if (!Number.isFinite(parsed)) return;
          onChange(parsed);
        }}
        onBlur={() => {
          if (displayValue === "" || displayValue === ".") return;
          const parsed = Number(displayValue);
          if (!Number.isFinite(parsed)) return;
          const normalized = min !== undefined ? Math.max(min, parsed) : parsed;
          setDisplayValue(String(normalized));
          onChange(normalized);
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
  order_mode: "limit" as "market" | "sliced" | "limit",
  slice_chunks: 5,
  slice_delay_sec: 2,
  credential_id: null as number | null,
};

type QuickTradeUpdate = {
  stop_loss_pct?: number;
  take_profit_pct?: number;
};

const hasNumber = (value: number | ""): value is number => value !== "";

export default function QuickTradePage() {
  const qc = useQueryClient();
  const [form, setForm] = useState(defaults);
  const [editingTradeId, setEditingTradeId] = useState<number | null>(null);
  const [editForm, setEditForm] = useState<{
    stop_loss_pct: number | "";
    take_profit_pct: number | "";
  }>({ stop_loss_pct: 0, take_profit_pct: 0 });
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

  const updateMut = useMutation({
    mutationFn: ({ id, data }: { id: number; data: QuickTradeUpdate }) =>
      api.patch(`/quick-trades/${id}`, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["quick-trades"] });
      setEditingTradeId(null);
      setError("");
    },
    onError: (e: any) => setError(e.response?.data?.detail || "Failed to update trade"),
  });

  const set = (key: string, value: any) => setForm((f) => ({ ...f, [key]: value }));
  const startEdit = (trade: SimplePairTrade) => {
    setEditingTradeId(trade.id);
    setEditForm({
      stop_loss_pct: trade.stop_loss_pct,
      take_profit_pct: trade.take_profit_pct,
    });
    setError("");
  };
  const cancelEdit = () => {
    setEditingTradeId(null);
    setError("");
  };
  const saveEdit = (id: number) => {
    if (!hasNumber(editForm.stop_loss_pct) || !hasNumber(editForm.take_profit_pct)) return;
    updateMut.mutate({
      id,
      data: {
        stop_loss_pct: editForm.stop_loss_pct,
        take_profit_pct: editForm.take_profit_pct,
      },
    });
  };

  const openTrades = trades.filter((t) => t.status === "open");
  const closedTrades = trades.filter((t) => t.status === "closed" || t.status === "failed");
  const usesChunkControls = form.order_mode === "sliced" || form.order_mode === "limit";
  const canOpenTrade =
    !!form.asset_a &&
    !!form.asset_b &&
    form.asset_a !== form.asset_b &&
    hasNumber(form.ratio) &&
    hasNumber(form.margin_usd) &&
    hasNumber(form.leverage) &&
    hasNumber(form.stop_loss_pct) &&
    hasNumber(form.take_profit_pct) &&
    (!usesChunkControls || (hasNumber(form.slice_chunks) && hasNumber(form.slice_delay_sec)));
  const openTrade = () => {
    openMut.mutate({
      ...form,
      slice_chunks: hasNumber(form.slice_chunks) ? form.slice_chunks : defaults.slice_chunks,
      slice_delay_sec: hasNumber(form.slice_delay_sec) ? form.slice_delay_sec : defaults.slice_delay_sec,
    });
  };

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
          <div>
            <label className="text-[10px] text-text-secondary uppercase tracking-[0.12em] block mb-1.5 font-mono">
              Order Mode
            </label>
            <select
              className="bg-surface-2/80 border border-border-default rounded-md px-3 py-2 text-[13px] font-mono text-text-primary hover:border-border-hover focus:border-accent/40 focus:outline-none transition-all"
              value={form.order_mode}
              onChange={(e) => set("order_mode", e.target.value)}
            >
              <option value="market">Market</option>
              <option value="sliced">Sliced</option>
              <option value="limit">Limit</option>
            </select>
          </div>
          {usesChunkControls && (
            <>
              <NumberField label="Chunks" value={form.slice_chunks} onChange={(v) => set("slice_chunks", v)} step={1} min={2} />
              <NumberField label="Delay (sec)" value={form.slice_delay_sec} onChange={(v) => set("slice_delay_sec", v)} step={0.5} min={0.5} />
            </>
          )}
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
            disabled={!canOpenTrade || openMut.isPending}
            onClick={openTrade}
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
                  <th className="text-left py-2 px-2">Mode</th>
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
                    <td className="py-2 px-2 text-text-muted capitalize">{t.order_mode}</td>
                    <td className="py-2 px-2 text-right text-text-muted">
                      {editingTradeId === t.id ? (
                        <div className="flex justify-end items-end gap-2">
                          <NumberField
                            label="SL %"
                            value={editForm.stop_loss_pct}
                            onChange={(v) => setEditForm((f) => ({ ...f, stop_loss_pct: v }))}
                            step={1}
                            min={0}
                          />
                          <NumberField
                            label="TP %"
                            value={editForm.take_profit_pct}
                            onChange={(v) => setEditForm((f) => ({ ...f, take_profit_pct: v }))}
                            step={1}
                            min={0}
                          />
                        </div>
                      ) : (
                        <span>-{t.stop_loss_pct}% / +{t.take_profit_pct}%</span>
                      )}
                    </td>
                    <td className="py-2 px-2 text-right text-text-primary">
                      ${t.entry_notional?.toFixed(0) ?? "—"}
                    </td>
                    <td className="py-2 px-2 text-text-muted">
                      {t.entry_time ? new Date(t.entry_time).toLocaleString() : "—"}
                    </td>
                    <td className="py-2 px-2 text-right">
                      <div className="flex justify-end gap-2">
                        {editingTradeId === t.id ? (
                          <>
                            <button
                              className="px-2 py-1 bg-accent/10 text-accent border border-accent/20 rounded text-[11px] hover:bg-accent/20 disabled:opacity-50"
                              disabled={
                                updateMut.isPending ||
                                !hasNumber(editForm.stop_loss_pct) ||
                                !hasNumber(editForm.take_profit_pct)
                              }
                              onClick={() => saveEdit(t.id)}
                            >
                              {updateMut.isPending ? "Saving..." : "Save"}
                            </button>
                            <button
                              className="px-2 py-1 bg-surface-2 text-text-secondary border border-border-default rounded text-[11px] hover:border-border-hover disabled:opacity-50"
                              disabled={updateMut.isPending}
                              onClick={cancelEdit}
                            >
                              Cancel
                            </button>
                          </>
                        ) : (
                          <button
                            className="px-2 py-1 bg-surface-2 text-text-secondary border border-border-default rounded text-[11px] hover:border-border-hover"
                            onClick={() => startEdit(t)}
                          >
                            Edit
                          </button>
                        )}
                        <button
                          className="px-2 py-1 bg-red-500/10 text-red-400 border border-red-500/20 rounded text-[11px] hover:bg-red-500/20 disabled:opacity-50"
                          disabled={closeMut.isPending}
                          onClick={() => closeMut.mutate(t.id)}
                        >
                          Close
                        </button>
                      </div>
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
