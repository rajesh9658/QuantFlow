import React, { useState } from 'react';
import { EquityCurvePoint } from '../types/dashboard';
import { Activity, ArrowUpRight, ArrowDownRight } from 'lucide-react';

interface PnLChartProps {
  data?: EquityCurvePoint[];
  loading?: boolean;
}

const defaultPoints: EquityCurvePoint[] = [
  { timestamp: '2026-08-10', equity: 100000, drawdown: 0.0, exposure: 45000 },
  { timestamp: '2026-08-11', equity: 101200, drawdown: 0.0, exposure: 48000 },
  { timestamp: '2026-08-12', equity: 100800, drawdown: 0.0039, exposure: 46000 },
  { timestamp: '2026-08-13', equity: 102400, drawdown: 0.0, exposure: 52000 },
  { timestamp: '2026-08-14', equity: 101900, drawdown: 0.0048, exposure: 50000 },
  { timestamp: '2026-08-15', equity: 103500, drawdown: 0.0, exposure: 51000 },
  { timestamp: '2026-08-16', equity: 104200, drawdown: 0.0, exposure: 53000 },
  { timestamp: '2026-08-17', equity: 103800, drawdown: 0.0038, exposure: 49000 },
  { timestamp: '2026-08-18', equity: 105100, drawdown: 0.0, exposure: 54000 },
  { timestamp: '2026-08-19', equity: 106300, drawdown: 0.0, exposure: 55000 },
  { timestamp: '2026-08-20', equity: 108450, drawdown: 0.0, exposure: 52216 },
];

