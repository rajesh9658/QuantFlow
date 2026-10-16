import React, { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, X, Clock, CheckCircle2, AlertCircle } from "lucide-react";
import { apiClient } from "../api/client";
import { endpoints } from "../config/endpoints";
import { OrderItem } from "../types/dashboard";

const PAGE_SIZE = 25; // non-configurable: standard table page size

export function OrdersPage() {
  const [page, setPage] = useState(0);
  const [statusFilter, setStatusFilter] = useState("");
  const [selectedOrder, setSelectedOrder] = useState<OrderItem | null>(null);

  const { data: orders = [], isLoading } = useQuery<OrderItem[]>({
    queryKey: ["orders", { status: statusFilter, limit: PAGE_SIZE, offset: page * PAGE_SIZE }],
    queryFn: () =>
      apiClient(
        endpoints.orders({
          status: statusFilter || undefined,
          limit: PAGE_SIZE,
          offset: page * PAGE_SIZE,
        })
      ),
  });

  const getStatusBadge = (status: string) => {
    switch (status.toUpperCase()) {
      case "FILLED":
        return "bg-emerald-500/20 text-emerald-400 border border-emerald-500/30";
      case "PARTIALLY_FILLED":
        return "bg-cyan-500/20 text-cyan-400 border border-cyan-500/30";
      case "NEW":
        return "bg-blue-500/20 text-blue-400 border border-blue-500/30";
      case "CANCELLED":
        return "bg-slate-700/40 text-slate-400 border border-slate-700";
      case "REJECTED":
        return "bg-rose-500/20 text-rose-400 border border-rose-500/30";
      default:
        return "bg-slate-800 text-slate-300";
    }
  };

  return (
    <div className="space-y-6">
      {/* Filters Header */}
      <div className="flex items-center justify-between p-4 rounded-xl bg-slate-900 border border-slate-800">
        <div className="flex items-center space-x-3">
          <select
            value={statusFilter}
            onChange={(e) => {
              setStatusFilter(e.target.value);
              setPage(0);
            }}
            className="px-3 py-1.5 bg-slate-950 border border-slate-800 rounded-lg text-xs font-mono text-slate-200 focus:outline-none focus:border-emerald-500"
          >
            <option value="">All Statuses</option>
            <option value="NEW">NEW</option>
            <option value="PARTIALLY_FILLED">PARTIALLY_FILLED</option>
            <option value="FILLED">FILLED</option>
            <option value="CANCELLED">CANCELLED</option>
            <option value="REJECTED">REJECTED</option>
          </select>
        </div>
      </div>

      {/* Orders Table */}
      <div className="p-5 rounded-xl bg-slate-900 border border-slate-800">
        <h2 className="text-sm font-bold font-mono text-slate-200 mb-4">
          MANAGED ORDERS
        </h2>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs font-mono">
            <thead>
              <tr className="border-b border-slate-800 text-slate-400">
                <th className="pb-2">ORDER ID</th>
                <th className="pb-2">SYMBOL</th>
                <th className="pb-2">SIDE</th>
                <th className="pb-2">TYPE</th>
                <th className="pb-2">QTY</th>
                <th className="pb-2">FILLED</th>
                <th className="pb-2">AVG PRICE</th>
                <th className="pb-2">STATUS</th>
                <th className="pb-2 text-right">CREATED</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60">
              {isLoading ? (
                <tr>
                  <td colSpan={9} className="py-8 text-center text-slate-500">
                    Loading orders...
                  </td>
                </tr>
              ) : orders.length > 0 ? (
                orders.map((ord) => (
                  <tr
                    key={ord.order_id}
                    onClick={() => setSelectedOrder(ord)}
                    className="hover:bg-slate-800/50 cursor-pointer transition"
                  >
                    <td className="py-2.5 text-slate-400 font-bold">{ord.order_id.slice(0, 8)}...</td>
                    <td className="py-2.5 font-bold text-slate-200">{ord.symbol}</td>
                    <td className="py-2.5">
                      <span
                        className={`px-1.5 py-0.5 rounded text-[10px] font-bold uppercase ${
                          ord.side.toLowerCase() === "buy" ? "text-emerald-400" : "text-rose-400"
                        }`}
                      >
                        {ord.side}
                      </span>
                    </td>
                    <td className="py-2.5 text-slate-400 uppercase">{ord.type}</td>
                    <td className="py-2.5 text-slate-300">{ord.quantity}</td>
                    <td className="py-2.5 text-slate-300">{ord.filled_quantity}</td>
                    <td className="py-2.5 text-slate-300">${ord.avg_price.toLocaleString()}</td>
                    <td className="py-2.5">
                      <span className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase ${getStatusBadge(ord.status)}`}>
                        {ord.status}
                      </span>
                    </td>
                    <td className="py-2.5 text-right text-slate-500">
                      {ord.created_at ? new Date(ord.created_at).toLocaleTimeString() : "—"}
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={9} className="py-8 text-center text-slate-500">
                    No orders matching criteria
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
              disabled={orders.length < PAGE_SIZE}
              onClick={() => setPage((p) => p + 1)}
              className="p-1.5 rounded bg-slate-950 border border-slate-800 hover:border-slate-700 disabled:opacity-40"
            >
              <ChevronRight className="h-4 w-4" />
            </button>
          </div>
        </div>
      </div>

      {/* Selected Order Timeline Drawer */}
      {selectedOrder && (
        <div className="fixed inset-y-0 right-0 z-50 w-full max-w-md bg-slate-900 border-l border-slate-800 p-6 shadow-2xl overflow-y-auto">
          <div className="flex items-center justify-between pb-4 border-b border-slate-800">
            <h3 className="font-bold font-mono text-sm text-slate-100">ORDER LIFECYCLE</h3>
            <button
              type="button"
              onClick={() => setSelectedOrder(null)}
              className="text-slate-400 hover:text-white"
            >
              <X className="h-5 w-5" />
            </button>
          </div>

          <div className="space-y-4 py-4 text-xs font-mono">
            <div>
              <div className="text-slate-500">Order ID</div>
              <div className="text-slate-200 select-all font-semibold">{selectedOrder.order_id}</div>
            </div>
            <div>
              <div className="text-slate-500">Symbol</div>
              <div className="text-slate-200 font-bold text-sm">{selectedOrder.symbol}</div>
            </div>
            <div>
              <div className="text-slate-500">Current Status</div>
              <span className={`inline-block mt-1 px-2 py-0.5 rounded text-[10px] font-bold ${getStatusBadge(selectedOrder.status)}`}>
                {selectedOrder.status}
              </span>
            </div>

            {/* Lifecycle Timeline */}
            <div className="pt-4 border-t border-slate-800">
              <div className="text-slate-400 font-bold mb-3">LIFECYCLE EVENTS</div>
              <div className="space-y-3 relative pl-4 border-l-2 border-slate-800">
                <div className="relative">
                  <div className="absolute -left-[21px] top-1 w-2.5 h-2.5 rounded-full bg-emerald-400" />
                  <div className="text-slate-200 font-semibold">Order Created</div>
                  <div className="text-slate-500 text-[11px]">{selectedOrder.created_at}</div>
                </div>
                {selectedOrder.status === "FILLED" && (
                  <div className="relative">
                    <div className="absolute -left-[21px] top-1 w-2.5 h-2.5 rounded-full bg-emerald-400" />
                    <div className="text-slate-200 font-semibold">Fully Filled</div>
                    <div className="text-slate-500 text-[11px]">Filled {selectedOrder.filled_quantity} @ ${selectedOrder.avg_price}</div>
                  </div>
                )}
                {selectedOrder.status === "CANCELLED" && (
                  <div className="relative">
                    <div className="absolute -left-[21px] top-1 w-2.5 h-2.5 rounded-full bg-amber-400" />
                    <div className="text-slate-200 font-semibold">Order Cancelled</div>
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
