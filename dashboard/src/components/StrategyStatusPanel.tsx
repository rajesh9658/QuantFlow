import React from 'react';
import { StrategySummary } from '../types/dashboard';
import { Cpu, Check, X, TrendingUp, Percent, Hash } from 'lucide-react';

interface StrategyStatusPanelProps {
  strategies?: StrategySummary[];
  onToggleStrategy?: (name: string, active: boolean) => Promise<void> | void;
  loading?: boolean;
}

const defaultStrategies: StrategySummary[] = [
  {
    name: 'Simple Momentum',
    version: '1.2.0',
    active: true,
    config: { period: 20, threshold: 0.02 },
    metrics: { win_rate: 0.65, sharpe: 1.85, total_trades: 142 },
  },
  {
    name: 'Mean Reversion',
    version: '0.9.4',
    active: true,
    config: { z_score_entry: 2.0, exit_window: 10 },
    metrics: { win_rate: 0.58, sharpe: 1.42, total_trades: 89 },
  },
  {
    name: 'Breakout Hunter',
    version: '2.0.1',
    active: false,
    config: { lookback: 50, vol_mult: 1.5 },
    metrics: { win_rate: 0.44, sharpe: 0.95, total_trades: 34 },
  },
];

export const StrategyStatusPanel: React.FC<StrategyStatusPanelProps> = ({
  strategies = defaultStrategies,
  onToggleStrategy,
  loading = false,
}) => {
  const list = (strategies && strategies.length > 0) ? strategies : defaultStrategies;

  return (
    <div
      className="glass-panel rounded-xl border border-slate-800 bg-slate-900/70 overflow-hidden shadow-xl space-y-3"
      data-testid="strategy-status-panel"
    >
      {/* Header */}
      <div className="px-5 py-4 border-b border-slate-800 flex items-center justify-between">
        <div className="flex items-center space-x-2">
          <Cpu className="w-4 h-4 text-cyan-400" />
          <h3 className="text-sm font-semibold text-slate-200 tracking-wide">
            Strategy Engine Plugins
          </h3>
        </div>
        <span className="text-xs font-mono px-2 py-0.5 rounded bg-slate-800 text-slate-300">
          {list.filter((s) => s.active).length} / {list.length} Online
        </span>
      </div>

      {/* Strategies List */}
      <div className="divide-y divide-slate-800/60 p-2">
        {list.map((strat) => (
          <div
            key={strat.name}
            className="p-3.5 rounded-lg hover:bg-slate-800/20 transition flex flex-col md:flex-row md:items-center justify-between gap-4"
            data-testid={`strategy-item-${strat.name.toLowerCase().replace(/\s+/g, '-')}`}
          >
            {/* Name & Details */}
            <div className="space-y-1">
              <div className="flex items-center space-x-2">
                <span
                  className={`w-2.5 h-2.5 rounded-full ${
                    strat.active ? 'bg-emerald-400 animate-pulse' : 'bg-slate-600'
                  }`}
                  data-testid={`strategy-status-dot-${strat.name.toLowerCase().replace(/\s+/g, '-')}`}
                />
                <h4 className="font-semibold text-slate-100 text-sm">{strat.name}</h4>
                <span className="text-[11px] font-mono text-slate-500 bg-slate-950 px-1.5 py-0.5 rounded border border-slate-800">
                  v{strat.version}
                </span>
              </div>
              <div className="text-xs text-slate-400 font-mono">
                Parameters: {JSON.stringify(strat.config)}
              </div>
            </div>

            {/* Metrics & Toggle */}
            <div className="flex items-center space-x-6">
              {/* Telemetry Metrics */}
              <div className="grid grid-cols-3 gap-3 text-right text-xs font-mono">
                <div>
                  <span className="text-slate-500 block text-[10px] uppercase">Sharpe</span>
                  <span className="text-emerald-400 font-semibold">{strat.metrics.sharpe.toFixed(2)}</span>
                </div>
                <div>
                  <span className="text-slate-500 block text-[10px] uppercase">Win Rate</span>
                  <span className="text-slate-200 font-semibold">{(strat.metrics.win_rate * 100).toFixed(0)}%</span>
                </div>
                <div>
                  <span className="text-slate-500 block text-[10px] uppercase">Trades</span>
                  <span className="text-slate-400 font-semibold">{strat.metrics.total_trades}</span>
                </div>
              </div>

              {/* Active Toggle Switch */}
              <button
                type="button"
                disabled={loading}
                onClick={() => onToggleStrategy && onToggleStrategy(strat.name, !strat.active)}
                className={`w-12 h-6 flex items-center rounded-full p-1 transition-colors ${
                  strat.active ? 'bg-emerald-500 justify-end' : 'bg-slate-700 justify-start'
                }`}
                data-testid={`strategy-toggle-${strat.name.toLowerCase().replace(/\s+/g, '-')}`}
                aria-label={`Toggle ${strat.name}`}
              >
                <span className="bg-white w-4 h-4 rounded-full shadow-md transform transition-transform" />
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};
