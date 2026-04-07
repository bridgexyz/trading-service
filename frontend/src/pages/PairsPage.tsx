import { useState, useRef, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import api from "../api/client";
import StatusBadge from "../components/StatusBadge";
import { fmtDollar } from "../utils/formatNumber";
import type { TradingPair, Credential } from "../types";

const INTERVALS = ["15m", "30m", "1h", "2h", "4h", "8h", "12h", "1d"];

interface Market {
  market_id: number;
  symbol: string;
}

const defaultPair = {
  asset_a: "",
  asset_b: "",
  lighter_market_a: 0,
  lighter_market_b: 0,
  entry_z: 1.5,
  exit_z_early: 0.5,
  exit_z_late: 0.2,
  stop_z: 4.0,
  window_interval: "4h",
  window_candles: 40,
  train_candles: 100,
  max_half_life: 10,
  rsi_upper: 65,
  rsi_lower: 15,
  rsi_period: 14,
  rsi_a_lower: 10,
  rsi_a_upper: 70,
  rsi_b_lower: 10,
  rsi_b_upper: 70,
  stop_loss_pct: 10,
  position_size_pct: 50,
  leverage: 5,
  order_mode: "market" as "market" | "sliced" | "limit",
  slice_chunks: 10,
  slice_delay_sec: 2.0,
  cooldown_losses: 0,
  cooldown_loss_pct: 0,
  cooldown_drawdown_pct: 0,
  cooldown_candles: 0,
  schedule_interval: 10,
  exit_schedule_interval: 10,
  use_exit_schedule: false,
  is_enabled: true,
  credential_id: null as number | null,
};

type FormData = typeof defaultPair;
type SubmitData = Omit<FormData, "schedule_interval" | "exit_schedule_interval"> & { name: string; train_interval: string; schedule_interval: string; exit_schedule_interval: string };

function SectionLabel({ children }: { children: string }) {
  return (
    <div className="text-[10px] text-text-secondary uppercase tracking-[0.15em] font-mono font-medium pt-3 pb-1.5 border-b border-border-default/50 w-full">
      {children}
    </div>
  );
}

function Field({
  label,
  value,
  onChange,
  w = "w-24",
}: {
  label: string;
  value: string | number;
  onChange: (v: string | number) => void;
  w?: string;
}) {
  const [touched, setTouched] = useState(false);
  const isEmpty = value === "" || value === undefined;
  const showError = touched && isEmpty;

  return (
    <div>
      <label className="text-[10px] text-text-secondary uppercase tracking-[0.12em] block mb-1.5 font-mono">
        {label}
      </label>
      <input
        type="text"
        inputMode="decimal"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          if (["Backspace", "Delete", "Tab", "ArrowLeft", "ArrowRight", "Home", "End"].includes(e.key)) return;
          if (e.key === "-" && e.currentTarget.selectionStart === 0 && !e.currentTarget.value.includes("-")) return;
          if (e.key === "." && !e.currentTarget.value.includes(".")) return;
          if (/^\d$/.test(e.key)) return;
          e.preventDefault();
        }}
        onWheel={(e) => e.currentTarget.blur()}
        onBlur={() => setTouched(true)}
        className={`bg-surface-2/80 border ${showError ? "border-red-500" : "border-border-default"} rounded-md px-3 py-2 text-[13px] font-mono text-text-primary placeholder:text-text-muted hover:border-border-hover focus:border-accent/40 focus:outline-none transition-all ${w}`}
      />
      {showError && <span className="text-[10px] text-red-400 mt-0.5 block">Required</span>}
    </div>
  );
}

