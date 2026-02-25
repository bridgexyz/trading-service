import { useState } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api from "../api/client";
import { useAuth } from "../contexts/AuthContext";
import type { SchedulerStatus } from "../types";

const navItems = [
  { to: "/", label: "Dashboard", icon: "M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-4 0h4" },
  { to: "/pairs", label: "Pairs", icon: "M8 7h12m0 0l-4-4m4 4l-4 4m0 5H4m0 0l4 4m-4-4l4-4" },
  { to: "/logs", label: "Logs", icon: "M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" },
  { to: "/credentials", label: "Keys", icon: "M15 7a2 2 0 012 2m4 0a6 6 0 01-7.743 5.743L11 17H9v2H7v2H4a1 1 0 01-1-1v-2.586a1 1 0 01.293-.707l5.964-5.964A6 6 0 1121 9z" },
];

function NavIcon({ d }: { d: string }) {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d={d} />
    </svg>
  );
}

export default function Layout({ children }: { children: React.ReactNode }) {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [stopModalOpen, setStopModalOpen] = useState(false);
  const [closePositions, setClosePositions] = useState(true);
  const [disablePairs, setDisablePairs] = useState(true);
  const { logout } = useAuth();
  const qc = useQueryClient();
  const location = useLocation();

  const { data: scheduler } = useQuery<SchedulerStatus>({
    queryKey: ["scheduler"],
    queryFn: () => api.get("/system/scheduler").then((r) => r.data),
  });

  const emergencyMut = useMutation({
    mutationFn: () =>
      api.post("/system/emergency-stop", {
        close_positions: closePositions,
        disable_pairs: disablePairs,
      }),
    onSuccess: () => {
      setStopModalOpen(false);
      qc.invalidateQueries();
    },
  });

  return (
    <div className="min-h-screen flex flex-col bg-surface-0">
      {/* Header */}
      <header className="h-12 border-b border-border-default bg-surface-1/80 backdrop-blur-xl flex items-center px-4 md:px-5 shrink-0 relative scanline z-20">
        {/* Logo */}
        <div className="flex items-center gap-2 mr-6">
          <div className="w-6 h-6 rounded bg-accent/10 border border-accent/20 flex items-center justify-center">
            <svg width="12" height="12" viewBox="0 0 16 16" fill="none">
              <path d="M2 14L8 2L14 14" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-accent" />
              <path d="M5 9.5H11" stroke="currentColor" strokeWidth="2" strokeLinecap="round" className="text-accent" />
            </svg>
          </div>
          <div className="flex items-baseline gap-1.5">
            <span className="text-[13px] font-semibold tracking-tight text-text-primary">
              LIGHTER
            </span>
            <span className="text-[9px] font-mono text-text-muted tracking-[0.2em]">
              TRADE
            </span>
          </div>
        </div>

        {/* Desktop nav */}
        <nav className="hidden md:flex items-center gap-0.5">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === "/"}
              className={({ isActive }) =>
                `flex items-center gap-1.5 px-3 py-1.5 rounded text-[12px] font-medium tracking-wide transition-all duration-150 ${
                  isActive
                    ? "bg-accent/10 text-accent border border-accent/15"
                    : "text-text-secondary hover:text-text-primary hover:bg-surface-2 border border-transparent"
                }`
              }
            >
              <NavIcon d={item.icon} />
              {item.label}
            </NavLink>
          ))}
        </nav>

        {/* Right side */}
        <div className="ml-auto flex items-center gap-2.5">
          {/* Emergency stop */}
          <button
            onClick={() => setStopModalOpen(true)}
            className="hidden md:flex items-center gap-1.5 bg-negative/8 hover:bg-negative/15 text-negative border border-negative/20 hover:border-negative/40 px-2.5 py-1 rounded text-[11px] font-semibold tracking-wide transition-all"
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
              <path d="M18 6L6 18M6 6l12 12" />
            </svg>
            STOP
          </button>

          {/* Scheduler status */}
          <div className="flex items-center gap-1.5 text-[11px] text-text-secondary font-mono px-2 py-1 bg-surface-2/50 rounded border border-border-default">
            <span
              className={`w-1.5 h-1.5 rounded-full transition-all ${
                scheduler?.running
                  ? "bg-accent shadow-[0_0_8px_var(--color-accent)]"
                  : "bg-negative shadow-[0_0_8px_var(--color-negative)]"
              }`}
            />
            {scheduler?.running
              ? `${scheduler.job_count} JOBS`
              : "OFFLINE"}
          </div>

          {/* Logout */}
          <button
            onClick={logout}
            className="hidden md:block text-[11px] text-text-muted hover:text-text-secondary transition-colors font-mono tracking-wide"
          >
            EXIT
          </button>

          {/* Mobile hamburger */}
          <button
            onClick={() => setDrawerOpen(true)}
            className="md:hidden p-2 -mr-2 min-h-[44px] min-w-[44px] flex items-center justify-center text-text-secondary hover:text-text-primary"
            aria-label="Open menu"
          >
            <svg width="18" height="18" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
              <path d="M3 5h14M3 10h14M3 15h14" />
            </svg>
          </button>
        </div>
      </header>

      {/* Mobile drawer overlay */}
      {drawerOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/60 backdrop-blur-sm md:hidden"
          onClick={() => setDrawerOpen(false)}
        />
      )}

      {/* Mobile drawer */}
      <div
        className={`fixed top-0 right-0 z-50 h-full w-72 bg-surface-1 border-l border-border-default transform transition-transform duration-250 ease-out md:hidden ${
          drawerOpen ? "translate-x-0" : "translate-x-full"
        }`}
      >
        <div className="flex items-center justify-between px-5 py-4 border-b border-border-default">
          <span className="text-xs font-mono text-text-muted tracking-[0.2em] uppercase">Navigation</span>
          <button
            onClick={() => setDrawerOpen(false)}
            className="p-2 min-h-[44px] min-w-[44px] flex items-center justify-center text-text-secondary hover:text-text-primary"
            aria-label="Close menu"
          >
            <svg width="16" height="16" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
              <path d="M4 4l10 10M14 4L4 14" />
            </svg>
          </button>
        </div>
        <nav className="p-3 space-y-0.5">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === "/"}
              onClick={() => setDrawerOpen(false)}
              className={({ isActive }) =>
                `flex items-center gap-2.5 px-3 py-3 rounded text-[13px] font-medium transition-all min-h-[44px] ${
                  isActive
                    ? "bg-accent/10 text-accent"
                    : "text-text-secondary hover:text-text-primary hover:bg-surface-2"
                }`
              }
            >
              <NavIcon d={item.icon} />
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="absolute bottom-0 left-0 right-0 px-5 py-4 border-t border-border-default space-y-3">
          <div className="flex items-center gap-1.5 text-[11px] text-text-secondary font-mono">
            <span
              className={`w-1.5 h-1.5 rounded-full ${
                scheduler?.running ? "bg-accent" : "bg-negative"
              }`}
            />
            {scheduler?.running
              ? `Scheduler: ${scheduler.job_count} jobs`
              : "Scheduler: offline"}
          </div>
          <button
            onClick={() => { setDrawerOpen(false); logout(); }}
            className="text-[12px] text-text-muted hover:text-text-secondary transition-colors font-mono tracking-wide min-h-[44px]"
          >
            EXIT
          </button>
        </div>
      </div>

      {/* Mobile emergency stop FAB */}
      <button
        onClick={() => setStopModalOpen(true)}
        className="md:hidden fixed bottom-6 right-6 z-30 bg-negative/90 hover:bg-negative text-white w-13 h-13 rounded-xl shadow-lg shadow-negative/20 flex items-center justify-center active:scale-95 transition-all border border-negative/40"
        aria-label="Emergency Stop"
      >
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
          <path d="M18 6L6 18M6 6l12 12" />
        </svg>
      </button>

      {/* Emergency stop modal */}
      {stopModalOpen && (
        <>
          <div
            className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm"
            onClick={() => !emergencyMut.isPending && setStopModalOpen(false)}
          />
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
            <div className="bg-surface-1 border border-negative/20 rounded-xl p-6 w-full max-w-sm space-y-4 shadow-2xl shadow-negative/5 animate-fade-up">
              <div className="flex items-center gap-2">
                <div className="w-8 h-8 rounded-lg bg-negative/10 border border-negative/20 flex items-center justify-center">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" className="text-negative">
                    <path d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4.5c-.77-.833-2.694-.833-3.464 0L3.34 16.5c-.77.833.192 2.5 1.732 2.5z" />
                  </svg>
                </div>
                <h3 className="text-base font-semibold text-negative">
                  Emergency Stop
                </h3>
              </div>
              <p className="text-[13px] text-text-secondary leading-relaxed">
                This will immediately attempt to close all positions and halt trading operations.
              </p>

              <div className="space-y-2">
                <label className="flex items-center gap-2.5 text-[13px] text-text-primary cursor-pointer min-h-[44px] px-3 py-2 rounded-lg bg-surface-2/50 border border-border-default hover:border-border-hover transition-colors">
                  <input
                    type="checkbox"
                    checked={closePositions}
                    onChange={(e) => setClosePositions(e.target.checked)}
                    className="w-4 h-4 rounded accent-negative"
                  />
                  Close all open positions
                </label>
                <label className="flex items-center gap-2.5 text-[13px] text-text-primary cursor-pointer min-h-[44px] px-3 py-2 rounded-lg bg-surface-2/50 border border-border-default hover:border-border-hover transition-colors">
                  <input
                    type="checkbox"
                    checked={disablePairs}
                    onChange={(e) => setDisablePairs(e.target.checked)}
                    className="w-4 h-4 rounded accent-negative"
                  />
                  Disable all trading pairs
                </label>
              </div>

              {emergencyMut.isError && (
                <p className="text-negative text-xs font-mono">
                  Error: {(emergencyMut.error as any)?.message || "Failed"}
                </p>
              )}
              {emergencyMut.isSuccess && (
                <p className="text-accent text-xs font-mono">
                  Done: {(emergencyMut.data as any)?.data?.positions_closed ?? 0} positions closed,{" "}
                  {(emergencyMut.data as any)?.data?.pairs_disabled ?? 0} pairs disabled
                </p>
              )}

              <div className="flex gap-2 pt-1">
                <button
                  onClick={() => emergencyMut.mutate()}
                  disabled={emergencyMut.isPending || (!closePositions && !disablePairs)}
                  className="bg-negative hover:bg-negative/80 text-white px-4 py-2.5 rounded-lg text-[13px] font-semibold transition-all disabled:opacity-50 min-h-[44px] flex-1"
                >
                  {emergencyMut.isPending ? "Stopping..." : "Confirm Stop"}
                </button>
                <button
                  onClick={() => setStopModalOpen(false)}
                  disabled={emergencyMut.isPending}
                  className="bg-surface-2 hover:bg-surface-3 text-text-secondary px-4 py-2.5 rounded-lg text-[13px] font-medium transition-colors min-h-[44px]"
                >
                  Cancel
                </button>
              </div>
            </div>
          </div>
        </>
      )}

      {/* Main content */}
      <main key={location.pathname} className="flex-1 overflow-auto p-4 md:p-6 animate-fade-up">
        {children}
      </main>
    </div>
  );
}
