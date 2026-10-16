import React, { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import {
  LineChart as LineChartIcon,
  Play,
  RotateCcw,
  TrendingUp,
  Award,
  ChevronRight,
  CheckCircle2,
  AlertCircle,
  Clock,
} from "lucide-react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
} from "recharts";
import { apiClient } from "../api/client";
import { endpoints } from "../config/endpoints";
import { BacktestRunItem, BacktestRunDetail, BacktestJobStatus } from "../types/dashboard";

const RunFormSchema = z.object({
  strategy_name: z.string().min(1, "Strategy is required"),
  symbol: z.string().min(1, "Symbol is required"),
  start_date: z.string().min(1, "Start date is required"),
  end_date: z.string().min(1, "End date is required"),
  initial_cash: z.coerce.number().positive(),
  parameters_json: z.string().refine((val) => {
    try {
      JSON.parse(val);
      return true;
    } catch {
      return false;
    }
  }, "Invalid parameters JSON"),
});

type RunFormData = z.infer<typeof RunFormSchema>;

export function BacktestPage() {
  const queryClient = useQueryClient();
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);

  // List of runs
  const { data: runs = [], isLoading: isLoadingRuns } = useQuery<BacktestRunItem[]>({
    queryKey: ["backtest", "runs"],
    queryFn: () => apiClient(endpoints.backtest.runs()),
  });

  // Selected run details
  const { data: runDetail } = useQuery<BacktestRunDetail>({
    queryKey: ["backtest", "run", selectedRunId],
    queryFn: () => apiClient(endpoints.backtest.run(selectedRunId!)),
    enabled: Boolean(selectedRunId),
  });

  // Active Job Polling
  const { data: jobStatus } = useQuery<BacktestJobStatus>({
    queryKey: ["backtest", "job", activeJobId],
    queryFn: () => apiClient(endpoints.backtest.job(activeJobId!)),
    enabled: Boolean(activeJobId),
    refetchInterval: (query) => {
      const data = query.state.data;
      if (data && (data.status === "completed" || data.status === "failed")) {
        return false;
      }
      return 1500; // non-configurable: 1.5s job status polling interval
    },
  });

  useEffect(() => {
    if (jobStatus && jobStatus.status === "completed") {
      queryClient.invalidateQueries({ queryKey: ["backtest", "runs"] });
      if (jobStatus.run_id) {
        setSelectedRunId(jobStatus.run_id);
      }
    }
  }, [jobStatus, queryClient]);

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<RunFormData>({
    resolver: zodResolver(RunFormSchema),
    defaultValues: {
      strategy_name: "trend_following",
      symbol: "BTC/USDT",
      start_date: "2024-01-01",
      end_date: "2024-06-01",
      initial_cash: 100000.0,
      parameters_json: '{"window_fast": 10, "window_slow": 30}',
    },
  });

  const triggerMutation = useMutation({
    mutationFn: async (data: RunFormData) => {
      const payload = {
        strategy_name: data.strategy_name,
        symbol: data.symbol,
        start_date: data.start_date,
        end_date: data.end_date,
        initial_cash: data.initial_cash,
        parameters: JSON.parse(data.parameters_json),
      };
      return apiClient<{ job_id: string }>(endpoints.backtest.trigger(), {
        method: "POST",
        body: JSON.stringify(payload),
      });
    },
    onSuccess: (res) => {
      setActiveJobId(res.job_id);
    },
  });

  const onSubmit = (data: RunFormData) => {
    triggerMutation.mutate(data);
  };

  return (
    <div className="space-y-6">
      {/* Run Trigger Form */}
      <div className="p-5 rounded-xl bg-slate-900 border border-slate-800">
        <div className="flex items-center space-x-2 mb-4">
          <Play className="h-4 w-4 text-emerald-400" />
          <h2 className="text-sm font-bold font-mono text-slate-200">
            LAUNCH STRATEGY BACKTEST
          </h2>
        </div>

        <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div>
              <label className="block text-xs font-mono text-slate-400 mb-1">Strategy Name:</label>
              <input
                type="text"
                {...register("strategy_name")}
                className="w-full px-3 py-1.5 bg-slate-950 border border-slate-800 rounded-lg text-xs font-mono text-slate-200 focus:outline-none focus:border-emerald-500"
              />
              {errors.strategy_name && (
                <span className="text-xs text-rose-400 font-mono mt-1 block">
                  {errors.strategy_name.message}
                </span>
              )}
            </div>

            <div>
              <label className="block text-xs font-mono text-slate-400 mb-1">Symbol:</label>
              <input
                type="text"
                {...register("symbol")}
                className="w-full px-3 py-1.5 bg-slate-950 border border-slate-800 rounded-lg text-xs font-mono text-slate-200 focus:outline-none focus:border-emerald-500"
              />
              {errors.symbol && (
                <span className="text-xs text-rose-400 font-mono mt-1 block">
                  {errors.symbol.message}
                </span>
              )}
            </div>

            <div>
              <label className="block text-xs font-mono text-slate-400 mb-1">Initial Cash ($):</label>
              <input
                type="number"
                step="any"
                {...register("initial_cash")}
                className="w-full px-3 py-1.5 bg-slate-950 border border-slate-800 rounded-lg text-xs font-mono text-slate-200 focus:outline-none focus:border-emerald-500"
              />
              {errors.initial_cash && (
                <span className="text-xs text-rose-400 font-mono mt-1 block">
                  {errors.initial_cash.message}
                </span>
              )}
            </div>

            <div>
              <label className="block text-xs font-mono text-slate-400 mb-1">Start Date:</label>
              <input
                type="date"
                {...register("start_date")}
                className="w-full px-3 py-1.5 bg-slate-950 border border-slate-800 rounded-lg text-xs font-mono text-slate-200 focus:outline-none focus:border-emerald-500"
              />
            </div>

            <div>
              <label className="block text-xs font-mono text-slate-400 mb-1">End Date:</label>
              <input
                type="date"
                {...register("end_date")}
                className="w-full px-3 py-1.5 bg-slate-950 border border-slate-800 rounded-lg text-xs font-mono text-slate-200 focus:outline-none focus:border-emerald-500"
              />
            </div>

            <div>
              <label className="block text-xs font-mono text-slate-400 mb-1">Parameters (JSON):</label>
              <input
                type="text"
                {...register("parameters_json")}
                className="w-full px-3 py-1.5 bg-slate-950 border border-slate-800 rounded-lg text-xs font-mono text-slate-200 focus:outline-none focus:border-emerald-500"
              />
            </div>
          </div>

          <div className="flex items-center justify-between pt-2">
            <div>
              {activeJobId && jobStatus && (
                <div className="flex items-center space-x-2 text-xs font-mono text-cyan-400">
                  <Clock className="h-4 w-4 animate-spin" />
                  <span>
                    Job {activeJobId.slice(0, 8)}: {jobStatus.status.toUpperCase()} ({Math.round(jobStatus.progress * 100)}%)
                  </span>
                </div>
              )}
            </div>

            <button
              type="submit"
              disabled={triggerMutation.isPending}
              className="px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white font-mono font-bold text-xs transition"
            >
              {triggerMutation.isPending ? "Queuing Job..." : "Submit Backtest Job"}
            </button>
          </div>
        </form>
      </div>

      {/* Grid: Run List & Report Viewer */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left: Completed Run List */}
        <div className="p-5 rounded-xl bg-slate-900 border border-slate-800 space-y-3">
          <h3 className="text-sm font-bold font-mono text-slate-200 mb-2">
            HISTORICAL RUNS ({runs.length})
          </h3>

          {isLoadingRuns ? (
            <div className="text-xs font-mono text-slate-500 py-6 text-center">
              Loading backtest catalog...
            </div>
          ) : runs.length > 0 ? (
            runs.map((r) => (
              <div
                key={r.id}
                onClick={() => setSelectedRunId(r.id)}
                className={`p-3 rounded-lg border text-xs font-mono cursor-pointer transition ${
                  selectedRunId === r.id
                    ? "bg-slate-800 border-emerald-500/50"
                    : "bg-slate-950 border-slate-800 hover:bg-slate-900"
                }`}
              >
                <div className="flex justify-between items-center mb-1">
                  <span className="font-bold text-slate-200 uppercase">{r.strategy_name}</span>
                  <span
                    className={`text-[10px] px-1.5 py-0.2 rounded uppercase font-bold ${
                      r.status === "completed"
                        ? "bg-emerald-500/20 text-emerald-400"
                        : "bg-amber-500/20 text-amber-400"
                    }`}
                  >
                    {r.status}
                  </span>
                </div>
                <div className="text-[11px] text-slate-500">
                  {r.start_date} → {r.end_date}
                </div>
                <div className="flex justify-between mt-2 pt-2 border-t border-slate-800/80 text-[11px]">
                  <span>Sharpe: {r.sharpe ? r.sharpe.toFixed(2) : "N/A"}</span>
                  <span className={r.total_return >= 0 ? "text-emerald-400" : "text-rose-400"}>
                    Return: {(r.total_return * 100).toFixed(1)}%
                  </span>
                </div>
              </div>
            ))
          ) : (
            <div className="text-xs font-mono text-slate-500 py-6 text-center">
              No backtest runs found
            </div>
          )}
        </div>

        {/* Right: Detailed Report Viewer */}
        <div className="lg:col-span-2 p-5 rounded-xl bg-slate-900 border border-slate-800">
          <h3 className="text-sm font-bold font-mono text-slate-200 mb-4">
            PERFORMANCE & METRICS REPORT
          </h3>

          {runDetail ? (
            <div className="space-y-6">
              {/* Metrics Summary */}
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                <div className="p-3 rounded-lg bg-slate-950 border border-slate-800 text-center font-mono">
                  <div className="text-[10px] text-slate-500">SHARPE RATIO</div>
                  <div className="text-base font-bold text-emerald-400 mt-1">
                    {runDetail.metrics?.sharpe ? Number(runDetail.metrics.sharpe).toFixed(2) : "N/A"}
                  </div>
                </div>
                <div className="p-3 rounded-lg bg-slate-950 border border-slate-800 text-center font-mono">
                  <div className="text-[10px] text-slate-500">SORTINO RATIO</div>
                  <div className="text-base font-bold text-cyan-400 mt-1">
                    {runDetail.metrics?.sortino ? Number(runDetail.metrics.sortino).toFixed(2) : "N/A"}
                  </div>
                </div>
                <div className="p-3 rounded-lg bg-slate-950 border border-slate-800 text-center font-mono">
                  <div className="text-[10px] text-slate-500">MAX DRAWDOWN</div>
                  <div className="text-base font-bold text-rose-400 mt-1">
                    {runDetail.metrics?.max_drawdown
                      ? `${(Number(runDetail.metrics.max_drawdown) * 100).toFixed(1)}%`
                      : "N/A"}
                  </div>
                </div>
                <div className="p-3 rounded-lg bg-slate-950 border border-slate-800 text-center font-mono">
                  <div className="text-[10px] text-slate-500">WIN RATE</div>
                  <div className="text-base font-bold text-slate-200 mt-1">
                    {runDetail.metrics?.win_rate
                      ? `${(Number(runDetail.metrics.win_rate) * 100).toFixed(1)}%`
                      : "N/A"}
                  </div>
                </div>
              </div>

              {/* Equity Curve Chart */}
              {runDetail.equity_curve && runDetail.equity_curve.length > 0 && (
                <div className="h-64 w-full">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={runDetail.equity_curve}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                      <XAxis dataKey="timestamp" stroke="#334155" tick={{ fill: "#64748b", fontSize: 10 }} />
                      <YAxis stroke="#334155" tick={{ fill: "#64748b", fontSize: 10 }} />
                      <Tooltip
                        contentStyle={{
                          backgroundColor: "#0f172a",
                          borderColor: "#334155",
                          fontSize: "12px",
                          fontFamily: "monospace",
                        }}
                      />
                      <Line
                        type="monotone"
                        dataKey="equity"
                        stroke="#10b981"
                        strokeWidth={2}
                        dot={false}
                        isAnimationActive={false} // non-configurable: chart performance
                      />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              )}

              {/* Parameters Breakdown */}
              <div className="p-4 rounded-lg bg-slate-950 border border-slate-800 text-xs font-mono">
                <div className="text-slate-400 font-bold mb-2">RUN PARAMETERS</div>
                <pre className="text-slate-300 overflow-x-auto">
                  {JSON.stringify(runDetail.params, null, 2)}
                </pre>
              </div>
            </div>
          ) : (
            <div className="py-16 text-center text-xs font-mono text-slate-500">
              Select a backtest run on the left to view detailed analytics
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
