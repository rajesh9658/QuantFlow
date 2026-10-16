import { create } from "zustand";
import { subscribeWithSelector } from "zustand/middleware";

interface UIState {
  theme: "dark" | "light";
  sidebarOpen: boolean;
  activeFilters: Record<string, string>;
  toggleTheme: () => void;
  toggleSidebar: () => void;
  setFilter: (key: string, value: string) => void;
  clearFilters: () => void;
}

export const useUIStore = create<UIState>()(
  subscribeWithSelector((set) => ({
    theme: "dark",
    sidebarOpen: true,
    activeFilters: {},
    toggleTheme: () =>
      set((state) => ({ theme: state.theme === "dark" ? "light" : "dark" })),
    toggleSidebar: () =>
      set((state) => ({ sidebarOpen: !state.sidebarOpen })),
    setFilter: (key, value) =>
      set((state) => ({
        activeFilters: { ...state.activeFilters, [key]: value },
      })),
    clearFilters: () => set({ activeFilters: {} }),
  }))
);
