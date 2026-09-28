import React, { useState } from 'react';
import { TradeExecution } from '../types/dashboard';
import { History, Filter, ArrowDownRight, ArrowUpRight } from 'lucide-react';

interface TradeLogProps {
  trades?: TradeExecution[];
  loading?: boolean;
}

const defaultTrades: TradeExecution[] = [
  {
    fill_id: 'f-101',
    order_id: 'ord-101',
    symbol: 'BTC/USDT',
    side: 'buy',
    price: 48500.0,
    quantity: 0.5,
    commission: 12.13,
    timestamp_exchange: '2026-08-20T10:30:00Z',
    realized_pnl: 0.0,
    strategy: 'Simple Momentum',
  },
  {
    fill_id: 'f-102',
    order_id: 'ord-102',
    symbol: 'ETH/USDT',
    side: 'sell',
    price: 2780.5,
    quantity: 1.5,
    commission: 4.17,
    timestamp_exchange: '2026-08-20T09:45:12Z',
    realized_pnl: 145.2,
    strategy: 'Mean Reversion',
  },
  {
    fill_id: 'f-103',
    order_id: 'ord-103',
    symbol: 'SOL/USDT',
    side: 'sell',
    price: 138.4,
    quantity: 10.0,
    commission: 1.38,
    timestamp_exchange: '2026-08-20T08:15:33Z',
    realized_pnl: -32.0,
    strategy: 'Breakout Hunter',
  },
];

export const TradeLog: React.FC<TradeLogProps> = ({
  trades = defaultTrades,
  loading = false,
}) => {
  const [filterSide, setFilterSide] = useState<string>('all');
  const [search, setSearch] = useState<string>('');

  const list = (trades && trades.length > 0) ? trades : defaultTrades;

  const filtered = list.filter((t) => {
    if (filterSide !== 'all' && t.side.toLowerCase() !== filterSide.toLowerCase()) {
      return false;
    }
    if (search && !t.symbol.toLowerCase().includes(search.toLowerCase())) {
      return false;
    }
    return true;
  });

  const formatUsd = (num: number) =>
    new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: 2,
    }).format(num);

  const formatTime = (ts: string) => {
    try {
      return new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    } catch {
      return ts;
    }
  };

  return (
    <div
      className="glass-panel rounded-xl border border-slate-800 bg-slate-900/70 overflow-hidden shadow-xl"
      data-testid="trade-log-panel"
    >
      {/* Header & Filter Controls */}
      <div className="px-5 py-4 border-b border-slate-800 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center space-x-2">
          <History className="w-4 h-4 text-cyan-400" />
          <h3 className="text-sm font-semibold text-slate-200 tracking-wide">
            Execution Log & Trades
          </h3>
          <span className="text-xs font-mono px-2 py-0.5 rounded bg-slate-800 text-slate-300">
            {filtered.length} Fills
          </span>
        </div>

        <div className="flex items-center space-x-2 text-xs">
          {/* Side Filter Buttons */}
          <div className="flex rounded-lg bg-slate-950/80 p-0.5 border border-slate-800">
            {['all', 'buy', 'sell'].map((s) => (
              <button
                key={s}
                onClick={() => setFilterSide(s)}
                className={`px-2.5 py-1 rounded-md capitalize font-mono text-xs transition ${
                  filterSide === s
                    ? 'bg-slate-800 text-slate-100 font-semibold shadow-sm'
                    : 'text-slate-400 hover:text-slate-200'
                }`}
                data-testid={`filter-${s}`}
              >
                {s}
              </button>
            ))}
          </div>

          {/* Search Input */}
          <input
            type="text"
            placeholder="Search symbol..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="bg-slate-950/80 border border-slate-800 rounded-lg px-2.5 py-1 text-slate-200 placeholder-slate-500 focus:outline-none focus:border-cyan-500 font-mono text-xs"
            data-testid="trade-search-input"
          />
        </div>
      </div>

      {/* Trade Log Table */}
      <div className="overflow-x-auto max-h-80 overflow-y-auto">
        <table className="w-full text-left text-sm font-mono" data-testid="trades-table">
          <thead className="sticky top-0 bg-slate-950/90 backdrop-blur border-b border-slate-800 text-slate-400 text-xs uppercase tracking-wider">
            <tr>
              <th className="px-4 py-3 font-medium">Time</th>
              <th className="px-4 py-3 font-medium">Symbol</th>
              <th className="px-4 py-3 font-medium">Side</th>
              <th className="px-4 py-3 font-medium text-right">Fill Price</th>
              <th className="px-4 py-3 font-medium text-right">Qty</th>
              <th className="px-4 py-3 font-medium text-right">Fee</th>
              <th className="px-4 py-3 font-medium text-right">Realized PnL</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800/50 text-xs">
            {loading ? (
              <tr>
                <td colSpan={7} className="px-4 py-6 text-center text-slate-500">
                  Streaming trades...
                </td>
              </tr>
            ) : filtered.length === 0 ? (
              <tr>
                <td colSpan={7} className="px-4 py-6 text-center text-slate-500 font-sans">
                  No matching trade executions found.
                </td>
              </tr>
            ) : (
              filtered.map((t) => {
                const isBuy = t.side.toLowerCase() === 'buy';
                const hasPnl = t.realized_pnl !== 0;
                const isProfitable = t.realized_pnl > 0;

                return (
                  <tr
                    key={t.fill_id}
                    className="hover:bg-slate-800/30 transition-colors"
                    data-testid={`trade-row-${t.fill_id}`}
                  >
                    <td className="px-4 py-3 text-slate-400 whitespace-nowrap">
                      {formatTime(t.timestamp_exchange)}
                    </td>
                    <td className="px-4 py-3 font-sans font-semibold text-slate-200">
                      {t.symbol}
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`inline-flex items-center px-2 py-0.5 rounded text-[11px] font-semibold uppercase tracking-wider ${
                          isBuy
                            ? 'bg-emerald-950/70 text-emerald-400 border border-emerald-800/60'
                            : 'bg-rose-950/70 text-rose-400 border border-rose-800/60'
                        }`}
                        data-testid={`trade-badge-${t.side.toLowerCase()}`}
                      >
                        {isBuy ? (
                          <ArrowUpRight className="w-3 h-3 mr-0.5" />
                        ) : (
                          <ArrowDownRight className="w-3 h-3 mr-0.5" />
                        )}
                        {t.side}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right text-slate-200 font-medium">
                      {formatUsd(t.price)}
                    </td>
                    <td className="px-4 py-3 text-right text-slate-300">
                      {t.quantity}
                    </td>
                    <td className="px-4 py-3 text-right text-slate-500">
                      ${t.commission.toFixed(2)}
                    </td>
                    <td
                      className={`px-4 py-3 text-right font-semibold ${
                        !hasPnl
                          ? 'text-slate-500'
                          : isProfitable
                          ? 'text-emerald-400'
                          : 'text-rose-400'
                      }`}
                      data-testid={`trade-pnl-${t.fill_id}`}
                    >
                      {hasPnl ? `${isProfitable ? '+' : ''}${formatUsd(t.realized_pnl)}` : '--'}
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
};
