import React, { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Download, Filter, ChevronLeft, ChevronRight, X, ArrowUpRight, ArrowDownRight } from "lucide-react";
import { apiClient } from "../api/client";
import { endpoints } from "../config/endpoints";
import { TradeExecution } from "../types/dashboard";

const PAGE_SIZE = 25; // non-configurable: standard table page size

export function TradesPage() {
  const [page, setPage] = useState(0);
  const [symbolFilter, setSymbolFilter] = useState("");
  const [strategyFilter, setStrategyFilter] = useState("");
  const [selectedTrade, setSelectedTrade] = useState<TradeExecution | null>(null);

  const { data: trades = [], isLoading } = useQuery<TradeExecution[]>({
    queryKey: ["trades", { symbol: symbolFilter, strategy: strategyFilter, limit: PAGE_SIZE, offset: page * PAGE_SIZE }],
    queryFn: () =>
      apiClient(
        endpoints.trades({
          symbol: symbolFilter || undefined,
          strategy: strategyFilter || undefined,
          limit: PAGE_SIZE,
          offset: page * PAGE_SIZE,
        })
      ),
  });

  const handleExportCsv = () => {
    if (trades.length === 0) return;
    const headers = ["Fill ID", "Order ID", "Symbol", "Side", "Price", "Quantity", "Commission", "Realized PnL", "Timestamp"];
    const rows = trades.map((t) => [
      t.fill_id,
      t.order_id,
      t.symbol,
      t.side,
      t.price,
      t.quantity,
      t.commission,
      t.realized_pnl,
      t.timestamp_exchange || "",
    ]);
    const csvContent =
      "data:text/csv;charset=utf-8," +
      [headers.join(","), ...rows.map((e) => e.join(","))].join("\n");
    const encodedUri = encodeURI(csvContent);
    const link = document.createElement("a");
    link.setAttribute("href", encodedUri);
    link.setAttribute("download", `trades_export_${new Date().toISOString()}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  return (
    <div className="space-y-6">
      {/* Top Header & Controls */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 p-4 rounded-xl bg-slate-900 border border-slate-800">
        <div className="flex flex-wrap items-center gap-3">
          <input
            type="text"
            placeholder="Filter by Symbol..."
            value={symbolFilter}
            onChange={(e) => {
              setSymbolFilter(e.target.value);
              setPage(0);
            }}
            className="px-3 py-1.5 bg-slate-950 border border-slate-800 rounded-lg text-xs font-mono text-slate-200 placeholder-slate-500 focus:outline-none focus:border-emerald-500"
          />
          <input
            type="text"
            placeholder="Filter by Strategy..."
            value={strategyFilter}
            onChange={(e) => {
              setStrategyFilter(e.target.value);
              setPage(0);
            }}
            className="px-3 py-1.5 bg-slate-950 border border-slate-800 rounded-lg text-xs font-mono text-slate-200 placeholder-slate-500 focus:outline-none focus:border-emerald-500"
          />
        </div>

        <button
          type="button"
          onClick={handleExportCsv}
          disabled={trades.length === 0}
          className="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 disabled:opacity-50 text-slate-200 text-xs font-mono flex items-center space-x-1.5 transition"
        >
          <Download className="h-3.5 w-3.5 text-slate-400" />
          <span>Export CSV</span>
        </button>
      </div>

      {/* Trades Table */}
      <div className="p-5 rounded-xl bg-slate-900 border border-slate-800">
        <h2 className="text-sm font-bold font-mono text-slate-200 mb-4">
          TRADE EXECUTION FILLS
        </h2>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs font-mono">
            <thead>
              <tr className="border-b border-slate-800 text-slate-400">
                <th className="pb-2">FILL ID</th>
                <th className="pb-2">SYMBOL</th>
                <th className="pb-2">SIDE</th>
                <th className="pb-2">PRICE</th>
                <th className="pb-2">QTY</th>
                <th className="pb-2">COMMISSION</th>
                <th className="pb-2 text-right">REALIZED PnL</th>
                <th className="pb-2 text-right">TIMESTAMP</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60">
              {isLoading ? (
                <tr>
                  <td colSpan={8} className="py-8 text-center text-slate-500">
                    Loading execution fills...
                  </td>
                </tr>
              ) : trades.length > 0 ? (
                trades.map((t) => (
                  <tr
                    key={t.fill_id}
                    onClick={() => setSelectedTrade(t)}
                    className="hover:bg-slate-800/50 cursor-pointer transition"
                  >
                    <td className="py-2.5 text-slate-400 font-bold">{t.fill_id.slice(0, 8)}...</td>
                    <td className="py-2.5 font-bold text-slate-200">{t.symbol}</td>
                    <td className="py-2.5">
                      <span
                        className={`px-1.5 py-0.5 rounded text-[10px] font-bold uppercase ${
                          t.side.toLowerCase() === "buy"
                            ? "bg-emerald-500/20 text-emerald-400 border border-emerald-500/30"
                            : "bg-rose-500/20 text-rose-400 border border-rose-500/30"
                        }`}
                      >
                        {t.side}
                      </span>
                    </td>
                    <td className="py-2.5 text-slate-300">${t.price.toLocaleString()}</td>
                    <td className="py-2.5 text-slate-300">{t.quantity}</td>
                    <td className="py-2.5 text-slate-400">${t.commission.toFixed(4)}</td>
                    <td
                      className={`py-2.5 text-right font-bold ${
                        t.realized_pnl >= 0 ? "text-emerald-400" : "text-rose-400"
                      }`}
                    >
                      {t.realized_pnl !== 0
                        ? `${t.realized_pnl > 0 ? "+" : ""}$${t.realized_pnl.toFixed(2)}`
                        : "—"}
                    </td>
                    <td className="py-2.5 text-right text-slate-500">
                      {t.timestamp_exchange ? new Date(t.timestamp_exchange).toLocaleTimeString() : "—"}
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={8} className="py-8 text-center text-slate-500">
                    No trade executions matching filter criteria
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination Controls */}
        <div className="flex items-center justify-between border-t border-slate-800/80 pt-4 mt-4 text-xs font-mono text-slate-400">
          <div>Page {page + 1}</div>
          <div className="flex space-x-2">
            <button
              type="button"
              disabled={page === 0}
              onClick={() => setPage((p) => Math.max(0, p - 1))}
              className="p-1.5 rounded bg-slate-950 border border-slate-800 hover:border-slate-700 disabled:opacity-40"
            >
              <ChevronLeft className="h-4 w-4" />
            </button>
            <button
              type="button"
              disabled={trades.length < PAGE_SIZE}
              onClick={() => setPage((p) => p + 1)}
              className="p-1.5 rounded bg-slate-950 border border-slate-800 hover:border-slate-700 disabled:opacity-40"
            >
              <ChevronRight className="h-4 w-4" />
            </button>
          </div>
        </div>
      </div>

      {/* Trade Detail Drawer */}
      {selectedTrade && (
        <div className="fixed inset-y-0 right-0 z-50 w-full max-w-md bg-slate-900 border-l border-slate-800 p-6 shadow-2xl overflow-y-auto">
          <div className="flex items-center justify-between pb-4 border-b border-slate-800">
            <h3 className="font-bold font-mono text-sm text-slate-100">FILL DETAILS</h3>
            <button
              type="button"
              onClick={() => setSelectedTrade(null)}
              className="text-slate-400 hover:text-white"
            >
              <X className="h-5 w-5" />
            </button>
          </div>

          <div className="space-y-4 py-4 text-xs font-mono">
            <div>
              <div className="text-slate-500">Fill ID</div>
              <div className="text-slate-200 select-all font-semibold">{selectedTrade.fill_id}</div>
            </div>
            <div>
              <div className="text-slate-500">Order ID</div>
              <div className="text-slate-200 select-all font-semibold">{selectedTrade.order_id}</div>
            </div>
            <div>
              <div className="text-slate-500">Symbol</div>
              <div className="text-slate-200 text-sm font-bold">{selectedTrade.symbol}</div>
            </div>
            <div>
              <div className="text-slate-500">Side</div>
              <div className="uppercase font-bold text-slate-200">{selectedTrade.side}</div>
            </div>
            <div>
              <div className="text-slate-500">Execution Price</div>
              <div className="text-slate-200">${selectedTrade.price.toLocaleString()}</div>
            </div>
            <div>
              <div className="text-slate-500">Executed Quantity</div>
              <div className="text-slate-200">{selectedTrade.quantity}</div>
            </div>
            <div>
              <div className="text-slate-500">Commission</div>
              <div className="text-slate-200">${selectedTrade.commission.toFixed(4)}</div>
            </div>
            <div>
              <div className="text-slate-500">Realized PnL</div>
              <div className={selectedTrade.realized_pnl >= 0 ? "text-emerald-400" : "text-rose-400"}>
                ${selectedTrade.realized_pnl.toFixed(2)}
              </div>
            </div>
            <div>
              <div className="text-slate-500">Timestamp</div>
              <div className="text-slate-300">{selectedTrade.timestamp_exchange || "N/A"}</div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
