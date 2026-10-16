import React, { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, Radio, CheckCircle, XCircle } from "lucide-react";
import { apiClient } from "../api/client";
import { endpoints } from "../config/endpoints";
import { SignalItem } from "../types/dashboard";

const PAGE_SIZE = 25; // non-configurable: standard table page size

export function SignalsPage() {
  const [page, setPage] = useState(0);
  const [strategyFilter, setStrategyFilter] = useState("");

  const { data: signals = [], isLoading } = useQuery<SignalItem[]>({
    queryKey: ["signals", { strategy: strategyFilter, limit: PAGE_SIZE, offset: page * PAGE_SIZE }],
    queryFn: () =>
      apiClient(
        endpoints.signals({
          strategy: strategyFilter || undefined,
          limit: PAGE_SIZE,
          offset: page * PAGE_SIZE,
        })
      ),
  });

  return (
    <div className="space-y-6">
      {/* Top Controls */}
      <div className="flex items-center justify-between p-4 rounded-xl bg-slate-900 border border-slate-800">
        <input
          type="text"
          placeholder="Filter by strategy name..."
          value={strategyFilter}
          onChange={(e) => {
            setStrategyFilter(e.target.value);
            setPage(0);
          }}
          className="px-3 py-1.5 bg-slate-950 border border-slate-800 rounded-lg text-xs font-mono text-slate-200 placeholder-slate-500 focus:outline-none focus:border-emerald-500"
        />
      </div>

      {/* Signals Table */}
      <div className="p-5 rounded-xl bg-slate-900 border border-slate-800">
        <div className="flex items-center space-x-2 mb-4">
          <Radio className="h-4 w-4 text-cyan-400" />
          <h2 className="text-sm font-bold font-mono text-slate-200">
            STRATEGY ALPHA SIGNALS
          </h2>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs font-mono">
            <thead>
              <tr className="border-b border-slate-800 text-slate-400">
                <th className="pb-2">SIGNAL ID</th>
                <th className="pb-2">STRATEGY</th>
                <th className="pb-2">SYMBOL</th>
                <th className="pb-2">DIRECTION</th>
                <th className="pb-2">CONFIDENCE</th>
                <th className="pb-2">STATUS / REASON</th>
                <th className="pb-2 text-right">TIMESTAMP</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60">
              {isLoading ? (
                <tr>
                  <td colSpan={7} className="py-8 text-center text-slate-500">
                    Loading signals...
                  </td>
                </tr>
              ) : signals.length > 0 ? (
                signals.map((sig) => {
                  const isBuy = sig.direction.toUpperCase() === "BUY";
                  const isRejected = Boolean(sig.rejection_reason);

                  return (
                    <tr key={sig.event_id} className="hover:bg-slate-800/30">
                      <td className="py-2.5 text-slate-400 font-bold">{sig.event_id.slice(0, 8)}...</td>
                      <td className="py-2.5 font-bold text-slate-200">{sig.strategy_name}</td>
                      <td className="py-2.5 text-slate-300">{sig.symbol}</td>
                      <td className="py-2.5">
                        <span
                          className={`px-1.5 py-0.5 rounded text-[10px] font-bold uppercase ${
                            isBuy
                              ? "bg-emerald-500/20 text-emerald-400 border border-emerald-500/30"
                              : "bg-rose-500/20 text-rose-400 border border-rose-500/30"
                          }`}
                        >
                          {sig.direction}
                        </span>
                      </td>
                      <td className="py-2.5">
                        <div className="flex items-center space-x-2">
                          <div className="w-16 bg-slate-800 h-1.5 rounded-full overflow-hidden">
                            <div
                              className="bg-cyan-400 h-full rounded-full"
                              style={{ width: `${Math.min(sig.confidence * 100, 100)}%` }}
                            />
                          </div>
                          <span className="text-slate-400 text-[11px]">
                            {(sig.confidence * 100).toFixed(0)}%
                          </span>
                        </div>
                      </td>
                      <td className="py-2.5">
                        {isRejected ? (
                          <div className="flex items-center space-x-1.5 text-rose-400">
                            <XCircle className="h-3.5 w-3.5" />
                            <span>{sig.rejection_reason}</span>
                          </div>
                        ) : (
                          <div className="flex items-center space-x-1.5 text-emerald-400">
                            <CheckCircle className="h-3.5 w-3.5" />
                            <span>Approved (Risk Passed)</span>
                          </div>
                        )}
                      </td>
                      <td className="py-2.5 text-right text-slate-500">
                        {sig.timestamp_exchange ? new Date(sig.timestamp_exchange).toLocaleTimeString() : "—"}
                      </td>
                    </tr>
                  );
                })
              ) : (
                <tr>
                  <td colSpan={7} className="py-8 text-center text-slate-500">
                    No signals emitted
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
              disabled={signals.length < PAGE_SIZE}
              onClick={() => setPage((p) => p + 1)}
              className="p-1.5 rounded bg-slate-950 border border-slate-800 hover:border-slate-700 disabled:opacity-40"
            >
              <ChevronRight className="h-4 w-4" />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
