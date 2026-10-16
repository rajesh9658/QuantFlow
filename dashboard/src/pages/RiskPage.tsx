import React, { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Shield, AlertTriangle, CheckCircle, RefreshCw, Sliders } from "lucide-react";
import { apiClient } from "../api/client";
import { endpoints } from "../config/endpoints";
import { useRiskStore } from "../state/riskStore";
import { EmergencyStopModal } from "../components/EmergencyStopModal";
import { RiskStatus, RiskConfig } from "../types/dashboard";

const RiskFormSchema = z.object({
  max_position_qty: z.coerce.number().positive(),
  max_daily_loss: z.coerce.number().positive(),
  max_total_exposure: z.coerce.number().positive(),
  trading_schedule: z.string().min(1),
  allowed_symbols: z.string(),
});

type RiskFormData = z.infer<typeof RiskFormSchema>;

export function RiskPage() {
  const queryClient = useQueryClient();
  const liveStatus = useRiskStore((s) => s.status);
  const [showStopModal, setShowStopModal] = useState(false);

  const { data: serverStatus } = useQuery<RiskStatus>({
    queryKey: ["risk", "status"],
    queryFn: () => apiClient(endpoints.risk.status()),
  });

  const { data: config } = useQuery<RiskConfig>({
    queryKey: ["risk", "config"],
    queryFn: () => apiClient(endpoints.risk.config()),
  });

  const status = serverStatus || liveStatus;

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<RiskFormData>({
    resolver: zodResolver(RiskFormSchema),
    values: {
      max_position_qty: config?.max_position_qty || 5.0,
      max_daily_loss: config?.max_daily_loss || 1000.0,
      max_total_exposure: config?.max_total_exposure || 100000.0,
      trading_schedule: config?.trading_schedule || "00:00-23:59",
      allowed_symbols: config?.allowed_symbols?.join(", ") || "BTC/USDT, ETH/USDT",
    },
  });

  // Optimistic update for risk.config.patch per Spec B7
  const patchConfigMutation = useMutation({
    mutationFn: async (data: Partial<RiskConfig>) => {
      return apiClient(endpoints.risk.config(), {
        method: "PATCH",
        body: JSON.stringify(data),
      });
    },
    onMutate: async (newConfig) => {
      await queryClient.cancelQueries({ queryKey: ["risk", "config"] });
      const previous = queryClient.getQueryData<RiskConfig>(["risk", "config"]);
      queryClient.setQueryData<RiskConfig>(["risk", "config"], (old) =>
        old ? { ...old, ...newConfig } : (newConfig as RiskConfig)
      );
      return { previous };
    },
    onError: (_err, _vars, context) => {
      if (context?.previous) {
        queryClient.setQueryData(["risk", "config"], context.previous);
      }
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["risk", "config"] });
    },
  });

  const onSubmit = (data: RiskFormData) => {
    patchConfigMutation.mutate({
      max_position_qty: data.max_position_qty,
      max_daily_loss: data.max_daily_loss,
      max_total_exposure: data.max_total_exposure,
      trading_schedule: data.trading_schedule,
      allowed_symbols: data.allowed_symbols.split(",").map((s) => s.trim()).filter(Boolean),
    });
  };

  const dailyLossPct = Math.min(
    (Math.abs(Math.min(status.daily_pnl, 0)) / Math.max(status.daily_loss_limit, 1)) * 100,
    100
  );

  const exposurePct = Math.min(
    (status.current_exposure / Math.max(status.max_exposure, 1)) * 100,
    100
  );

  return (
    <div className="space-y-6">
      {/* Top Banner with Emergency Stop */}
      <div className="p-5 rounded-xl bg-slate-900 border border-slate-800 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div>
          <div className="flex items-center space-x-2">
            <Shield className="h-5 w-5 text-indigo-400" />
            <h2 className="text-base font-bold font-mono text-slate-100">
              RISK ENGINE & CIRCUIT BREAKER
            </h2>
          </div>
          <p className="text-xs font-mono text-slate-500 mt-1">
            Real-time threshold enforcement and institutional risk limits
          </p>
        </div>

        <button
          type="button"
          onClick={() => setShowStopModal(true)}
          className={`px-4 py-2 rounded-lg text-xs font-mono font-bold uppercase transition flex items-center space-x-2 shadow-lg ${
            status.emergency_stop
              ? "bg-rose-600 text-white animate-pulse"
              : "bg-rose-600 hover:bg-rose-500 text-white shadow-rose-900/50"
          }`}
        >
          <AlertTriangle className="h-4 w-4" />
          <span>{status.emergency_stop ? "SYSTEM EMERGENCY HALTED" : "TRIGGER EMERGENCY STOP"}</span>
        </button>
      </div>

      {/* Gauges & Limit Status */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Daily PnL vs Limit Gauge */}
        <div className="p-5 rounded-xl bg-slate-900 border border-slate-800">
          <div className="flex justify-between items-center mb-2">
            <span className="text-xs font-mono text-slate-400">DAILY LOSS CONSUMPTION</span>
            <span className="text-xs font-mono text-slate-200">
              ${Math.abs(Math.min(status.daily_pnl, 0)).toFixed(2)} / ${status.daily_loss_limit.toFixed(2)}
            </span>
          </div>
          <div className="w-full bg-slate-950 h-3 rounded-full overflow-hidden border border-slate-800">
            <div
              className={`h-full rounded-full transition-all duration-300 ${
                dailyLossPct > 80 ? "bg-rose-500" : dailyLossPct > 50 ? "bg-amber-400" : "bg-emerald-400"
              }`}
              style={{ width: `${dailyLossPct}%` }}
            />
          </div>
          <div className="text-[11px] font-mono text-slate-500 mt-2">
            Current Daily PnL: <span className={status.daily_pnl >= 0 ? "text-emerald-400" : "text-rose-400"}>${status.daily_pnl.toFixed(2)}</span>
          </div>
        </div>

        {/* Total Exposure vs Limit */}
        <div className="p-5 rounded-xl bg-slate-900 border border-slate-800">
          <div className="flex justify-between items-center mb-2">
            <span className="text-xs font-mono text-slate-400">TOTAL NOTIONAL EXPOSURE</span>
            <span className="text-xs font-mono text-slate-200">
              ${status.current_exposure.toLocaleString()} / ${status.max_exposure.toLocaleString()}
            </span>
          </div>
          <div className="w-full bg-slate-950 h-3 rounded-full overflow-hidden border border-slate-800">
            <div
              className={`h-full rounded-full transition-all duration-300 ${
                exposurePct > 80 ? "bg-rose-500" : exposurePct > 50 ? "bg-cyan-400" : "bg-indigo-400"
              }`}
              style={{ width: `${exposurePct}%` }}
            />
          </div>
          <div className="text-[11px] font-mono text-slate-500 mt-2">
            Circuit Breaker: {status.circuit_breaker_active ? (
              <span className="text-rose-400 font-bold uppercase">TRIPPED</span>
            ) : (
              <span className="text-emerald-400 font-bold uppercase">ARMED / NORMAL</span>
            )}
          </div>
        </div>
      </div>

      {/* Thresholds Form */}
      <div className="p-5 rounded-xl bg-slate-900 border border-slate-800">
        <div className="flex items-center space-x-2 mb-4">
          <Sliders className="h-4 w-4 text-emerald-400" />
          <h3 className="text-sm font-bold font-mono text-slate-200">
            RISK POLICY THRESHOLDS (HOT-RELOADABLE)
          </h3>
        </div>

        <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-mono text-slate-400 mb-1">
                Max Position Quantity per Symbol:
              </label>
              <input
                type="number"
                step="any"
                {...register("max_position_qty")}
                className="w-full px-3 py-2 bg-slate-950 border border-slate-800 rounded-lg text-slate-200 font-mono text-xs focus:outline-none focus:border-emerald-500"
              />
              {errors.max_position_qty && (
                <span className="text-xs text-rose-400 font-mono mt-1 block">
                  {errors.max_position_qty.message}
                </span>
              )}
            </div>

            <div>
              <label className="block text-xs font-mono text-slate-400 mb-1">
                Max Daily Loss ($):
              </label>
              <input
                type="number"
                step="any"
                {...register("max_daily_loss")}
                className="w-full px-3 py-2 bg-slate-950 border border-slate-800 rounded-lg text-slate-200 font-mono text-xs focus:outline-none focus:border-emerald-500"
              />
              {errors.max_daily_loss && (
                <span className="text-xs text-rose-400 font-mono mt-1 block">
                  {errors.max_daily_loss.message}
                </span>
              )}
            </div>

            <div>
              <label className="block text-xs font-mono text-slate-400 mb-1">
                Max Total Exposure ($):
              </label>
              <input
                type="number"
                step="any"
                {...register("max_total_exposure")}
                className="w-full px-3 py-2 bg-slate-950 border border-slate-800 rounded-lg text-slate-200 font-mono text-xs focus:outline-none focus:border-emerald-500"
              />
              {errors.max_total_exposure && (
                <span className="text-xs text-rose-400 font-mono mt-1 block">
                  {errors.max_total_exposure.message}
                </span>
              )}
            </div>

            <div>
              <label className="block text-xs font-mono text-slate-400 mb-1">
                Trading Schedule (UTC Window):
              </label>
              <input
                type="text"
                {...register("trading_schedule")}
                className="w-full px-3 py-2 bg-slate-950 border border-slate-800 rounded-lg text-slate-200 font-mono text-xs focus:outline-none focus:border-emerald-500"
              />
              {errors.trading_schedule && (
                <span className="text-xs text-rose-400 font-mono mt-1 block">
                  {errors.trading_schedule.message}
                </span>
              )}
            </div>

            <div className="md:col-span-2">
              <label className="block text-xs font-mono text-slate-400 mb-1">
                Allowed Trading Symbols (Comma-separated):
              </label>
              <input
                type="text"
                {...register("allowed_symbols")}
                className="w-full px-3 py-2 bg-slate-950 border border-slate-800 rounded-lg text-slate-200 font-mono text-xs focus:outline-none focus:border-emerald-500"
              />
              {errors.allowed_symbols && (
                <span className="text-xs text-rose-400 font-mono mt-1 block">
                  {errors.allowed_symbols.message}
                </span>
              )}
            </div>
          </div>

          <div className="flex justify-end pt-2">
            <button
              type="submit"
              disabled={patchConfigMutation.isPending}
              className="px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white font-mono font-bold text-xs transition"
            >
              {patchConfigMutation.isPending ? "Applying Policy..." : "Update Risk Policy"}
            </button>
          </div>
        </form>
      </div>

      <EmergencyStopModal
        isOpen={showStopModal}
        onClose={() => setShowStopModal(false)}
      />
    </div>
  );
}
