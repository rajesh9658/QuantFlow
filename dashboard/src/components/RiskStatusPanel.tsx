import React from 'react';
import { RiskStatus } from '../types/dashboard';
import { ShieldAlert, AlertTriangle, CheckCircle2, Flame, Power } from 'lucide-react';

interface RiskStatusPanelProps {
  riskStatus?: RiskStatus | null;
  onToggleEmergencyStop?: (enabled: boolean) => Promise<void> | void;
  loading?: boolean;
}

const defaultRiskStatus: RiskStatus = {
  emergency_stop: false,
  circuit_breaker_active: false,
  daily_pnl: -450.0,
  daily_loss_limit: 1000.0,
  current_exposure: 52216.25,
  max_exposure: 100000.0,
};

export const RiskStatusPanel: React.FC<RiskStatusPanelProps> = ({
  riskStatus = defaultRiskStatus,
  onToggleEmergencyStop,
  loading = false,
}) => {
  const r = riskStatus || defaultRiskStatus;

  // Daily Loss Limit consumption
  const lossConsumed = Math.max(0, -r.daily_pnl);
  const lossLimitPct = Math.min(100, (lossConsumed / (r.daily_loss_limit || 1)) * 100);

  // Exposure consumption
  const exposurePct = Math.min(100, (r.current_exposure / (r.max_exposure || 1)) * 100);

  const formatUsd = (num: number) =>
    new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: 0,
    }).format(num);

  return (
    <div
      className="glass-panel p-5 rounded-xl border border-slate-800 bg-slate-900/70 shadow-xl space-y-5"
      data-testid="risk-status-panel"
    >
      {/* Header */}
      <div className="flex items-center justify-between border-b border-slate-800/80 pb-4">
        <div className="flex items-center space-x-2">
          <ShieldAlert className="w-5 h-5 text-amber-400" />
          <h3 className="text-sm font-semibold text-slate-100 tracking-wide">
            Risk & Circuit Breakers
          </h3>
        </div>

        {/* Circuit Breaker Status Badge */}
        <div className="flex items-center space-x-2">
          <span
            className={`inline-flex items-center px-2.5 py-1 rounded-full text-xs font-mono font-medium ${
              r.circuit_breaker_active
                ? 'bg-rose-950/80 text-rose-400 border border-rose-800 glow-rose'
                : 'bg-emerald-950/80 text-emerald-400 border border-emerald-800'
            }`}
            data-testid="circuit-breaker-badge"
          >
            {r.circuit_breaker_active ? (
              <>
                <Flame className="w-3.5 h-3.5 mr-1 text-rose-400 animate-pulse" />
                Circuit Breaker TRIPPED
              </>
            ) : (
              <>
                <CheckCircle2 className="w-3.5 h-3.5 mr-1 text-emerald-400" />
                Circuit Breakers Normal
              </>
            )}
          </span>
        </div>
      </div>

      {/* Emergency Stop Button */}
      <div
        className={`p-4 rounded-xl border transition-all ${
          r.emergency_stop
            ? 'bg-rose-950/40 border-rose-700/80 glow-rose'
            : 'bg-slate-950/50 border-slate-800'
        }`}
        data-testid="emergency-stop-box"
      >
        <div className="flex items-center justify-between">
          <div className="space-y-0.5">
            <div className="flex items-center space-x-2">
              <Power className={`w-4 h-4 ${r.emergency_stop ? 'text-rose-400' : 'text-slate-400'}`} />
              <span className="text-sm font-semibold text-slate-100">
                Kill Switch / Emergency Stop
              </span>
            </div>
            <p className="text-xs text-slate-400">
              {r.emergency_stop
                ? 'Trading halted: open orders canceled and positions flattened.'
                : 'Instantly cancels all open orders and flattens live positions.'}
            </p>
          </div>

          <button
            type="button"
            disabled={loading}
            onClick={() => onToggleEmergencyStop && onToggleEmergencyStop(!r.emergency_stop)}
            className={`px-4 py-2 rounded-lg font-mono text-xs font-bold uppercase tracking-wider transition-all flex items-center space-x-2 shadow-lg ${
              r.emergency_stop
                ? 'bg-emerald-600 hover:bg-emerald-500 text-white'
                : 'bg-rose-600 hover:bg-rose-500 text-white glow-rose'
            }`}
            data-testid="emergency-stop-toggle-btn"
          >
            <Power className="w-4 h-4" />
            <span>{r.emergency_stop ? 'Deactivate Stop' : 'Engage Emergency Stop'}</span>
          </button>
        </div>
      </div>

      {/* Progress Bars & Risk Limits */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs font-mono">
        {/* Daily Loss Consumption */}
        <div className="p-3.5 rounded-lg bg-slate-950/40 border border-slate-800 space-y-2">
          <div className="flex justify-between items-center text-slate-300">
            <span className="font-sans font-medium text-slate-400">Daily Loss Consumption</span>
            <span
              className={`font-semibold ${lossConsumed > 0 ? 'text-rose-400' : 'text-slate-200'}`}
              data-testid="daily-loss-value"
            >
              -{formatUsd(lossConsumed)} / {formatUsd(r.daily_loss_limit)}
            </span>
          </div>

          <div className="w-full bg-slate-800 h-2 rounded-full overflow-hidden">
            <div
              className={`h-full transition-all duration-500 ${
                lossLimitPct > 80 ? 'bg-rose-500' : lossLimitPct > 50 ? 'bg-amber-500' : 'bg-emerald-500'
              }`}
              style={{ width: `${lossLimitPct}%` }}
              data-testid="loss-limit-bar"
            />
          </div>

          <div className="flex justify-between text-[11px] text-slate-500 font-sans">
            <span>{lossLimitPct.toFixed(1)}% threshold consumed</span>
            <span>Net Day PnL: <strong className={r.daily_pnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}>{formatUsd(r.daily_pnl)}</strong></span>
          </div>
        </div>

        {/* Exposure Utilization */}
        <div className="p-3.5 rounded-lg bg-slate-950/40 border border-slate-800 space-y-2">
          <div className="flex justify-between items-center text-slate-300">
            <span className="font-sans font-medium text-slate-400">Total Exposure Utilization</span>
            <span className="font-semibold text-slate-200" data-testid="exposure-value">
              {formatUsd(r.current_exposure)} / {formatUsd(r.max_exposure)}
            </span>
          </div>

          <div className="w-full bg-slate-800 h-2 rounded-full overflow-hidden">
            <div
              className={`h-full transition-all duration-500 ${
                exposurePct > 85 ? 'bg-rose-500' : exposurePct > 60 ? 'bg-cyan-500' : 'bg-emerald-500'
              }`}
              style={{ width: `${exposurePct}%` }}
              data-testid="exposure-limit-bar"
            />
          </div>

          <div className="flex justify-between text-[11px] text-slate-500 font-sans">
            <span>{exposurePct.toFixed(1)}% limit utilized</span>
            <span>Safety buffer: {formatUsd(Math.max(0, r.max_exposure - r.current_exposure))}</span>
          </div>
        </div>
      </div>
    </div>
  );
};
