import { create } from "zustand";
import { subscribeWithSelector } from "zustand/middleware";

export interface Position {
  symbol: string;
  quantity: number;
  avg_entry_price: number;
  unrealized_pnl: number;
}

export interface PortfolioSnapshot {
  cash: number;
  total_equity: number;
  total_exposure: number;
  realized_pnl: number;
  unrealized_pnl: number;
  positions: Position[];
}

export interface EquityPoint {
  timestamp: string;
  equity: number;
  drawdown: number;
  exposure: number;
}

interface PortfolioState {
  snapshot: PortfolioSnapshot;
  history: EquityPoint[];
  lastUpdate: string | null;
  updateSnapshot: (data: Partial<PortfolioSnapshot>) => void;
  appendHistoryPoint: (point: EquityPoint) => void;
  setHistory: (points: EquityPoint[]) => void;
}

export const usePortfolioStore = create<PortfolioState>()(
  subscribeWithSelector((set) => ({
    snapshot: {
      cash: 100000.0,
      total_equity: 100000.0,
      total_exposure: 0.0,
      realized_pnl: 0.0,
      unrealized_pnl: 0.0,
      positions: [],
    },
    history: [],
    lastUpdate: null,
    updateSnapshot: (data) =>
      set((state) => ({
        snapshot: { ...state.snapshot, ...data },
        lastUpdate: new Date().toISOString(),
      })),
    appendHistoryPoint: (point) =>
      set((state) => ({
        history: [...state.history.slice(-199), point], // keep last 200 points
      })),
    setHistory: (points) => set({ history: points }),
  }))
);
