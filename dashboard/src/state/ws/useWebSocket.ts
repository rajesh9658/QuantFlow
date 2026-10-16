import { useEffect } from "react";
import { useWebSocketContext } from "./WebSocketProvider";
import { useTickerStore, TickerData } from "../tickerStore";

export function useWebSocket() {
  return useWebSocketContext();
}

/**
 * Automatically subscribes to symbols on mount and unsubscribes on unmount.
 * Handles ref-counting through WebSocketProvider.
 */
export function useSymbolSubscription(symbols: string[]) {
  const { subscribeSymbols, unsubscribeSymbols } = useWebSocketContext();

  useEffect(() => {
    if (!symbols || symbols.length === 0) return;
    subscribeSymbols(symbols);
    return () => {
      unsubscribeSymbols(symbols);
    };
  }, [symbols, subscribeSymbols, unsubscribeSymbols]);
}

/**
 * Returns latest ticker data from Zustand store and manages symbol subscription.
 */
export function useTicker(symbol: string): TickerData | undefined {
  useSymbolSubscription([symbol]);
  return useTickerStore((state) => state.bySymbol[symbol]);
}
