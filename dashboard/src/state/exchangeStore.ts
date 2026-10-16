import { create } from "zustand";
import { subscribeWithSelector } from "zustand/middleware";

export interface ExchangeStatus {
  id: string;
  name: string;
  type: string;
  enabled: boolean;
  connected: boolean;
  latency_ms: number;
  last_heartbeat?: string;
  symbols_subscribed: string[];
}

interface ExchangeState {
  exchanges: Record<string, ExchangeStatus>;
  setExchanges: (list: ExchangeStatus[]) => void;
  updateExchange: (id: string, partial: Partial<ExchangeStatus>) => void;
}

export const useExchangeStore = create<ExchangeState>()(
  subscribeWithSelector((set) => ({
    exchanges: {},
    setExchanges: (list) => {
      const map: Record<string, ExchangeStatus> = {};
      for (const ex of list) {
        map[ex.id] = ex;
      }
      set({ exchanges: map });
    },
    updateExchange: (id, partial) =>
      set((state) => {
        const existing = state.exchanges[id] || {
          id,
          name: id,
          type: "crypto",
          enabled: true,
          connected: true,
          latency_ms: 0,
          symbols_subscribed: [],
        };
        return {
          exchanges: {
            ...state.exchanges,
            [id]: { ...existing, ...partial },
          },
        };
      }),
  }))
);
