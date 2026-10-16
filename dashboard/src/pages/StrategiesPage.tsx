import React, { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Cpu, Settings2, Play, Square, Check, X, TrendingUp } from "lucide-react";
import { apiClient } from "../api/client";
import { endpoints } from "../config/endpoints";
import { StrategySummary } from "../types/dashboard";

const ConfigSchema = z.object({
  jsonString: z.string().refine((val) => {
    try {
      JSON.parse(val);
      return true;
    } catch {
      return false;
    }
  }, "Must be valid JSON"),
});

type ConfigFormData = z.infer<typeof ConfigSchema>;

export function StrategiesPage() {
  const queryClient = useQueryClient();
  const [editingStrategy, setEditingStrategy] = useState<StrategySummary | null>(null);

  const { data: strategies = [], isLoading } = useQuery<StrategySummary[]>({
    queryKey: ["strategies"],
    queryFn: () => apiClient(endpoints.strategies.list()),
  });

  // Optimistic Toggle Mutation per Spec B7
  const toggleMutation = useMutation({
    mutationFn: async ({ name, active }: { name: string; active: boolean }) => {
      return apiClient(endpoints.strategies.toggle(name), {
        method: "POST",
        body: JSON.stringify({ active }),
      });
    },
    onMutate: async ({ name, active }) => {
      await queryClient.cancelQueries({ queryKey: ["strategies"] });
      const previous = queryClient.getQueryData<StrategySummary[]>(["strategies"]);
      queryClient.setQueryData<StrategySummary[]>(["strategies"], (old) =>
        old ? old.map((s) => (s.name === name ? { ...s, active } : s)) : []
      );
      return { previous };
    },
    onError: (_err, _vars, context) => {
      if (context?.previous) {
        queryClient.setQueryData(["strategies"], context.previous);
      }
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["strategies"] });
    },
  });

  const {
    register,
    handleSubmit,
    setValue,
    formState: { errors },
  } = useForm<ConfigFormData>({
    resolver: zodResolver(ConfigSchema),
  });

  const configMutation = useMutation({
    mutationFn: async ({ name, config }: { name: string; config: Record<string, unknown> }) => {
      return apiClient(endpoints.strategies.config(name), {
        method: "PATCH",
        body: JSON.stringify({ config }),
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["strategies"] });
      setEditingStrategy(null);
    },
  });

  const openConfigEditor = (strategy: StrategySummary) => {
    setEditingStrategy(strategy);
    setValue("jsonString", JSON.stringify(strategy.config || {}, null, 2));
  };

  const onSubmitConfig = (data: ConfigFormData) => {
    if (!editingStrategy) return;
    const parsed = JSON.parse(data.jsonString);
    configMutation.mutate({ name: editingStrategy.name, config: parsed });
  };

  return (
    <div className="space-y-6">
      <div className="p-4 rounded-xl bg-slate-900 border border-slate-800 flex items-center justify-between">
        <div>
          <h2 className="text-sm font-bold font-mono text-slate-200">ACTIVE TRADING STRATEGIES</h2>
          <p className="text-xs font-mono text-slate-500">Autonomous alpha execution models</p>
        </div>
      </div>

      {isLoading ? (
        <div className="p-12 text-center text-xs font-mono text-slate-500">
          Loading strategy registry...
        </div>
      ) : strategies.length > 0 ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {strategies.map((strategy) => (
            <div
              key={strategy.name}
              className="p-5 rounded-xl bg-slate-900 border border-slate-800 flex flex-col justify-between space-y-4"
            >
              <div>
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center space-x-2">
                    <div className="p-1.5 rounded-lg bg-emerald-500/10 border border-emerald-500/20 text-emerald-400">
                      <Cpu className="h-4 w-4" />
                    </div>
                    <div>
                      <h3 className="font-bold font-mono text-slate-100 text-sm">{strategy.name}</h3>
                      <span className="text-[10px] font-mono text-slate-500">v{strategy.version}</span>
                    </div>
                  </div>

                  {/* Active Toggle Button */}
                  <button
                    type="button"
                    onClick={() =>
                      toggleMutation.mutate({
                        name: strategy.name,
                        active: !strategy.active,
                      })
                    }
                    className={`px-3 py-1 rounded-full text-xs font-mono font-bold uppercase transition flex items-center space-x-1.5 ${
                      strategy.active
                        ? "bg-emerald-500/20 text-emerald-400 border border-emerald-500/40 hover:bg-emerald-500/30"
                        : "bg-slate-800 text-slate-500 border border-slate-700 hover:bg-slate-700"
                    }`}
                  >
                    {strategy.active ? (
                      <>
                        <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                        <span>RUNNING</span>
                      </>
                    ) : (
                      <>
                        <Square className="h-3 w-3" />
                        <span>STOPPED</span>
                      </>
                    )}
                  </button>
                </div>

                {/* Metrics */}
                <div className="grid grid-cols-3 gap-2 py-3 border-y border-slate-800/80 text-center font-mono">
                  <div>
                    <div className="text-[10px] text-slate-500">WIN RATE</div>
                    <div className="text-xs font-bold text-slate-200">
                      {(strategy.metrics.win_rate * 100).toFixed(1)}%
                    </div>
                  </div>
                  <div>
                    <div className="text-[10px] text-slate-500">SHARPE</div>
                    <div className="text-xs font-bold text-emerald-400">
                      {strategy.metrics.sharpe.toFixed(2)}
                    </div>
                  </div>
                  <div>
                    <div className="text-[10px] text-slate-500">TRADES</div>
                    <div className="text-xs font-bold text-slate-300">
                      {strategy.metrics.total_trades}
                    </div>
                  </div>
                </div>
              </div>

              {/* Card Footer Actions */}
              <div className="pt-2 flex items-center justify-between">
                <button
                  type="button"
                  onClick={() => openConfigEditor(strategy)}
                  className="px-3 py-1.5 rounded-lg bg-slate-950 border border-slate-800 hover:border-slate-700 text-slate-300 hover:text-white text-xs font-mono flex items-center space-x-1.5 transition"
                >
                  <Settings2 className="h-3.5 w-3.5 text-slate-400" />
                  <span>Configure</span>
                </button>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="p-12 text-center text-xs font-mono text-slate-500 bg-slate-900 rounded-xl border border-slate-800">
          No strategy plugins registered
        </div>
      )}

      {/* Strategy Config Modal */}
      {editingStrategy && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4">
          <div className="relative w-full max-w-lg rounded-xl border border-slate-800 bg-slate-900 p-6 shadow-2xl">
            <div className="flex items-center justify-between pb-4 border-b border-slate-800 mb-4">
              <h3 className="font-bold font-mono text-sm text-slate-100">
                EDIT CONFIGURATION: {editingStrategy.name}
              </h3>
              <button
                type="button"
                onClick={() => setEditingStrategy(null)}
                className="text-slate-400 hover:text-white"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <form onSubmit={handleSubmit(onSubmitConfig)} className="space-y-4">
              <div>
                <label className="block text-xs font-mono text-slate-400 mb-1">
                  Strategy Parameters (JSON):
                </label>
                <textarea
                  {...register("jsonString")}
                  rows={10}
                  className="w-full px-3 py-2 bg-slate-950 border border-slate-800 rounded-lg text-slate-200 font-mono text-xs focus:outline-none focus:border-emerald-500"
                />
                {errors.jsonString && (
                  <span className="text-xs text-rose-400 font-mono mt-1 block">
                    {errors.jsonString.message}
                  </span>
                )}
              </div>

              <div className="flex justify-end space-x-3 pt-2">
                <button
                  type="button"
                  onClick={() => setEditingStrategy(null)}
                  className="px-4 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-mono transition"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={configMutation.isPending}
                  className="px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white font-mono font-bold text-xs transition"
                >
                  {configMutation.isPending ? "Applying..." : "Save Config (Hot-Reload)"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
