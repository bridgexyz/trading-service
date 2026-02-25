import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api from "../api/client";
import StatusBadge from "../components/StatusBadge";
import type { Credential } from "../types";

export default function CredentialsPage() {
  const qc = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({
    name: "default",
    lighter_host: "https://mainnet.zklighter.elliot.ai",
    api_key_index: 3,
    private_key: "",
    account_index: 0,
  });

  const { data: creds } = useQuery<Credential[]>({
    queryKey: ["credentials"],
    queryFn: () => api.get("/credentials").then((r) => r.data),
  });

  const [error, setError] = useState<string>("");

  const createMut = useMutation({
    mutationFn: (data: typeof form) => api.post("/credentials", data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["credentials"] });
      setShowForm(false);
      setError("");
      setForm((f) => ({ ...f, private_key: "" }));
    },
    onError: (err: unknown) => {
      if (err && typeof err === "object" && "response" in err) {
        const resp = (err as { response: { data: { detail: unknown } } }).response;
        const detail = resp?.data?.detail;
        if (Array.isArray(detail)) {
          setError(detail.map((d: { loc: string[]; msg: string }) => `${d.loc.slice(-1)}: ${d.msg}`).join(", "));
        } else if (typeof detail === "string") {
          setError(detail);
        } else {
          setError("Failed to save credential");
        }
      } else {
        setError("Failed to save credential");
      }
    },
  });

  const testMut = useMutation({
    mutationFn: (id: number) => api.post(`/credentials/${id}/test`),
  });

  const deleteMut = useMutation({
    mutationFn: (id: number) => api.delete(`/credentials/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["credentials"] }),
  });

  return (
    <div className="space-y-6 max-w-4xl">
      <div className="flex items-baseline justify-between">
        <div className="flex items-baseline gap-3">
          <h2 className="text-xl font-semibold tracking-tight">Credentials</h2>
          <span className="text-[10px] font-mono text-text-muted tracking-[0.2em]">KEYS</span>
        </div>
        <button
          onClick={() => setShowForm(!showForm)}
          className="bg-accent/90 hover:bg-accent text-surface-0 px-4 py-2.5 rounded-lg text-[12px] font-semibold transition-all shadow-lg shadow-accent/10 hover:shadow-accent/20 tracking-wide min-h-[44px] sm:min-h-0"
        >
          + ADD KEY
        </button>
      </div>

      {showForm && (
        <div className="bg-surface-1 border border-border-default rounded-xl p-5 space-y-4 animate-fade-up">
          <h3 className="text-sm font-semibold tracking-tight">New Lighter Credential</h3>
          <div className="flex flex-wrap gap-3">
            <div>
              <label className="text-[10px] text-text-muted uppercase tracking-[0.12em] block mb-1.5 font-mono">
                Name
              </label>
              <input
                type="text"
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                className="bg-surface-2/80 border border-border-default rounded-lg px-3 py-2 text-[13px] font-mono text-text-primary placeholder:text-text-muted hover:border-border-hover focus:border-accent/40 focus:outline-none transition-all w-36"
              />
            </div>
            <div>
              <label className="text-[10px] text-text-muted uppercase tracking-[0.12em] block mb-1.5 font-mono">
                Lighter Host
              </label>
              <input
                type="text"
                value={form.lighter_host}
                onChange={(e) => setForm({ ...form, lighter_host: e.target.value })}
                className="bg-surface-2/80 border border-border-default rounded-lg px-3 py-2 text-[13px] font-mono text-text-primary placeholder:text-text-muted hover:border-border-hover focus:border-accent/40 focus:outline-none transition-all w-80"
              />
            </div>
            <div>
              <label className="text-[10px] text-text-muted uppercase tracking-[0.12em] block mb-1.5 font-mono">
                API Key Index
              </label>
              <input
                type="number"
                value={form.api_key_index}
                onChange={(e) => setForm({ ...form, api_key_index: Number(e.target.value) })}
                className="bg-surface-2/80 border border-border-default rounded-lg px-3 py-2 text-[13px] font-mono text-text-primary hover:border-border-hover focus:border-accent/40 focus:outline-none transition-all w-20 [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none"
              />
            </div>
            <div>
              <label className="text-[10px] text-text-muted uppercase tracking-[0.12em] block mb-1.5 font-mono">
                Account Index
              </label>
              <input
                type="number"
                value={form.account_index}
                onChange={(e) => setForm({ ...form, account_index: Number(e.target.value) })}
                className="bg-surface-2/80 border border-border-default rounded-lg px-3 py-2 text-[13px] font-mono text-text-primary hover:border-border-hover focus:border-accent/40 focus:outline-none transition-all w-20 [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none"
              />
            </div>
            <div>
              <label className="text-[10px] text-text-muted uppercase tracking-[0.12em] block mb-1.5 font-mono">
                Private Key
              </label>
              <input
                type="password"
                value={form.private_key}
                onChange={(e) => setForm({ ...form, private_key: e.target.value })}
                placeholder="0x..."
                className="bg-surface-2/80 border border-border-default rounded-lg px-3 py-2 text-[13px] font-mono text-text-primary placeholder:text-text-muted/30 hover:border-border-hover focus:border-accent/40 focus:outline-none transition-all w-80"
              />
            </div>
          </div>
          {error && (
            <div className="bg-negative/8 border border-negative/20 rounded-lg px-3.5 py-2.5 text-negative text-[12px] font-mono">
              {error}
            </div>
          )}
          <div className="flex gap-2 pt-1">
            <button
              onClick={() => { setError(""); createMut.mutate(form); }}
              disabled={!form.private_key}
              className="bg-accent/90 hover:bg-accent disabled:opacity-40 text-surface-0 px-5 py-2.5 rounded-lg text-[13px] font-semibold transition-all shadow-lg shadow-accent/10 hover:shadow-accent/20 min-h-[44px] sm:min-h-0"
            >
              Save
            </button>
            <button
              onClick={() => { setShowForm(false); setError(""); }}
              className="bg-surface-2 hover:bg-surface-3 text-text-secondary px-5 py-2.5 rounded-lg text-[13px] font-medium transition-colors min-h-[44px] sm:min-h-0"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Credentials list */}
      <div className="space-y-2">
        {creds?.map((cred) => (
          <div
            key={cred.id}
            className="bg-surface-1 border border-border-default rounded-xl px-5 py-4 card-hover"
          >
            <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
              <div>
                <div className="flex items-center gap-2.5">
                  <div className="w-7 h-7 rounded-lg bg-accent/8 border border-accent/15 flex items-center justify-center">
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-accent">
                      <path d="M15 7a2 2 0 012 2m4 0a6 6 0 01-7.743 5.743L11 17H9v2H7v2H4a1 1 0 01-1-1v-2.586a1 1 0 01.293-.707l5.964-5.964A6 6 0 1121 9z" />
                    </svg>
                  </div>
                  <span className="text-sm font-medium text-text-primary">{cred.name}</span>
                  <StatusBadge status={cred.is_active ? "active" : "paused"} />
                </div>
                <p className="text-[11px] text-text-muted font-mono mt-2 ml-9.5">
                  {cred.lighter_host}
                  <span className="text-border-hover mx-2">|</span>
                  Key #{cred.api_key_index}
                  <span className="text-border-hover mx-2">|</span>
                  Account #{cred.account_index}
                </p>
              </div>
              <div className="flex gap-1.5 ml-9.5 sm:ml-0">
                <button
                  onClick={() => testMut.mutate(cred.id)}
                  disabled={testMut.isPending}
                  className="text-[11px] font-mono bg-surface-2 hover:bg-surface-3 border border-border-default hover:border-border-hover text-text-secondary hover:text-text-primary px-3 py-2 rounded-lg transition-all min-h-[44px] sm:min-h-0"
                >
                  {testMut.isPending ? "TESTING..." : "TEST"}
                </button>
                <button
                  onClick={() => {
                    if (confirm("Delete this credential?"))
                      deleteMut.mutate(cred.id);
                  }}
                  className="text-[11px] font-mono text-negative hover:bg-negative/8 border border-transparent hover:border-negative/20 px-3 py-2 rounded-lg transition-all min-h-[44px] sm:min-h-0"
                >
                  DELETE
                </button>
              </div>
            </div>
          </div>
        ))}
        {(!creds || creds.length === 0) && (
          <div className="bg-surface-1 border border-border-default rounded-xl py-16 text-center">
            <div className="w-10 h-10 rounded-xl bg-surface-2 border border-border-default flex items-center justify-center mx-auto mb-3">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="text-text-muted">
                <path d="M15 7a2 2 0 012 2m4 0a6 6 0 01-7.743 5.743L11 17H9v2H7v2H4a1 1 0 01-1-1v-2.586a1 1 0 01.293-.707l5.964-5.964A6 6 0 1121 9z" />
              </svg>
            </div>
            <p className="text-sm text-text-muted">No credentials configured.</p>
            <button
              onClick={() => setShowForm(true)}
              className="text-accent hover:text-accent-hover text-sm mt-2 inline-block font-medium"
            >
              Add your first key
            </button>
          </div>
        )}
        {testMut.data && (
          <div className="bg-surface-2/50 border border-border-default rounded-xl p-4 text-xs font-mono text-text-secondary">
            <pre className="overflow-x-auto">{JSON.stringify(testMut.data.data, null, 2)}</pre>
          </div>
        )}
      </div>
    </div>
  );
}
