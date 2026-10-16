import React from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Globe, Power, Activity, Wifi, Radio } from "lucide-react";
import { apiClient } from "../api/client";
import { endpoints } from "../config/endpoints";
import { ExchangeItem } from "../types/dashboard";

export function ExchangesPage() {
  const queryClient = useQueryClient();

  const { data: exchanges = [], isLoading } = useQuery<ExchangeItem[]>({
    queryKey: ["exchanges"],
    queryFn: () => apiClient(endpoints.exchanges.list()),
  });

  const toggleMutation = useMutation({
    mutationFn: async ({ id, enabled }: { id: string; enabled: boolean }) => {
      return apiClient(endpoints.exchanges.toggle(id), {
        method: "POST",
        body: JSON.stringify({ enabled }),
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["exchanges"] });
    },
  });

  return (
    <div className="space-y-6">
      <div className="p-4 rounded-xl bg-slate-900 border border-slate-800 flex items-center justify-between">
        <div>
          <h2 className="text-sm font-bold font-mono text-slate-200">EXCHANGE CONNECTIVITY ADAPTERS</h2>
          <p className="text-xs font-mono text-slate-500">Market data streams and execution gateways</p>
        </div>
      </div>

      {isLoading ? (
        <div className="p-12 text-center text-xs font-mono text-slate-500">
          Querying exchange adapter statuses...
        </div>
      ) : exchanges.length > 0 ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {exchanges.map((ex) => (
            <div
              key={ex.id}
              className="p-5 rounded-xl bg-slate-900 border border-slate-800 flex flex-col justify-between space-y-4"
            >
              <div>
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center space-x-2">
                    <div className="p-1.5 rounded-lg bg-cyan-500/10 border border-cyan-500/20 text-cyan-400">
                      <Globe className="h-4 w-4" />
                    </div>
                    <div>
                      <h3 className="font-bold font-mono text-slate-100 text-sm uppercase">{ex.name}</h3>
                      <span className="text-[10px] font-mono text-slate-500 uppercase">{ex.type} adapter</span>
                    </div>
                  </div>

                  <span
                    className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase ${
                      ex.connected && ex.enabled
                        ? "bg-emerald-500/20 text-emerald-400 border border-emerald-500/40"
                        : "bg-rose-500/20 text-rose-400 border border-rose-500/40"
                    }`}
                  >
                    {ex.connected && ex.enabled ? "CONNECTED" : "DISCONNECTED"}
                  </span>
                </div>

                <div className="space-y-2 py-3 border-y border-slate-800/80 text-xs font-mono">
                  <div className="flex justify-between">
                    <span className="text-slate-500">Gateway Latency:</span>
                    <span className="font-bold text-slate-200">{ex.latency_ms} ms</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-500">Heartbeat:</span>
                    <span className="text-slate-400">
                      {ex.last_heartbeat ? new Date(ex.last_heartbeat).toLocaleTimeString() : "Recent"}
                    </span>
                  </div>
                  <div>
                    <div className="text-slate-500 mb-1">Subscribed Symbol Streams ({ex.symbols_subscribed?.length || 0}):</div>
                    <div className="flex flex-wrap gap-1">
                      {ex.symbols_subscribed && ex.symbols_subscribed.length > 0 ? (
                        ex.symbols_subscribed.map((sym) => (
                          <span
                            key={sym}
                            className="px-1.5 py-0.5 rounded bg-slate-950 border border-slate-800 text-[10px] text-slate-300"
                          >
                            {sym}
                          </span>
                        ))
                      ) : (
                        <span className="text-slate-600 text-[11px]">No active streams</span>
                      )}
                    </div>
                  </div>
                </div>
              </div>

              <div className="pt-2 flex justify-end">
                <button
                  type="button"
                  disabled={toggleMutation.isPending}
                  onClick={() => toggleMutation.mutate({ id: ex.id, enabled: !ex.enabled })}
                  className={`px-3 py-1.5 rounded-lg text-xs font-mono font-semibold flex items-center space-x-1.5 transition ${
                    ex.enabled
                      ? "bg-rose-950 hover:bg-rose-900 text-rose-300 border border-rose-800"
                      : "bg-emerald-950 hover:bg-emerald-900 text-emerald-300 border border-emerald-800"
                  }`}
                >
                  <Power className="h-3.5 w-3.5" />
                  <span>{ex.enabled ? "Disable Adapter" : "Enable Adapter"}</span>
                </button>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="p-12 text-center text-xs font-mono text-slate-500 bg-slate-900 rounded-xl border border-slate-800">
          No exchange adapters configured
        </div>
      )}
    </div>
  );
}
