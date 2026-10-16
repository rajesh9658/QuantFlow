import React, { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
  BarChart,
  Bar,
} from "recharts";
import { Search, ArrowUpDown, PieChart as PieIcon, TrendingDown } from "lucide-react";
import { apiClient } from "../api/client";
import { endpoints } from "../config/endpoints";
import { usePortfolioStore } from "../state/portfolioStore";
import { PortfolioSnapshot, EquityCurvePoint } from "../types/dashboard";

type SortField = "symbol" | "quantity" | "avg_entry_price" | "unrealized_pnl";

export function PortfolioPage() {
  const liveSnapshot = usePortfolioStore((s) => s.snapshot);
  const liveHistory = usePortfolioStore((s) => s.history);

  const { data: serverSnapshot } = useQuery<PortfolioSnapshot>({
    queryKey: ["portfolio"],
    queryFn: () => apiClient(endpoints.portfolio.snapshot()),
  });

  const { data: serverHistory } = useQuery<EquityCurvePoint[]>({
    queryKey: ["portfolio", "history"],
    queryFn: () => apiClient(endpoints.portfolio.history()),
  });

  const snapshot = serverSnapshot || liveSnapshot;
  const history = liveHistory.length > 0 ? liveHistory : serverHistory || [];

  const [search, setSearch] = useState("");
  const [sortField, setSortField] = useState<SortField>("symbol");
  const [sortAsc, setSortAsc] = useState(true);

  const filteredPositions = useMemo(() => {
    return snapshot.positions
      .filter((p) => p.symbol.toLowerCase().includes(search.toLowerCase()))
      .sort((a, b) => {
        let valA = a[sortField];
        let valB = b[sortField];
        if (typeof valA === "string") {
          return sortAsc ? valA.localeCompare(valB as string) : (valB as string).localeCompare(valA);
        }
        return sortAsc ? (valA as number) - (valB as number) : (valB as number) - (valA as number);
      });
  }, [snapshot.positions, search, sortField, sortAsc]);

  const toggleSort = (field: SortField) => {
    if (sortField === field) {
      setSortAsc(!sortAsc);
    } else {
      setSortField(field);
      setSortAsc(true);
    }
  };

  const pnlBreakdown = [
    { name: "Realized PnL", value: snapshot.realized_pnl },
    { name: "Unrealized PnL", value: snapshot.unrealized_pnl },
  ];

  return (
    <div className="space-y-6">
      {/* Header Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="p-4 rounded-xl bg-slate-900 border border-slate-800">
          <div className="text-xs font-mono text-slate-400 mb-1">TOTAL EQUITY</div>
          <div className="text-2xl font-bold font-mono text-white">
            ${snapshot.total_equity.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </div>
          <div className="text-xs font-mono text-slate-500 mt-1">
            Cash: ${snapshot.cash.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </div>
        </div>

        <div className="p-4 rounded-xl bg-slate-900 border border-slate-800">
          <div className="text-xs font-mono text-slate-400 mb-1">TOTAL EXPOSURE</div>
          <div className="text-2xl font-bold font-mono text-cyan-400">
            ${snapshot.total_exposure.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </div>
          <div className="text-xs font-mono text-slate-500 mt-1">
            Exposure Ratio: {snapshot.total_equity > 0 ? ((snapshot.total_exposure / snapshot.total_equity) * 100).toFixed(1) : 0}%
          </div>
        </div>

        <div className="p-4 rounded-xl bg-slate-900 border border-slate-800">
          <div className="text-xs font-mono text-slate-400 mb-1">AGGREGATE PnL</div>
          <div
            className={`text-2xl font-bold font-mono ${
              snapshot.realized_pnl + snapshot.unrealized_pnl >= 0 ? "text-emerald-400" : "text-rose-400"
            }`}
          >
            ${(snapshot.realized_pnl + snapshot.unrealized_pnl).toFixed(2)}
          </div>
          <div className="text-xs font-mono text-slate-500 mt-1">
            Realized: ${snapshot.realized_pnl.toFixed(2)} • Unrealized: ${snapshot.unrealized_pnl.toFixed(2)}
          </div>
        </div>
      </div>

      {/* Equity & Drawdown Chart Overlay */}
      <div className="p-5 rounded-xl bg-slate-900 border border-slate-800">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-sm font-bold font-mono text-slate-200">
            EQUITY CURVE & DRAWDOWN OVERLAY
          </h2>
          <span className="text-xs font-mono text-slate-500">Continuous telemetry feed</span>
        </div>
        <div className="h-64 w-full">
          {history.length > 0 ? (
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={history}>
                <defs>
                  <linearGradient id="equityGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#10b981" stopOpacity={0.4} />
                    <stop offset="95%" stopColor="#10b981" stopOpacity={0} />
                  </linearGradient>
                </defs>
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
                />
                <Area
                  type="monotone"
                  dataKey="equity"
                  stroke="#10b981"
                  fillOpacity={1}
                  fill="url(#equityGrad)"
                  isAnimationActive={false} // non-configurable: avoid re-render stutter
                />
              </AreaChart>
            </ResponsiveContainer>
          ) : (
            <div className="h-full flex items-center justify-center text-xs font-mono text-slate-500">
              No equity history loaded
            </div>
          )}
        </div>
      </div>

      {/* Positions Table with Sorting & Filter */}
      <div className="p-5 rounded-xl bg-slate-900 border border-slate-800">
        <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 mb-4">
          <h2 className="text-sm font-bold font-mono text-slate-200">
            ACTIVE POSITIONS ({filteredPositions.length})
          </h2>

          <div className="relative w-full sm:w-64">
            <Search className="absolute left-3 top-2.5 h-4 w-4 text-slate-500" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Filter by symbol..."
              className="w-full pl-9 pr-3 py-1.5 bg-slate-950 border border-slate-800 rounded-lg text-xs font-mono text-slate-200 placeholder-slate-500 focus:outline-none focus:border-emerald-500"
            />
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs font-mono">
            <thead>
              <tr className="border-b border-slate-800 text-slate-400">
                <th
                  onClick={() => toggleSort("symbol")}
                  className="pb-2 cursor-pointer hover:text-white"
                >
                  <div className="flex items-center space-x-1">
                    <span>SYMBOL</span>
                    <ArrowUpDown className="h-3 w-3" />
                  </div>
                </th>
                <th
                  onClick={() => toggleSort("quantity")}
                  className="pb-2 cursor-pointer hover:text-white"
                >
                  <div className="flex items-center space-x-1">
                    <span>QUANTITY</span>
                    <ArrowUpDown className="h-3 w-3" />
                  </div>
                </th>
                <th
                  onClick={() => toggleSort("avg_entry_price")}
                  className="pb-2 cursor-pointer hover:text-white"
                >
                  <div className="flex items-center space-x-1">
                    <span>AVG ENTRY</span>
                    <ArrowUpDown className="h-3 w-3" />
                  </div>
                </th>
                <th
                  onClick={() => toggleSort("unrealized_pnl")}
                  className="pb-2 cursor-pointer hover:text-white text-right"
                >
                  <div className="flex items-center justify-end space-x-1">
                    <span>UNREALIZED PnL</span>
                    <ArrowUpDown className="h-3 w-3" />
                  </div>
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60">
              {filteredPositions.length > 0 ? (
                filteredPositions.map((pos) => (
                  <tr key={pos.symbol} className="hover:bg-slate-800/30">
                    <td className="py-3 font-bold text-slate-200">{pos.symbol}</td>
                    <td className="py-3 text-slate-300">{pos.quantity}</td>
                    <td className="py-3 text-slate-400">${pos.avg_entry_price.toLocaleString()}</td>
                    <td
                      className={`py-3 text-right font-bold ${
                        pos.unrealized_pnl >= 0 ? "text-emerald-400" : "text-rose-400"
                      }`}
                    >
                      {pos.unrealized_pnl >= 0 ? "+" : ""}${pos.unrealized_pnl.toFixed(2)}
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={4} className="py-8 text-center text-slate-500">
                    No matching positions found
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
