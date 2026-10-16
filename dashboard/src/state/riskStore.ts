import { create } from "zustand";
import { subscribeWithSelector } from "zustand/middleware";

export interface RiskStatus {
  emergency_stop: boolean;
  circuit_breaker_active: boolean;
  daily_pnl: number;
  daily_loss_limit: number;
  current_exposure: number;
  max_exposure: number;
}

export interface RiskConfig {
  max_position_qty: number;
  max_daily_loss: number;
  max_total_exposure: number;
  allowed_symbols: string[];
  trading_schedule: string;
}

interface RiskState {
  status: RiskStatus;
  config: RiskConfig;
  emergencyStop: boolean;
  updateStatus: (data: Partial<RiskStatus>) => void;
  updateConfig: (data: Partial<RiskConfig>) => void;
  setEmergencyStop: (active: boolean) => void;
}

export const useRiskStore = create<RiskState>()(
  subscribeWithSelector((set) => ({
    status: {
      emergency_stop: false,
      circuit_breaker_active: false,
      daily_pnl: 0.0,
      daily_loss_limit: 1000.0,
      current_exposure: 0.0,
      max_exposure: 100000.0,
    },
    config: {
      max_position_qty: 5.0,
      max_daily_loss: 1000.0,
      max_total_exposure: 100000.0,
      allowed_symbols: ["BTC/USDT", "ETH/USDT"],
      trading_schedule: "00:00-23:59",
    },
    emergencyStop: false,
    updateStatus: (data) =>
      set((state) => ({
        status: { ...state.status, ...data },
        emergencyStop: data.emergency_stop !== undefined ? data.emergency_stop : state.emergencyStop,
      })),
    updateConfig: (data) =>
      set((state) => ({
        config: { ...state.config, ...data },
      })),
    setEmergencyStop: (active) =>
      set((state) => ({
        emergencyStop: active,
        status: { ...state.status, emergency_stop: active },
      })),
  }))
);