export const PnLChart: React.FC<PnLChartProps> = ({
  data = defaultPoints,
  loading = false,
}) => {
  const points = (data && data.length > 0) ? data : defaultPoints;
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);

  const equities = points.map((p) => p.equity);
  const minEquity = Math.min(...equities) * 0.995;
  const maxEquity = Math.max(...equities) * 1.005;
  const initialEquity = equities[0] || 1;
  const currentEquity = equities[equities.length - 1] || 1;
  const totalReturnPct = ((currentEquity - initialEquity) / initialEquity) * 100;
  const maxDrawdownPct = Math.max(...points.map((p) => p.drawdown)) * 100;

  // Chart dimensions
  const width = 800;
  const height = 240;
  const padding = { top: 20, right: 20, bottom: 30, left: 60 };
  const plotWidth = width - padding.left - padding.right;
  const plotHeight = height - padding.top - padding.bottom;

  const getX = (index: number) =>
    padding.left + (index / (points.length - 1 || 1)) * plotWidth;

  const getY = (val: number) =>
    padding.top +
    plotHeight -
    ((val - minEquity) / (maxEquity - minEquity || 1)) * plotHeight;

  // Build SVG Path
  const pathD = points.reduce((acc, pt, i) => {
    const x = getX(i);
    const y = getY(pt.equity);
    return i === 0 ? `M ${x} ${y}` : `${acc} L ${x} ${y}`;
  }, '');

  const areaD = `${pathD} L ${getX(points.length - 1)} ${padding.top + plotHeight} L ${getX(0)} ${padding.top + plotHeight} Z`;

  const activePoint = hoverIndex !== null ? points[hoverIndex] : points[points.length - 1];

  const formatUsd = (v: number) =>
    new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      maximumFractionDigits: 0,
    }).format(v);

  return (
    <div
      className="glass-panel p-5 rounded-xl border border-slate-800 bg-slate-900/70 shadow-xl space-y-4"
      data-testid="pnl-chart-panel"
    >
      {/* Header with Title & Stat Summary */}
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-slate-800/80 pb-4">
        <div className="flex items-center space-x-2">
          <Activity className="w-5 h-5 text-emerald-400" />
          <h3 className="text-sm font-semibold text-slate-100 tracking-wide">
            Portfolio Performance & Equity Curve
          </h3>
        </div>

        <div className="flex items-center space-x-6 text-xs font-mono">
          <div>
            <span className="text-slate-500 block text-[10px] uppercase">Net Return</span>
            <span
              className={`font-semibold flex items-center ${
                totalReturnPct >= 0 ? 'text-emerald-400' : 'text-rose-400'
              }`}
              data-testid="net-return"
            >
              {totalReturnPct >= 0 ? (
                <ArrowUpRight className="w-3.5 h-3.5 mr-0.5" />
              ) : (
                <ArrowDownRight className="w-3.5 h-3.5 mr-0.5" />
              )}
              {totalReturnPct >= 0 ? '+' : ''}
              {totalReturnPct.toFixed(2)}%
            </span>
          </div>

          <div>
            <span className="text-slate-500 block text-[10px] uppercase">Max Drawdown</span>
            <span className="font-semibold text-rose-400" data-testid="max-drawdown">
              -{maxDrawdownPct.toFixed(2)}%
            </span>
          </div>

          <div>
            <span className="text-slate-500 block text-[10px] uppercase">Peak Equity</span>
            <span className="font-semibold text-slate-200" data-testid="peak-equity">
              {formatUsd(Math.max(...equities))}
            </span>
          </div>
        </div>
      </div>

      {/* SVG Chart Rendering */}
      <div className="relative w-full overflow-hidden" style={{ minHeight: `${height}px` }}>
        {loading ? (
          <div className="h-60 flex items-center justify-center text-slate-500 text-sm font-mono">
            Loading equity curve telemetry...
          </div>
        ) : (
          <>
            <svg
              viewBox={`0 0 ${width} ${height}`}
              className="w-full h-auto overflow-visible select-none"
              data-testid="pnl-chart-svg"
            >
              <defs>
                <linearGradient id="equityGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#10b981" stopOpacity="0.35" />
                  <stop offset="100%" stopColor="#10b981" stopOpacity="0.0" />
                </linearGradient>
              </defs>

              {/* Grid Lines */}
              {[0, 0.25, 0.5, 0.75, 1].map((ratio) => {
                const y = padding.top + plotHeight * ratio;
                const val = maxEquity - ratio * (maxEquity - minEquity);
                return (
                  <g key={ratio}>
                    <line
                      x1={padding.left}
                      y1={y}
                      x2={width - padding.right}
                      y2={y}
                      stroke="#1e293b"
                      strokeDasharray="3 3"
                    />
                    <text
                      x={padding.left - 8}
                      y={y + 4}
                      fill="#64748b"
                      fontSize="10"
                      textAnchor="end"
                      fontFamily="monospace"
                    >
                      {formatUsd(val)}
                    </text>
                  </g>
                );
              })}

              {/* Area Under Curve */}
              <path d={areaD} fill="url(#equityGrad)" />

              {/* Equity Line */}
              <path
                d={pathD}
                fill="none"
                stroke="#10b981"
                strokeWidth="2.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              />

              {/* Hover Indicator */}
              {hoverIndex !== null && (
                <g>
                  <line
                    x1={getX(hoverIndex)}
                    y1={padding.top}
                    x2={getX(hoverIndex)}
                    y2={padding.top + plotHeight}
                    stroke="#06b6d4"
                    strokeWidth="1.5"
                    strokeDasharray="2 2"
                  />
                  <circle
                    cx={getX(hoverIndex)}
                    cy={getY(points[hoverIndex].equity)}
                    r="4.5"
                    fill="#06b6d4"
                    stroke="#0f172a"
                    strokeWidth="2"
                  />
                </g>
              )}

              {/* Transparent Overlay for Mouse Tracking */}
              {points.map((_, i) => {
                const x = getX(i);
                const barWidth = plotWidth / points.length;
                return (
                  <rect
                    key={i}
                    x={x - barWidth / 2}
                    y={padding.top}
                    width={barWidth}
                    height={plotHeight}
                    fill="transparent"
                    className="cursor-crosshair"
                    onMouseEnter={() => setHoverIndex(i)}
                    onMouseLeave={() => setHoverIndex(null)}
                  />
                );
              })}
            </svg>

            {/* Hover Tooltip Overlay */}
            {activePoint && (
              <div
                className="mt-2 flex items-center justify-between text-xs font-mono text-slate-400 bg-slate-950/60 px-3 py-1.5 rounded border border-slate-800"
                data-testid="pnl-tooltip"
              >
                <span>Date: <strong className="text-slate-200">{activePoint.timestamp}</strong></span>
                <span>Equity: <strong className="text-emerald-400">{formatUsd(activePoint.equity)}</strong></span>
                <span>Drawdown: <strong className="text-rose-400">-{(activePoint.drawdown * 100).toFixed(2)}%</strong></span>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
};
