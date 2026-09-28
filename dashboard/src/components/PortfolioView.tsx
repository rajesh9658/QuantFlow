import React from 'react';
import { PortfolioSnapshot } from '../types/dashboard';
import { Wallet, TrendingUp, TrendingDown, DollarSign, ShieldAlert, Layers } from 'lucide-react';

interface PortfolioViewProps {
  portfolio?: PortfolioSnapshot | null;
  loading?: boolean;
}

const defaultPortfolio: PortfolioSnapshot = {
  cash: 50234.5,
  total_equity: 102450.75,
  total_exposure: 52216.25,
  realized_pnl: 12450.75,
  unrealized_pnl: 2216.25,
  positions: [
    { symbol: 'BTC/USDT', quantity: 0.5, avg_entry_price: 48500.0, unrealized_pnl: 750.0 },
    { symbol: 'ETH/USDT', quantity: 4.2, avg_entry_price: 2750.0, unrealized_pnl: -120.5 },
    { symbol: 'SOL/USDT', quantity: 35.0, avg_entry_price: 135.2, unrealized_pnl: 480.0 },
  ],
};

export const PortfolioView: React.FC<PortfolioViewProps> = ({
  portfolio = defaultPortfolio,
  loading = false,
}) => {
  const p = portfolio || defaultPortfolio;
  const isPositiveRealized = p.realized_pnl >= 0;
  const isPositiveUnrealized = p.unrealized_pnl >= 0;

  const formatUsd = (num: number) =>
    new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: 2,
    }).format(num);

  return (
    <div className="space-y-6" data-testid="portfolio-view">
      {/* Top Metric Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4">
        {/* Total Equity */}
        <div className="glass-panel p-4 rounded-xl border border-slate-800 bg-slate-900/60 shadow-lg relative overflow-hidden group hover:border-slate-700 transition">
          <div className="flex items-center justify-between text-slate-400 mb-2">
            <span className="text-xs font-semibold uppercase tracking-wider">Total Equity</span>
            <Wallet className="w-4 h-4 text-emerald-400" />
          </div>
          <div className="text-2xl font-mono font-bold text-slate-100" data-testid="total-equity">
            {loading ? '---' : formatUsd(p.total_equity)}
          </div>
          <div className="mt-2 flex items-center text-xs text-slate-400">
            <span className="text-slate-500">Cash:</span>
            <span className="ml-1 font-mono text-slate-300" data-testid="cash-value">{formatUsd(p.cash)}</span>
          </div>
        </div>

        {/* Realized PnL */}
        <div className="glass-panel p-4 rounded-xl border border-slate-800 bg-slate-900/60 shadow-lg group hover:border-slate-700 transition">
          <div className="flex items-center justify-between text-slate-400 mb-2">
            <span className="text-xs font-semibold uppercase tracking-wider">Realized PnL</span>
            {isPositiveRealized ? (
              <TrendingUp className="w-4 h-4 text-emerald-400" />
            ) : (
              <TrendingDown className="w-4 h-4 text-rose-400" />
            )}
          </div>
          <div
            className={`text-2xl font-mono font-bold ${
              isPositiveRealized ? 'text-emerald-400' : 'text-rose-400'
            }`}
            data-testid="realized-pnl"
          >
            {loading ? '---' : `${isPositiveRealized ? '+' : ''}${formatUsd(p.realized_pnl)}`}
          </div>
          <span className="text-xs text-slate-500 mt-2 block">Accumulated net</span>
        </div>

        {/* Unrealized PnL */}
        <div className="glass-panel p-4 rounded-xl border border-slate-800 bg-slate-900/60 shadow-lg group hover:border-slate-700 transition">
          <div className="flex items-center justify-between text-slate-400 mb-2">
            <span className="text-xs font-semibold uppercase tracking-wider">Unrealized PnL</span>
            {isPositiveUnrealized ? (
              <TrendingUp className="w-4 h-4 text-emerald-400" />
            ) : (
              <TrendingDown className="w-4 h-4 text-rose-400" />
            )}
          </div>
          <div
            className={`text-2xl font-mono font-bold ${
              isPositiveUnrealized ? 'text-emerald-400' : 'text-rose-400'
            }`}
            data-testid="unrealized-pnl"
          >
            {loading ? '---' : `${isPositiveUnrealized ? '+' : ''}${formatUsd(p.unrealized_pnl)}`}
          </div>
          <span className="text-xs text-slate-500 mt-2 block">Mark-to-market</span>
        </div>

        {/* Total Exposure */}
        <div className="glass-panel p-4 rounded-xl border border-slate-800 bg-slate-900/60 shadow-lg group hover:border-slate-700 transition">
          <div className="flex items-center justify-between text-slate-400 mb-2">
            <span className="text-xs font-semibold uppercase tracking-wider">Total Exposure</span>
            <Layers className="w-4 h-4 text-cyan-400" />
          </div>
          <div className="text-2xl font-mono font-bold text-slate-100" data-testid="total-exposure">
            {loading ? '---' : formatUsd(p.total_exposure)}
          </div>
          <div className="mt-2 text-xs text-slate-500">
            {((p.total_exposure / (p.total_equity || 1)) * 100).toFixed(1)}% of equity
          </div>
        </div>

        {/* Cash Balance */}
        <div className="glass-panel p-4 rounded-xl border border-slate-800 bg-slate-900/60 shadow-lg group hover:border-slate-700 transition">
          <div className="flex items-center justify-between text-slate-400 mb-2">
            <span className="text-xs font-semibold uppercase tracking-wider">Free Cash</span>
            <DollarSign className="w-4 h-4 text-amber-400" />
          </div>
          <div className="text-2xl font-mono font-bold text-slate-100">
            {loading ? '---' : formatUsd(p.cash)}
          </div>
          <span className="text-xs text-slate-500 mt-2 block">Available margin</span>
        </div>
      </div>

      {/* Positions Table */}
      <div className="glass-panel rounded-xl border border-slate-800 bg-slate-900/70 overflow-hidden shadow-xl">
        <div className="px-5 py-4 border-b border-slate-800 flex items-center justify-between">
          <div className="flex items-center space-x-2">
            <Layers className="w-4 h-4 text-cyan-400" />
            <h3 className="text-sm font-semibold text-slate-200 tracking-wide">Open Positions</h3>
          </div>
          <span className="text-xs font-mono px-2 py-0.5 rounded bg-slate-800 text-slate-300">
            {p.positions.length} Active
          </span>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm" data-testid="positions-table">
            <thead>
              <tr className="bg-slate-950/40 text-slate-400 text-xs uppercase tracking-wider border-b border-slate-800/80">
                <th className="px-5 py-3 font-medium">Symbol</th>
                <th className="px-5 py-3 font-medium text-right">Quantity</th>
                <th className="px-5 py-3 font-medium text-right">Avg Entry Price</th>
                <th className="px-5 py-3 font-medium text-right">Notional Value</th>
                <th className="px-5 py-3 font-medium text-right">Unrealized PnL</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/50">
              {p.positions.length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-5 py-8 text-center text-slate-500">
                    No active positions held.
                  </td>
                </tr>
              ) : (
                p.positions.map((pos) => {
                  const notional = Math.abs(pos.quantity) * pos.avg_entry_price;
                  const isPos = pos.unrealized_pnl >= 0;
                  return (
                    <tr
                      key={pos.symbol}
                      className="hover:bg-slate-800/30 transition-colors font-mono"
                      data-testid={`position-row-${pos.symbol.replace('/', '-')}`}
                    >
                      <td className="px-5 py-3.5 font-sans font-semibold text-slate-100 flex items-center space-x-2">
                        <span className="w-2 h-2 rounded-full bg-cyan-400 animate-pulse"></span>
                        <span>{pos.symbol}</span>
                      </td>
                      <td className="px-5 py-3.5 text-right text-slate-200">
                        {pos.quantity > 0 ? `+${pos.quantity}` : pos.quantity}
                      </td>
                      <td className="px-5 py-3.5 text-right text-slate-300">
                        {formatUsd(pos.avg_entry_price)}
                      </td>
                      <td className="px-5 py-3.5 text-right text-slate-300">
                        {formatUsd(notional)}
                      </td>
                      <td
                        className={`px-5 py-3.5 text-right font-semibold ${
                          isPos ? 'text-emerald-400' : 'text-rose-400'
                        }`}
                      >
                        {isPos ? '+' : ''}
                        {formatUsd(pos.unrealized_pnl)}
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};
