import React from 'react';
import { ExchangeStatus } from '../types/dashboard';
import { Radio, Wifi, WifiOff, Clock, Tag } from 'lucide-react';

interface ExchangeStatusPanelProps {
  exchanges?: ExchangeStatus[];
  loading?: boolean;
}

const defaultExchanges: ExchangeStatus[] = [
  {
    name: 'binance',
    connected: true,
    latency_ms: 45,
    last_heartbeat: '2026-08-20T10:30:05Z',
    symbols_subscribed: ['BTC/USDT', 'ETH/USDT', 'SOL/USDT'],
  },
  {
    name: 'coinbase',
    connected: false,
    latency_ms: 0,
    last_heartbeat: '2026-08-20T10:25:00Z',
    symbols_subscribed: ['BTC/USD'],
  },
];

export const ExchangeStatusPanel: React.FC<ExchangeStatusPanelProps> = ({
  exchanges = defaultExchanges,
  loading = false,
}) => {
  const list = (exchanges && exchanges.length > 0) ? exchanges : defaultExchanges;

  const formatHeartbeat = (ts: string) => {
    try {
      return new Date(ts).toLocaleTimeString();
    } catch {
      return ts;
    }
  };

  return (
    <div
      className="glass-panel rounded-xl border border-slate-800 bg-slate-900/70 overflow-hidden shadow-xl space-y-4"
      data-testid="exchange-status-panel"
    >
      {/* Header */}
      <div className="px-5 py-4 border-b border-slate-800 flex items-center justify-between">
        <div className="flex items-center space-x-2">
          <Radio className="w-4 h-4 text-emerald-400 animate-pulse" />
          <h3 className="text-sm font-semibold text-slate-200 tracking-wide">
            Exchange Connectivity & Gateways
          </h3>
        </div>
        <span className="text-xs font-mono text-slate-400">
          {list.filter((e) => e.connected).length} / {list.length} Connected
        </span>
      </div>

      {/* Exchange Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 p-5 pt-0">
        {list.map((exch) => (
          <div
            key={exch.name}
            className={`p-4 rounded-xl border transition ${
              exch.connected
                ? 'bg-slate-950/50 border-slate-800 hover:border-slate-700'
                : 'bg-slate-950/20 border-rose-900/40 opacity-75'
            }`}
            data-testid={`exchange-card-${exch.name.toLowerCase()}`}
          >
            {/* Top row: Name & Connection Status */}
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center space-x-2">
                {exch.connected ? (
                  <Wifi className="w-4 h-4 text-emerald-400" />
                ) : (
                  <WifiOff className="w-4 h-4 text-rose-400" />
                )}
                <span className="font-semibold text-slate-100 uppercase font-mono text-sm tracking-wider">
                  {exch.name}
                </span>
              </div>

              <span
                className={`text-xs font-mono px-2 py-0.5 rounded-full font-medium ${
                  exch.connected
                    ? 'bg-emerald-950/80 text-emerald-400 border border-emerald-800'
                    : 'bg-rose-950/80 text-rose-400 border border-rose-800'
                }`}
                data-testid={`exchange-status-${exch.name.toLowerCase()}`}
              >
                {exch.connected ? 'ONLINE' : 'DISCONNECTED'}
              </span>
            </div>

            {/* Metrics */}
            <div className="grid grid-cols-2 gap-2 text-xs font-mono text-slate-400 mb-3 bg-slate-900/50 p-2.5 rounded-lg border border-slate-800/60">
              <div>
                <span className="text-slate-500 block text-[10px] uppercase">Latency</span>
                <span
                  className={`font-semibold ${
                    !exch.connected
                      ? 'text-slate-600'
                      : exch.latency_ms < 60
                      ? 'text-emerald-400'
                      : exch.latency_ms < 150
                      ? 'text-amber-400'
                      : 'text-rose-400'
                  }`}
                  data-testid={`exchange-latency-${exch.name.toLowerCase()}`}
                >
                  {exch.connected ? `${exch.latency_ms} ms` : 'N/A'}
                </span>
              </div>

              <div>
                <span className="text-slate-500 block text-[10px] uppercase flex items-center">
                  <Clock className="w-3 h-3 mr-1" />
                  Heartbeat
                </span>
                <span className="text-slate-300 font-medium">
                  {formatHeartbeat(exch.last_heartbeat)}
                </span>
              </div>
            </div>

            {/* Subscribed Symbols */}
            <div>
              <div className="flex items-center text-[10px] text-slate-500 uppercase tracking-wider font-semibold mb-1.5">
                <Tag className="w-3 h-3 mr-1" />
                Subscribed Feeds
              </div>
              <div className="flex flex-wrap gap-1.5">
                {exch.symbols_subscribed.map((s) => (
                  <span
                    key={s}
                    className="text-[11px] font-mono px-2 py-0.5 rounded bg-slate-800 text-slate-300 border border-slate-700/60"
                  >
                    {s}
                  </span>
                ))}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};
