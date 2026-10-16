import { create } from "zustand";
import { subscribeWithSelector } from "zustand/middleware";

export interface TickerData {
  symbol: string;
  bid: number;
  ask: number;
  last: number;
  timestamp?: string;
}

interface TickerState {
  bySymbol: Record<string, TickerData>;
  updateTicker: (data: TickerData) => void;
}

export const useTickerStore = create<TickerState>()(
  subscribeWithSelector((set) => ({
    bySymbol: {},
    updateTicker: (data) =>
      set((state) => ({
        bySymbol: {
          ...state.bySymbol,
          [data.symbol]: {
            ...data,
            timestamp: new Date().toISOString(),
          },
        },
      })),
  }))
);
