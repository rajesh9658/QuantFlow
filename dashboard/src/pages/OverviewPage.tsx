import React from "react";
import { useQuery } from "@tanstack/react-query";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
} from "recharts";
import { TrendingUp, Shield, Activity, DollarSign, ArrowUpRight, ArrowDownRight } from "lucide-react";
import { apiClient } from "../api/client";
import { endpoints } from "../config/endpoints";
import { usePortfolioStore } from "../state/portfolioStore";
import { useRiskStore } from "../state/riskStore";
import { useExchangeStore } from "../state/exchangeStore";
import { PortfolioSnapshot, EquityCurvePoint, AnalyticsSnapshot } from "../types/dashboard";

export function OverviewPage() {
  // Live WS updates from Zustand
  const liveSnapshot = usePortfolioStore((s) => s.snapshot);
  const liveHistory = usePortfolioStore((s) => s.history);
  const riskStatus = useRiskStore((s) => s.status);
  const exchanges = useExchangeStore((s) => Object.values(s.exchanges));

  // REST queries for initial/authoritative server state
  const { data: serverSnapshot } = useQuery<PortfolioSnapshot>({
    queryKey: ["portfolio"],
    queryFn: () => apiClient(endpoints.portfolio.snapshot()),
  });

  const { data: serverHistory } = useQuery<EquityCurvePoint[]>({
    queryKey: ["portfolio", "history"],
    queryFn: () => apiClient(endpoints.portfolio.history()),
  });

  const { data: metrics } = useQuery<AnalyticsSnapshot>({
    queryKey: ["metrics", "summary"],
    queryFn: () => apiClient(endpoints.metrics.summary()),
  });

  const snapshot = serverSnapshot || liveSnapshot;
  const historyData = liveHistory.length > 0 ? liveHistory : serverHistory || [];

  const isProfitable = snapshot.realized_pnl + snapshot.unrealized_pnl >= 0;

  return (
    <div className="space-y-6">
      {/* Top Banner / Metrics Overview */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* Equity Card */}
        <div className="p-4 rounded-xl bg-slate-900 border border-slate-800">
          <div className="flex items-center justify-between text-slate-400 text-xs font-mono mb-2">
            <span>TOTAL EQUITY</span>
            <DollarSign className="h-4 w-4 text-emerald-400" />
          </div>
          <div className="text-2xl font-bold font-mono text-slate-100">
            ${snapshot.total_equity.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </div>
          <div className="text-xs font-mono text-slate-500 mt-1">
            Cash: ${snapshot.cash.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </div>
        </div>

        {/* PnL Card */}
        <div className="p-4 rounded-xl bg-slate-900 border border-slate-800">
          <div className="flex items-center justify-between text-slate-400 text-xs font-mono mb-2">
            <span>TOTAL PnL (UNREALIZED)</span>
            {isProfitable ? (
              <ArrowUpRight className="h-4 w-4 text-emerald-400" />
            ) : (
              <ArrowDownRight className="h-4 w-4 text-rose-400" />
            )}
          </div>
          <div className={`text-2xl font-bold font-mono ${snapshot.unrealized_pnl >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
            {snapshot.unrealized_pnl >= 0 ? "+" : ""}${snapshot.unrealized_pnl.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </div>
          <div className="text-xs font-mono text-slate-500 mt-1">
            Realized: ${snapshot.realized_pnl.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </div>
        </div>

        {/* Exposure Card */}
        <div className="p-4 rounded-xl bg-slate-900 border border-slate-800">
          <div className="flex items-center justify-between text-slate-400 text-xs font-mono mb-2">
            <span>CURRENT EXPOSURE</span>
            <Activity className="h-4 w-4 text-cyan-400" />
          </div>
          <div className="text-2xl font-bold font-mono text-cyan-400">
            ${snapshot.total_exposure.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </div>
          <div className="text-xs font-mono text-slate-500 mt-1">
            Max Limit: ${riskStatus.max_exposure.toLocaleString()}
          </div>
        </div>

        {/* Risk / System Health */}
        <div className="p-4 rounded-xl bg-slate-900 border border-slate-800">
          <div className="flex items-center justify-between text-slate-400 text-xs font-mono mb-2">
            <span>RISK ENGINE STATE</span>
            <Shield className="h-4 w-4 text-indigo-400" />
          </div>
          <div className="flex items-center space-x-2 mt-1">
            <span
              className={`px-2 py-0.5 rounded text-xs font-bold font-mono uppercase ${
                riskStatus.emergency_stop
                  ? "bg-rose-500/20 text-rose-400 border border-rose-500/40"
                  : riskStatus.circuit_breaker_active
                  ? "bg-amber-500/20 text-amber-400 border border-amber-500/40"
                  : "bg-emerald-500/20 text-emerald-400 border border-emerald-500/40"
              }`}
            >
              {riskStatus.emergency_stop
                ? "HALTED"
                : riskStatus.circuit_breaker_active
                ? "BREAKER TRIPPED"
                : "NORMAL (ARMED)"}
            </span>
          </div>
          <div className="text-xs font-mono text-slate-500 mt-2">
            Win Rate: {metrics?.win_rate ? `${(metrics.win_rate * 100).toFixed(1)}%` : "N/A"} • Sharpe: {metrics?.sharpe ? metrics.sharpe.toFixed(2) : "N/A"}
          </div>
        </div>
      </div>

      {/* Equity Curve (Recharts) */}
      <div className="p-5 rounded-xl bg-slate-900 border border-slate-800">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center space-x-2">
            <TrendingUp className="h-4 w-4 text-emerald-400" />
            <h2 className="text-sm font-bold font-mono tracking-wide text-slate-200">
              EQUITY CURVE (REAL-TIME TELEMETRY)
            </h2>
          </div>
          <div className="text-xs font-mono text-slate-500">
            Streaming via WebSocket
          </div>
        </div>

        <div className="h-72 w-full">
          {historyData.length > 0 ? (
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={historyData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                <XAxis
                  dataKey="timestamp"
                  tick={{ fill: "#64748b", fontSize: 11 }}
                  tickFormatter={(val: string) => {
                    const d = new Date(val);
                    return isNaN(d.getTime()) ? String(val) : d.toLocaleTimeString();
                  }}
                  stroke="#334155"
                />
                <YAxis
                  domain={["auto", "auto"]}
                  tick={{ fill: "#64748b", fontSize: 11 }}
                  tickFormatter={(val: number) => `$${val.toLocaleString()}`}
                  stroke="#334155"
                />
                <Tooltip
                  contentStyle={{
                    backgroundColor: "#0f172a",
                    borderColor: "#334155",
                    fontSize: "12px",
                    fontFamily: "monospace",
                    borderRadius: "8px",
                  }}
                  formatter={(value: number) => [`$${value.toLocaleString()}`, "Equity"]}
                />
                <Line
                  type="monotone"
                  dataKey="equity"
                  stroke="#10b981"
                  strokeWidth={2}
                  dot={false}
                  isAnimationActive={false} // non-configurable: disable animation for high frequency smoothness
                />
              </LineChart>
            </ResponsiveContainer>
          ) : (
            <div className="h-full flex items-center justify-center text-xs font-mono text-slate-500">
              Awaiting telemetry equity points...
            </div>
          )}
        </div>
      </div>

      {/* Grid: Positions & Exchange Statuses */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Positions Table */}
        <div className="lg:col-span-2 p-5 rounded-xl bg-slate-900 border border-slate-800">
          <h2 className="text-sm font-bold font-mono text-slate-200 mb-4">
            CURRENT POSITIONS ({snapshot.positions.length})
          </h2>
          {snapshot.positions.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs font-mono">
                <thead>
                  <tr className="border-b border-slate-800 text-slate-400">
                    <th className="pb-2">SYMBOL</th>
                    <th className="pb-2">QTY</th>
                    <th className="pb-2">AVG ENTRY</th>
                    <th className="pb-2 text-right">UNREALIZED PnL</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/60">
                  {snapshot.positions.map((pos) => (
                    <tr key={pos.symbol} className="hover:bg-slate-800/30">
                      <td className="py-2.5 font-bold text-slate-200">{pos.symbol}</td>
                      <td className="py-2.5 text-slate-300">{pos.quantity}</td>
                      <td className="py-2.5 text-slate-400">${pos.avg_entry_price.toLocaleString()}</td>
                      <td className={`py-2.5 text-right font-semibold ${pos.unrealized_pnl >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
                        {pos.unrealized_pnl >= 0 ? "+" : ""}${pos.unrealized_pnl.toFixed(2)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="py-8 text-center text-xs font-mono text-slate-500">
              No open positions
            </div>
          )}
        </div>

        {/* Exchange Health Cards */}
        <div className="p-5 rounded-xl bg-slate-900 border border-slate-800">
          <h2 className="text-sm font-bold font-mono text-slate-200 mb-4">
            EXCHANGE ADAPTERS
          </h2>
          <div className="space-y-3">
            {exchanges.length > 0 ? (
              exchanges.map((ex) => (
                <div
                  key={ex.id || ex.name}
                  className="p-3 rounded-lg bg-slate-950 border border-slate-800 flex items-center justify-between text-xs font-mono"
                >
                  <div>
                    <div className="font-bold text-slate-200 uppercase">{ex.name}</div>
                    <div className="text-[11px] text-slate-500">
                      Latency: {ex.latency_ms}ms • Subscribed: {ex.symbols_subscribed?.length || 0}
                    </div>
                  </div>
                  <span
                    className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase ${
                      ex.connected
                        ? "bg-emerald-500/20 text-emerald-400 border border-emerald-500/30"
                        : "bg-rose-500/20 text-rose-400 border border-rose-500/30"
                    }`}
                  >
                    {ex.connected ? "ONLINE" : "OFFLINE"}
                  </span>
                </div>
              ))
            ) : (
              <div className="text-xs font-mono text-slate-500 text-center py-6">
                No exchange adapters reported
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
