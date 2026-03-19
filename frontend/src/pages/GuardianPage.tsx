import { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api from "../api/client";
import type { GuardianSettings, GuardianStatus, TradingPair } from "../types";

function Toggle({
  checked,
  onChange,
}: {
  checked: boolean;
  onChange: () => void;
}) {
  return (
    <div
      onClick={onChange}
      className={`relative w-10 h-5 rounded-full transition-colors cursor-pointer ${
        checked ? "bg-accent" : "bg-surface-3"
      }`}
    >
      <div
        className={`absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform ${
          checked ? "translate-x-5" : "translate-x-0.5"
        }`}
      />
    </div>
  );
}

export default function GuardianPage() {
  const qc = useQueryClient();

  const { data: settings } = useQuery<GuardianSettings>({
    queryKey: ["guardian-settings"],
    queryFn: () => api.get("/guardian/settings").then((r) => r.data),
  });

  const { data: status } = useQuery<GuardianStatus>({
    queryKey: ["guardian-status"],
    queryFn: () => api.get("/guardian/status").then((r) => r.data),
    refetchInterval: 15000,
  });

  const { data: pairs } = useQuery<TradingPair[]>({
    queryKey: ["pairs"],
    queryFn: () => api.get("/pairs").then((r) => r.data),
  });

  const [form, setForm] = useState({
    enabled: true,
    interval_seconds: 60,
    stop_loss_pct_override: null as number | null,
  });

  useEffect(() => {
    if (settings) {
      setForm({
        enabled: settings.enabled,
        interval_seconds: settings.interval_seconds,
        stop_loss_pct_override: settings.stop_loss_pct_override,
      });
    }
  }, [settings]);

  const useOverride = form.stop_loss_pct_override !== null;

  const updateMut = useMutation({
    mutationFn: (data: Partial<GuardianSettings>) =>
      api.patch("/guardian/settings", data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["guardian-settings"] });
      qc.invalidateQueries({ queryKey: ["guardian-status"] });
    },
  });

  const toggleExcludeMut = useMutation({
    mutationFn: ({ id, excluded }: { id: number; excluded: boolean }) =>
      api.patch(`/pairs/${id}`, { guardian_excluded: excluded }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["pairs"] });
      qc.invalidateQueries({ queryKey: ["guardian-status"] });
    },
  });

  const handleSave = () => {
    updateMut.mutate({
      enabled: form.enabled,
      interval_seconds: form.interval_seconds,
      stop_loss_pct_override: form.stop_loss_pct_override,
    });
  };

  const activePairs = pairs?.filter((p) => p.is_enabled) ?? [];

  return (
    <div className="space-y-6 max-w-4xl">
      {/* Header */}
      <div className="flex items-baseline justify-between">
        <div className="flex items-baseline gap-3">
          <h2 className="text-xl font-semibold tracking-tight">
            Stop-Loss Guardian
          </h2>
          <span className="text-[10px] font-mono text-text-muted tracking-[0.2em]">
            GLOBAL
          </span>
        </div>
        <div
          className={`flex items-center gap-1.5 text-[11px] font-mono px-2.5 py-1 rounded border ${
            status?.job_running
              ? "bg-accent/8 text-accent border-accent/20"
              : "bg-surface-2/50 text-text-muted border-border-default"
          }`}
        >
          <span
            className={`w-1.5 h-1.5 rounded-full ${
              status?.job_running
                ? "bg-accent shadow-[0_0_8px_var(--color-accent)]"
                : "bg-text-muted"
            }`}
          />
          {status?.job_running ? "RUNNING" : "STOPPED"}
        </div>
      </div>

      {/* Settings card */}
      <div className="bg-surface-1 border border-border-default rounded-lg p-5 space-y-4">
        <h3 className="text-sm font-semibold tracking-tight">Settings</h3>

        <div className="space-y-4">
          {/* Enable toggle */}
          <label className="flex items-center justify-between min-h-[44px] px-3 py-2 rounded-md bg-surface-2/50 border border-border-default hover:border-border-hover transition-colors cursor-pointer">
            <span className="text-[13px] text-text-primary">
              Enable Guardian
            </span>
            <Toggle
              checked={form.enabled}
              onChange={() => setForm((f) => ({ ...f, enabled: !f.enabled }))}
            />
          </label>

          {/* Interval */}
          <div>
            <label className="text-[10px] text-text-muted uppercase tracking-[0.12em] block mb-1.5 font-mono">
              Check Interval (seconds)
            </label>
            <input
              type="number"
              min={10}
              max={300}
              value={form.interval_seconds}
              onChange={(e) =>
                setForm((f) => ({
                  ...f,
                  interval_seconds: Number(e.target.value),
                }))
              }
              onWheel={(e) => e.currentTarget.blur()}
              className="bg-surface-2/80 border border-border-default rounded-md px-3 py-2 text-[13px] font-mono text-text-primary hover:border-border-hover focus:border-accent/40 focus:outline-none transition-all w-28"
            />
            <p className="text-[11px] text-text-muted mt-1">
              Range: 10-300 seconds
            </p>
          </div>

          {/* Global stop-loss override */}
          <div>
            <label className="flex items-center gap-2.5 text-[13px] text-text-primary cursor-pointer mb-2">
              <input
                type="checkbox"
                checked={useOverride}
                onChange={(e) =>
                  setForm((f) => ({
                    ...f,
                    stop_loss_pct_override: e.target.checked
                      ? f.stop_loss_pct_override ?? 5
                      : null,
                  }))
                }
                className="w-4 h-4 rounded accent-accent"
              />
              Override per-pair stop-loss %
            </label>
            {useOverride && (
              <div className="ml-6">
                <input
                  type="number"
                  min={0.1}
                  step={0.1}
                  value={form.stop_loss_pct_override ?? 5}
                  onChange={(e) =>
                    setForm((f) => ({
                      ...f,
                      stop_loss_pct_override: Number(e.target.value),
                    }))
                  }
                  onWheel={(e) => e.currentTarget.blur()}
                  className="bg-surface-2/80 border border-border-default rounded-md px-3 py-2 text-[13px] font-mono text-text-primary hover:border-border-hover focus:border-accent/40 focus:outline-none transition-all w-24"
                />
                <span className="text-[12px] text-text-muted ml-2">%</span>
                <p className="text-[11px] text-text-muted mt-1">
                  All positions will use this threshold instead of per-pair
                  values
                </p>
              </div>
            )}
          </div>
        </div>

        {/* Save */}
        <div className="flex items-center gap-3 pt-1">
          <button
            onClick={handleSave}
            disabled={updateMut.isPending}
            className="bg-accent/90 hover:bg-accent disabled:opacity-40 text-surface-0 px-5 py-2.5 rounded-md text-[13px] font-semibold transition-all shadow-lg shadow-accent/10 hover:shadow-accent/20 min-h-[44px] sm:min-h-0"
          >
            {updateMut.isPending ? "Saving..." : "Save"}
          </button>
          {updateMut.isSuccess && (
            <span className="text-accent text-[12px] font-mono">Saved</span>
          )}
          {updateMut.isError && (
            <span className="text-negative text-[12px] font-mono">
              Error saving
            </span>
          )}
        </div>
      </div>

      {/* Status card */}
      <div className="bg-surface-1 border border-border-default rounded-lg p-5">
        <h3 className="text-sm font-semibold tracking-tight mb-3">Status</h3>
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">
          <div>
            <div className="text-[10px] text-text-muted uppercase tracking-[0.12em] font-mono mb-1">
              Monitored Positions
            </div>
            <div className="text-lg font-semibold text-text-primary font-mono">
              {status?.monitored_positions ?? 0}
            </div>
          </div>
          <div>
            <div className="text-[10px] text-text-muted uppercase tracking-[0.12em] font-mono mb-1">
              Interval
            </div>
            <div className="text-lg font-semibold text-text-primary font-mono">
              {status?.interval_seconds ?? "-"}s
            </div>
          </div>
          <div>
            <div className="text-[10px] text-text-muted uppercase tracking-[0.12em] font-mono mb-1">
              Next Run
            </div>
            <div className="text-[13px] font-mono text-text-secondary">
              {status?.next_run
                ? new Date(status.next_run).toLocaleTimeString()
                : "-"}
            </div>
          </div>
        </div>
      </div>

      {/* Pair exclusion list */}
      <div className="bg-surface-1 border border-border-default rounded-lg p-5">
        <h3 className="text-sm font-semibold tracking-tight mb-3">
          Pair Exclusions
        </h3>
        <p className="text-[12px] text-text-muted mb-4">
          Excluded pairs will not be monitored by the guardian. Their own
          scheduled stop-loss checks still apply.
        </p>

        {activePairs.length === 0 ? (
          <p className="text-[13px] text-text-muted py-4 text-center">
            No active pairs
          </p>
        ) : (
          <div className="space-y-1">
            {activePairs.map((pair) => (
              <div
                key={pair.id}
                className="flex items-center justify-between px-3 py-2.5 rounded-md bg-surface-2/30 hover:bg-surface-2/60 transition-colors"
              >
                <div className="flex items-center gap-3">
                  <span className="text-[13px] font-medium text-text-primary">
                    {pair.name}
                  </span>
                  <span className="text-[11px] font-mono text-text-muted">
                    SL: {pair.stop_loss_pct}%
                  </span>
                </div>
                <label className="flex items-center gap-2 cursor-pointer">
                  <span
                    className={`text-[11px] font-mono ${
                      pair.guardian_excluded
                        ? "text-warning"
                        : "text-text-muted"
                    }`}
                  >
                    {pair.guardian_excluded ? "EXCLUDED" : "MONITORED"}
                  </span>
                  <Toggle
                    checked={!pair.guardian_excluded}
                    onChange={() =>
                      toggleExcludeMut.mutate({
                        id: pair.id,
                        excluded: !pair.guardian_excluded,
                      })
                    }
                  />
                </label>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