function SelectField({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: string[];
}) {
  return (
    <div>
      <label className="text-[10px] text-text-secondary uppercase tracking-[0.12em] block mb-1.5 font-mono">
        {label}
      </label>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="bg-surface-2/80 border border-border-default rounded-md px-3 py-2 text-[13px] font-mono text-text-primary hover:border-border-hover focus:border-accent/40 focus:outline-none transition-all"
      >
        {options.map((o) => (
          <option key={o}>{o}</option>
        ))}
      </select>
    </div>
  );
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

function PairForm({
  initial,
  onSubmit,
  onCancel,
  markets,
  credentials,
  isEdit,
}: {
  initial: FormData;
  onSubmit: (data: SubmitData) => void;
  onCancel: () => void;
  markets: Market[];
  credentials: Credential[];
  isEdit: boolean;
}) {
  const [form, setForm] = useState<FormData>(initial);
  const set = (key: keyof FormData, value: string | number | boolean | null) =>
    setForm((f) => ({ ...f, [key]: value }));

  const handleSubmit = () => {
    const numericKeys = ["entry_z","exit_z_early","exit_z_late","stop_z","window_candles","train_candles",
      "max_half_life","rsi_upper","rsi_lower","rsi_period",
      "rsi_a_lower","rsi_a_upper","rsi_b_lower","rsi_b_upper",
      "stop_loss_pct","position_size_pct","leverage","schedule_interval"] as const;
    const invalid = numericKeys.filter(k => String(form[k]) === "" || isNaN(Number(form[k])));
    if (invalid.length > 0) return;
    if (form.use_exit_schedule && (String(form.exit_schedule_interval) === "" || isNaN(Number(form.exit_schedule_interval)))) return;

    const name = `${form.asset_a}-${form.asset_b}`;
    onSubmit({
      ...form,
      schedule_interval: `${form.schedule_interval}m`,
      exit_schedule_interval: `${form.exit_schedule_interval}m`,
      train_interval: form.window_interval,
      name,
    });
  };

  return (
    <div className="bg-surface-1 border border-border-default rounded-lg p-5 space-y-3 animate-fade-up">
      <h3 className="text-sm font-semibold tracking-tight">
        {isEdit ? "Edit Pair" : "New Trading Pair"}
      </h3>

      <SectionLabel>Assets</SectionLabel>
      <div className="flex flex-wrap gap-3">
        <AssetAutocomplete
          label="Asset A"
          value={form.asset_a as string}
          onChange={(v) => set("asset_a", v)}
          markets={markets}
          onSelect={(m) => {
            set("asset_a", m.symbol);
            set("lighter_market_a", m.market_id);
          }}
        />
        <AssetAutocomplete
          label="Asset B"
          value={form.asset_b as string}
          onChange={(v) => set("asset_b", v)}
          markets={markets}
          onSelect={(m) => {
            set("asset_b", m.symbol);
            set("lighter_market_b", m.market_id);
          }}
        />
      </div>

      <SectionLabel>Signal Thresholds</SectionLabel>
      <div className="flex flex-wrap gap-3">
        <Field label="Entry Z" value={form.entry_z} onChange={(v) => set("entry_z", v)} />
        <Field label="Exit Z <8h" value={form.exit_z_early} onChange={(v) => set("exit_z_early", v)} />
        <Field label="Exit Z >8h" value={form.exit_z_late} onChange={(v) => set("exit_z_late", v)} />
        <Field label="Stop Z" value={form.stop_z} onChange={(v) => set("stop_z", v)} />
      </div>

      <SectionLabel>Windows</SectionLabel>
      <div className="flex flex-wrap gap-3">
        <SelectField label="Window" value={form.window_interval as string} onChange={(v) => set("window_interval", v)} options={INTERVALS} />
        <Field label="Z Candles" value={form.window_candles} onChange={(v) => set("window_candles", v)} />
        <Field label="Train Candles" value={form.train_candles} onChange={(v) => set("train_candles", v)} />
      </div>

      <SectionLabel>Regime Filters</SectionLabel>
      <div className="flex flex-wrap gap-3">
        <Field label="Max Half-Life" value={form.max_half_life} onChange={(v) => set("max_half_life", v)} />
        <Field label="RSI Period" value={form.rsi_period} onChange={(v) => set("rsi_period", v)} />
        <Field label="Ratio RSI Upper" value={form.rsi_upper} onChange={(v) => set("rsi_upper", v)} />
        <Field label="Ratio RSI Lower" value={form.rsi_lower} onChange={(v) => set("rsi_lower", v)} />
        <Field label="RSI A Lower" value={form.rsi_a_lower} onChange={(v) => set("rsi_a_lower", v)} />
        <Field label="RSI A Upper" value={form.rsi_a_upper} onChange={(v) => set("rsi_a_upper", v)} />
        <Field label="RSI B Lower" value={form.rsi_b_lower} onChange={(v) => set("rsi_b_lower", v)} />
        <Field label="RSI B Upper" value={form.rsi_b_upper} onChange={(v) => set("rsi_b_upper", v)} />
      </div>

      <SectionLabel>Risk & Execution</SectionLabel>
      <div className="flex flex-wrap gap-3">
        <Field label="Stop Loss %" value={form.stop_loss_pct} onChange={(v) => set("stop_loss_pct", v)} />
        <Field label="Position Size (%)" value={form.position_size_pct} onChange={(v) => set("position_size_pct", v)} />
        <Field label="Leverage" value={form.leverage} onChange={(v) => set("leverage", v)} />
        <SelectField label="Order Mode" value={form.order_mode as string} onChange={(v) => set("order_mode", v)} options={["market", "sliced", "limit"]} />
        {(form.order_mode === "sliced" || form.order_mode === "limit") && (
          <>
            <Field label="Chunks" value={form.slice_chunks} onChange={(v) => set("slice_chunks", v)} />
            <Field label="Delay (sec)" value={form.slice_delay_sec} onChange={(v) => set("slice_delay_sec", v)} />
          </>
        )}
      </div>

      <SectionLabel>Cooldown</SectionLabel>
      <div className="flex flex-wrap gap-3">
        <Field label="Consec. Losses" value={form.cooldown_losses} onChange={(v) => set("cooldown_losses", v)} />
        <Field label="Loss Sum %" value={form.cooldown_loss_pct} onChange={(v) => set("cooldown_loss_pct", v)} />
        <Field label="Max Drawdown %" value={form.cooldown_drawdown_pct} onChange={(v) => set("cooldown_drawdown_pct", v)} />
        <Field label="Wait Candles" value={form.cooldown_candles} onChange={(v) => set("cooldown_candles", v)} />
      </div>

      <SectionLabel>Schedule & Credential</SectionLabel>
      <div className="flex flex-wrap gap-3 items-end">
        <Field label={form.use_exit_schedule ? "Entry Interval (min)" : "Schedule Interval (min)"} value={form.schedule_interval} onChange={(v) => set("schedule_interval", v)} />
        <div>
          <label className="text-[10px] text-text-secondary uppercase tracking-[0.12em] block mb-1.5 font-mono">
            Exit Schedule
          </label>
          <button
            type="button"
            onClick={() => set("use_exit_schedule", !form.use_exit_schedule)}
            className={`w-11 h-6 rounded-full transition-all relative ${
              form.use_exit_schedule ? "bg-accent shadow-[0_0_10px_var(--color-accent)/30]" : "bg-surface-3 border border-border-default"
            }`}
          >
            <span
              className={`absolute top-0.5 w-5 h-5 rounded-full bg-white transition-transform shadow-sm ${
                form.use_exit_schedule ? "left-5.5" : "left-0.5"
              }`}
            />
          </button>
        </div>
        {form.use_exit_schedule && (
          <Field label="Exit Interval (min)" value={form.exit_schedule_interval} onChange={(v) => set("exit_schedule_interval", v)} />
        )}
        <div>
          <label className="text-[10px] text-text-secondary uppercase tracking-[0.12em] block mb-1.5 font-mono">
            Credential
          </label>
          <select
            value={form.credential_id ?? ""}
            onChange={(e) => set("credential_id", e.target.value ? Number(e.target.value) : null)}
            className="bg-surface-2/80 border border-border-default rounded-md px-3 py-2 text-[13px] font-mono text-text-primary hover:border-border-hover focus:border-accent/40 focus:outline-none transition-all"
          >
            <option value="">Default (first active)</option>
            {credentials.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name} {!c.is_active && "(inactive)"}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="text-[10px] text-text-secondary uppercase tracking-[0.12em] block mb-1.5 font-mono">
            Enabled
          </label>
          <button
            type="button"
            onClick={() => set("is_enabled", !form.is_enabled)}
            className={`w-11 h-6 rounded-full transition-all relative ${
              form.is_enabled ? "bg-accent shadow-[0_0_10px_var(--color-accent)/30]" : "bg-surface-3 border border-border-default"
            }`}
          >
            <span
              className={`absolute top-0.5 w-5 h-5 rounded-full bg-white transition-transform shadow-sm ${
                form.is_enabled ? "left-5.5" : "left-0.5"
              }`}
            />
          </button>
        </div>
      </div>

      <div className="flex gap-2 pt-4">
        <button
          onClick={handleSubmit}
          className="bg-accent/90 hover:bg-accent text-surface-0 px-5 py-2.5 rounded-md text-[13px] font-semibold transition-all shadow-lg shadow-accent/10 hover:shadow-accent/20 min-h-[44px] sm:min-h-0"
        >
          Save
        </button>
        <button
          onClick={onCancel}
          className="bg-surface-2 hover:bg-surface-3 text-text-secondary px-5 py-2.5 rounded-md text-[13px] font-medium transition-colors min-h-[44px] sm:min-h-0"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}

export default function PairsPage() {
  const qc = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [editId, setEditId] = useState<number | null>(null);

  const { data: pairs } = useQuery<TradingPair[]>({
    queryKey: ["pairs"],
    queryFn: () => api.get("/pairs").then((r) => r.data),
  });

  const { data: markets = [] } = useQuery<Market[]>({
    queryKey: ["markets"],
    queryFn: () => api.get("/markets").then((r) => r.data),
  });

  const { data: credentials = [] } = useQuery<Credential[]>({
    queryKey: ["credentials"],
    queryFn: () => api.get("/credentials").then((r) => r.data),
  });

  const createMut = useMutation({
    mutationFn: (data: SubmitData) => api.post("/pairs", data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["pairs"] });
      setShowForm(false);
    },
  });

  const updateMut = useMutation({
    mutationFn: ({ id, data }: { id: number; data: Partial<SubmitData> }) =>
      api.put(`/pairs/${id}`, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["pairs"] });
      setEditId(null);
    },
  });

  const toggleMut = useMutation({
    mutationFn: (id: number) => api.post(`/pairs/${id}/toggle`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["pairs"] }),
  });

  const deleteMut = useMutation({
    mutationFn: (id: number) => api.delete(`/pairs/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["pairs"] }),
  });

  const triggerMut = useMutation({
    mutationFn: (id: number) => api.post(`/system/trigger/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["pairs"] }),
  });

  const editingPair = editId
    ? pairs?.find((p) => p.id === editId)
    : null;

  const pairToFormData = (pair: TradingPair): FormData => ({
    asset_a: pair.asset_a,
    asset_b: pair.asset_b,
    lighter_market_a: pair.lighter_market_a,
    lighter_market_b: pair.lighter_market_b,
    entry_z: pair.entry_z,
    exit_z_early: pair.exit_z_early,
    exit_z_late: pair.exit_z_late,
    stop_z: pair.stop_z,
    window_interval: pair.window_interval,
    window_candles: pair.window_candles,
    train_candles: pair.train_candles,
    max_half_life: pair.max_half_life,
    rsi_upper: pair.rsi_upper,
    rsi_lower: pair.rsi_lower,
    rsi_period: pair.rsi_period,
    rsi_a_lower: pair.rsi_a_lower ?? 10,
    rsi_a_upper: pair.rsi_a_upper ?? 70,
    rsi_b_lower: pair.rsi_b_lower ?? 10,
    rsi_b_upper: pair.rsi_b_upper ?? 70,
    stop_loss_pct: pair.stop_loss_pct,
    position_size_pct: pair.position_size_pct,
    leverage: pair.leverage,
    order_mode: (pair.order_mode || "market") as "market" | "sliced" | "limit",
    slice_chunks: pair.slice_chunks ?? 10,
    slice_delay_sec: pair.slice_delay_sec ?? 2.0,
    cooldown_losses: pair.cooldown_losses ?? 0,
    cooldown_loss_pct: pair.cooldown_loss_pct ?? 0,
    cooldown_drawdown_pct: pair.cooldown_drawdown_pct ?? 0,
    cooldown_candles: pair.cooldown_candles ?? 0,
    schedule_interval: parseInt(pair.schedule_interval) || 10,
    exit_schedule_interval: parseInt(pair.exit_schedule_interval) || 10,
    use_exit_schedule: pair.use_exit_schedule ?? false,
    is_enabled: pair.is_enabled,
    credential_id: pair.credential_id,
  });

  const activePairs = pairs?.filter((p) => p.is_enabled) ?? [];
  const pausedPairs = pairs?.filter((p) => !p.is_enabled) ?? [];

  const renderMobileCard = (pair: TradingPair) => (
    <div
      key={pair.id}
      className="bg-surface-1 border border-border-default rounded-lg p-4 space-y-3 card-hover"
    >
      <div className="flex items-center justify-between">
        <Link
          to={`/pairs/${pair.id}`}
          className="text-[13px] text-accent hover:text-accent-hover font-medium transition-colors"
        >
          {pair.name}
        </Link>
        <StatusBadge status={pair.is_enabled ? "active" : "paused"} />
      </div>
      <div className="flex items-center gap-3 text-[11px] text-text-muted font-mono">
        <span>{pair.asset_a}/{pair.asset_b}</span>
        <span>{pair.schedule_interval}</span>
        <span className="text-text-primary">${fmtDollar(pair.current_equity, 0)}</span>
      </div>
      <div className="flex gap-1.5 pt-1">
        <button
          onClick={() => triggerMut.mutate(pair.id)}
          disabled={triggerMut.isPending}
          className="text-[11px] font-mono bg-surface-2 hover:bg-surface-3 border border-border-default text-text-secondary hover:text-text-primary px-2.5 py-1.5 rounded-md transition-colors disabled:opacity-40 min-h-[44px]"
        >
          RUN
        </button>
        <button
          onClick={() => toggleMut.mutate(pair.id)}
          className="text-[11px] font-mono bg-surface-2 hover:bg-surface-3 border border-border-default text-text-secondary hover:text-text-primary px-2.5 py-1.5 rounded-md transition-colors min-h-[44px]"
        >
          {pair.is_enabled ? "PAUSE" : "RESUME"}
        </button>
        <button
          onClick={() => setEditId(pair.id)}
          className="text-[11px] font-mono text-accent hover:text-accent-hover px-2.5 py-1.5 rounded-md hover:bg-surface-2 transition-colors min-h-[44px]"
        >
          EDIT
        </button>
        <button
          onClick={() => {
            if (confirm("Delete this pair?"))
              deleteMut.mutate(pair.id);
          }}
          className="text-[11px] font-mono text-negative px-2.5 py-1.5 rounded-md hover:bg-negative/8 transition-colors min-h-[44px]"
        >
          DEL
        </button>
      </div>
    </div>
  );

  const renderDesktopRow = (pair: TradingPair) => (
    <tr
      key={pair.id}
      className="border-b border-border-default/50 hover:bg-surface-2/30"
    >
      <td className="px-5 py-3">
        <Link
          to={`/pairs/${pair.id}`}
          className="text-accent hover:text-accent-hover font-medium transition-colors"
        >
          {pair.name}
        </Link>
      </td>
      <td className="px-5 py-3 text-text-secondary font-mono text-xs">
        {pair.asset_a}/{pair.asset_b}
      </td>
      <td className="px-5 py-3 text-center text-text-secondary font-mono text-xs">
        {pair.schedule_interval}
        {pair.use_exit_schedule && <span className="text-text-muted"> / {pair.exit_schedule_interval}</span>}
      </td>
      <td className="px-5 py-3 text-right font-mono text-text-primary">
        ${fmtDollar(pair.current_equity, 0)}
      </td>
      <td className="px-5 py-3 text-center">
        <StatusBadge status={pair.is_enabled ? "active" : "paused"} />
      </td>
      <td className="px-5 py-3 text-right">
        <div className="flex items-center justify-end gap-1">
          <button
            onClick={() => triggerMut.mutate(pair.id)}
            disabled={triggerMut.isPending}
            className="text-[11px] font-mono text-text-secondary hover:text-text-primary px-2 py-1 rounded-md hover:bg-surface-2 transition-colors disabled:opacity-40"
          >
            Run
          </button>
          <button
            onClick={() => toggleMut.mutate(pair.id)}
            className="text-[11px] font-mono text-text-secondary hover:text-text-primary px-2 py-1 rounded-md hover:bg-surface-2 transition-colors"
          >
            {pair.is_enabled ? "Pause" : "Resume"}
          </button>
          <button
            onClick={() => setEditId(pair.id)}
            className="text-[11px] font-mono text-accent hover:text-accent-hover px-2 py-1 rounded-md hover:bg-surface-2 transition-colors"
          >
            Edit
          </button>
          <button
            onClick={() => {
              if (confirm("Delete this pair?"))
                deleteMut.mutate(pair.id);
            }}
            className="text-[11px] font-mono text-negative hover:text-negative px-2 py-1 rounded-md hover:bg-negative/8 transition-colors"
          >
            Delete
          </button>
        </div>
      </td>
    </tr>
  );

  const desktopTableHead = (
    <thead>
      <tr className="border-b border-border-default">
        <th className="text-left px-5 py-2.5 text-[10px] font-mono font-medium text-text-secondary uppercase tracking-[0.15em]">Name</th>
        <th className="text-left px-5 py-2.5 text-[10px] font-mono font-medium text-text-secondary uppercase tracking-[0.15em]">Assets</th>
        <th className="text-center px-5 py-2.5 text-[10px] font-mono font-medium text-text-secondary uppercase tracking-[0.15em]">Schedule</th>
        <th className="text-right px-5 py-2.5 text-[10px] font-mono font-medium text-text-secondary uppercase tracking-[0.15em]">Equity</th>
        <th className="text-center px-5 py-2.5 text-[10px] font-mono font-medium text-text-secondary uppercase tracking-[0.15em]">Status</th>
        <th className="text-right px-5 py-2.5 text-[10px] font-mono font-medium text-text-secondary uppercase tracking-[0.15em]">Actions</th>
      </tr>
    </thead>
  );

  return (
    <div className="space-y-6 max-w-7xl">
      <div className="flex items-baseline justify-between">
        <div className="flex items-baseline gap-3">
          <h2 className="text-xl font-semibold tracking-tight">Trading Pairs</h2>
          <span className="text-[10px] font-mono text-text-secondary tracking-[0.2em]">MANAGE</span>
        </div>
        <button
          onClick={() => {
            setShowForm(true);
            setEditId(null);
          }}
          className="bg-accent/90 hover:bg-accent text-surface-0 px-4 py-2.5 rounded-md text-[12px] font-semibold transition-all shadow-lg shadow-accent/10 hover:shadow-accent/20 tracking-wide min-h-[44px] sm:min-h-0"
        >
          + ADD PAIR
        </button>
      </div>

      {showForm && (
        <PairForm
          initial={defaultPair}
          onSubmit={(data) => createMut.mutate(data)}
          onCancel={() => setShowForm(false)}
          markets={markets}
          credentials={credentials}
          isEdit={false}
        />
      )}

      {editId && editingPair && (
        <PairForm
          initial={pairToFormData(editingPair)}
          onSubmit={(data) => updateMut.mutate({ id: editId, data })}
          onCancel={() => setEditId(null)}
          markets={markets}
          credentials={credentials}
          isEdit={true}
        />
      )}

      {/* Mobile card layout */}
      <div className="md:hidden space-y-4">
        {activePairs.length > 0 && (
          <div className="space-y-2">
            <div className="text-[10px] text-text-secondary uppercase tracking-[0.15em] font-mono font-medium">
              Active Pairs
            </div>
            {activePairs.map(renderMobileCard)}
          </div>
        )}
        {pausedPairs.length > 0 && (
          <div className="space-y-2">
            <div className="text-[10px] text-text-secondary uppercase tracking-[0.15em] font-mono font-medium">
              Paused Pairs
            </div>
            {pausedPairs.map(renderMobileCard)}
          </div>
        )}
        {activePairs.length === 0 && pausedPairs.length === 0 && (
          <p className="text-center text-text-muted py-12 text-sm">
            No pairs configured yet.
          </p>
        )}
      </div>

      {/* Desktop tables */}
      <div className="hidden md:block space-y-4">
        {activePairs.length > 0 && (
          <div>
            <div className="text-[10px] text-text-secondary uppercase tracking-[0.15em] font-mono font-medium mb-2">
              Active Pairs
            </div>
            <div className="bg-surface-1 border border-border-default rounded-lg overflow-hidden">
              <div className="overflow-x-auto">
                <table className="w-full text-[13px]">
                  {desktopTableHead}
                  <tbody>{activePairs.map(renderDesktopRow)}</tbody>
                </table>
              </div>
            </div>
          </div>
        )}
        {pausedPairs.length > 0 && (
          <div>
            <div className="text-[10px] text-text-secondary uppercase tracking-[0.15em] font-mono font-medium mb-2">
              Paused Pairs
            </div>
            <div className="bg-surface-1 border border-border-default rounded-lg overflow-hidden">
              <div className="overflow-x-auto">
                <table className="w-full text-[13px]">
                  {desktopTableHead}
                  <tbody>{pausedPairs.map(renderDesktopRow)}</tbody>
                </table>
              </div>
            </div>
          </div>
        )}
        {activePairs.length === 0 && pausedPairs.length === 0 && (
          <div className="bg-surface-1 border border-border-default rounded-lg overflow-hidden">
            <p className="text-center text-text-muted py-12 text-sm">
              No pairs configured yet.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
