import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import api from "../api/client";
import StatCard from "../components/StatCard";
import StatusBadge from "../components/StatusBadge";
import type { DashboardSummary, TradingPair, ExchangePosition } from "../types";

export default function DashboardPage() {
  const { data: summary } = useQuery<DashboardSummary>({
    queryKey: ["dashboard"],
    queryFn: () => api.get("/dashboard/summary").then((r) => r.data),
  });

  const { data: pairs } = useQuery<TradingPair[]>({
    queryKey: ["pairs"],
    queryFn: () => api.get("/pairs").then((r) => r.data),
  });

  const {
    data: positions,
    isFetching: positionsFetching,
    refetch: refetchPositions,
  } = useQuery<ExchangePosition[]>({
    queryKey: ["positions-exchange"],
    queryFn: () => api.get("/positions/exchange").then((r) => r.data),
  });

  return (
    <div className="space-y-6 max-w-7xl">
      {/* Page header */}
      <div className="flex items-baseline gap-3">
        <h2 className="text-xl font-semibold tracking-tight">Overview</h2>
        <span className="text-[10px] font-mono text-text-secondary tracking-[0.2em]">DASHBOARD</span>
      </div>

      {/* Stats */}
      {summary && (
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
          <StatCard label="Active Pairs" value={summary.active_pairs} />
          <StatCard label="Open Positions" value={summary.open_positions} />
          <StatCard label="Total Trades" value={summary.total_trades} />
          <StatCard
            label="Total PnL"
            value={`$${summary.total_pnl.toFixed(2)}`}
            color={summary.total_pnl >= 0 ? "text-accent" : "text-negative"}
          />
          <StatCard
            label="Win Rate"
            value={`${summary.win_rate}%`}
            color={summary.win_rate >= 50 ? "text-accent" : "text-text-secondary"}
          />
        </div>
      )}

      {/* Pair table */}
      <div className="bg-surface-1 border border-border-default rounded-xl overflow-hidden">
        <div className="px-5 py-3.5 border-b border-border-default flex items-center justify-between">
          <h3 className="text-[11px] font-mono font-medium text-text-secondary uppercase tracking-[0.15em]">
            Trading Pairs
          </h3>
          <Link
            to="/pairs"
            className="text-[11px] text-accent hover:text-accent-hover transition-colors font-medium"
          >
            Manage
          </Link>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-[13px]">
            <thead>
              <tr className="border-b border-border-default">
                <th className="text-left px-5 py-2.5 text-[10px] font-mono font-medium text-text-secondary uppercase tracking-[0.15em]">Pair</th>
                <th className="text-left px-5 py-2.5 text-[10px] font-mono font-medium text-text-secondary uppercase tracking-[0.15em]">Assets</th>
                <th className="text-right px-5 py-2.5 text-[10px] font-mono font-medium text-text-secondary uppercase tracking-[0.15em]">Equity</th>
                <th className="text-center px-5 py-2.5 text-[10px] font-mono font-medium text-text-secondary uppercase tracking-[0.15em]">Interval</th>
                <th className="text-center px-5 py-2.5 text-[10px] font-mono font-medium text-text-secondary uppercase tracking-[0.15em]">Leverage</th>
                <th className="text-center px-5 py-2.5 text-[10px] font-mono font-medium text-text-secondary uppercase tracking-[0.15em]">Entry Z</th>
                <th className="text-center px-5 py-2.5 text-[10px] font-mono font-medium text-text-secondary uppercase tracking-[0.15em]">Status</th>
              </tr>
            </thead>
            <tbody>
              {pairs?.map((pair) => (
                <tr
                  key={pair.id}
                  className="border-b border-border-default/50 hover:bg-surface-2/30 cursor-pointer group"
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
                  <td className="px-5 py-3 text-right font-mono text-text-primary">
                    ${pair.current_equity.toFixed(0)}
                  </td>
                  <td className="px-5 py-3 text-center text-text-secondary font-mono text-xs">
                    {pair.schedule_interval}
                  </td>
                  <td className="px-5 py-3 text-center text-text-secondary font-mono text-xs">
                    {pair.leverage}x
                  </td>
                  <td className="px-5 py-3 text-center text-text-secondary font-mono text-xs">
                    {pair.entry_z}
                  </td>
                  <td className="px-5 py-3 text-center">
                    <StatusBadge status={pair.is_enabled ? "active" : "paused"} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {(!pairs || pairs.length === 0) && (
          <div className="text-center text-text-muted py-16">
            <p className="text-sm">No trading pairs configured.</p>
            <Link
              to="/pairs"
              className="text-accent hover:text-accent-hover text-sm mt-2 inline-block"
            >
              Add your first pair
            </Link>
          </div>
        )}
      </div>

      {/* Positions table — live from exchange */}
      <div className="bg-surface-1 border border-border-default rounded-xl overflow-hidden">
        <div className="px-5 py-3.5 border-b border-border-default flex items-center justify-between">
          <h3 className="text-[11px] font-mono font-medium text-text-secondary uppercase tracking-[0.15em]">
            Exchange Positions
          </h3>
          <button
            onClick={() => refetchPositions()}
            disabled={positionsFetching}
            className="text-[11px] text-accent hover:text-accent-hover transition-colors font-medium disabled:opacity-50"
          >
            {positionsFetching ? "Updating..." : "Update"}
          </button>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-[13px]">
            <thead>
              <tr className="border-b border-border-default">
                <th className="text-left px-5 py-2.5 text-[10px] font-mono font-medium text-text-secondary uppercase tracking-[0.15em]">Market</th>
                <th className="text-center px-5 py-2.5 text-[10px] font-mono font-medium text-text-secondary uppercase tracking-[0.15em]">Side</th>
                <th className="text-right px-5 py-2.5 text-[10px] font-mono font-medium text-text-secondary uppercase tracking-[0.15em]">Size</th>
                <th className="text-right px-5 py-2.5 text-[10px] font-mono font-medium text-text-secondary uppercase tracking-[0.15em]">Entry Price</th>
                <th className="text-right px-5 py-2.5 text-[10px] font-mono font-medium text-text-secondary uppercase tracking-[0.15em]">Current Price</th>
                <th className="text-right px-5 py-2.5 text-[10px] font-mono font-medium text-text-secondary uppercase tracking-[0.15em]">Notional</th>
                <th className="text-right px-5 py-2.5 text-[10px] font-mono font-medium text-text-secondary uppercase tracking-[0.15em]">P&L ($)</th>
                <th className="text-right px-5 py-2.5 text-[10px] font-mono font-medium text-text-secondary uppercase tracking-[0.15em]">P&L (%)</th>
              </tr>
            </thead>
            <tbody>
              {positions?.map((pos) => (
                <tr
                  key={pos.market_index}
                  className="border-b border-border-default/50 hover:bg-surface-2/30"
                >
                  <td className="px-5 py-3 text-text-primary font-medium">
                    {pos.symbol}
                  </td>
                  <td className="px-5 py-3 text-center">
                    <span className={pos.side === "long" ? "text-accent" : "text-negative"}>
                      {pos.side === "long" ? "Long" : "Short"}
                    </span>
                  </td>
                  <td className="px-5 py-3 text-right font-mono text-xs text-text-primary">
                    {pos.size < 1 ? pos.size.toFixed(6) : pos.size.toFixed(4)}
                  </td>
                  <td className="px-5 py-3 text-right font-mono text-xs text-text-secondary">
                    {pos.entry_price < 0.01 ? pos.entry_price.toFixed(6) : pos.entry_price.toFixed(2)}
                  </td>
                  <td className="px-5 py-3 text-right font-mono text-xs text-text-primary">
                    {pos.current_price < 0.01 ? pos.current_price.toFixed(6) : pos.current_price.toFixed(2)}
                  </td>
                  <td className="px-5 py-3 text-right font-mono text-xs text-text-secondary">
                    ${pos.notional.toFixed(2)}
                  </td>
                  <td className={`px-5 py-3 text-right font-mono text-xs ${pos.unrealized_pnl >= 0 ? "text-accent" : "text-negative"}`}>
                    {pos.unrealized_pnl >= 0 ? "+" : ""}{pos.unrealized_pnl.toFixed(2)}
                  </td>
                  <td className={`px-5 py-3 text-right font-mono text-xs ${pos.unrealized_pnl_pct >= 0 ? "text-accent" : "text-negative"}`}>
                    {pos.unrealized_pnl_pct >= 0 ? "+" : ""}{pos.unrealized_pnl_pct.toFixed(2)}%
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {(!positions || positions.length === 0) && (
          <p className="text-center text-text-muted py-12 text-sm">
            No open positions on exchange.
          </p>
        )}
      </div>
    </div>
  );
}
