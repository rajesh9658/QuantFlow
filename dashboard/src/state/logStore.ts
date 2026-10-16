import { create } from "zustand";
import { subscribeWithSelector } from "zustand/middleware";

export interface LogEntry {
  correlation_id: string;
  level: string;
  logger_name: string;
  message: string;
  metadata?: Record<string, unknown>;
  received_at: string;
}

const MAX_LOGS = 1000; // non-configurable: ring buffer limit per spec B3

interface LogState {
  logs: LogEntry[];
  paused: boolean;
  addLog: (entry: LogEntry) => void;
  setLogs: (entries: LogEntry[]) => void;
  togglePause: () => void;
  clear: () => void;
}

export const useLogStore = create<LogState>()(
  subscribeWithSelector((set) => ({
    logs: [],
    paused: false,
    addLog: (entry) =>
      set((state) => {
        if (state.paused) return state;
        const newLogs = [...state.logs, entry];
        if (newLogs.length > MAX_LOGS) {
          return { logs: newLogs.slice(newLogs.length - MAX_LOGS) };
        }
        return { logs: newLogs };
      }),
    setLogs: (entries) => set({ logs: entries.slice(-MAX_LOGS) }),
    togglePause: () => set((state) => ({ paused: !state.paused })),
    clear: () => set({ logs: [] }),
  }))
);
