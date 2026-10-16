import React, { createContext, useContext, useEffect, useRef, useState, useCallback } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { env } from "../../config/env";
import { routeWsMessage, WSEnvelope } from "./wsRouter";

export type ConnectionStatus = "connecting" | "connected" | "disconnected" | "reconnecting";

export interface WebSocketContextValue {
  status: ConnectionStatus;
  isStale: boolean;
  isDisconnected: boolean;
  lastMessageAt: Date | null;
  sendAction: (action: string, payload?: Record<string, unknown>) => void;
  subscribeSymbols: (symbols: string[]) => void;
  unsubscribeSymbols: (symbols: string[]) => void;
}

const WebSocketContext = createContext<WebSocketContextValue | null>(null);

export function WebSocketProvider({ children }: { children: React.ReactNode }) {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<ConnectionStatus>("connecting");
  const [lastMessageAt, setLastMessageAt] = useState<Date | null>(null);
  const [isStale, setIsStale] = useState<boolean>(false);
  const [isDisconnected, setIsDisconnected] = useState<boolean>(false);

  const socketRef = useRef<WebSocket | null>(null);
  const reconnectAttemptRef = useRef<number>(0);
  const reconnectTimerRef = useRef<number | null>(null);
  const pingTimerRef = useRef<number | null>(null);
  const staleTimerRef = useRef<number | null>(null);
  const symbolRefCounts = useRef<Map<string, number>>(new Map());

  const sendRaw = useCallback((data: Record<string, unknown>) => {
    if (socketRef.current && socketRef.current.readyState === WebSocket.OPEN) {
      socketRef.current.send(JSON.stringify(data));
    }
  }, []);

  const sendAction = useCallback(
    (action: string, payload: Record<string, unknown> = {}) => {
      sendRaw({ action, ...payload });
    },
    [sendRaw]
  );

  const subscribeSymbols = useCallback(
    (symbols: string[]) => {
      const newlySubscribed: string[] = [];
      for (const sym of symbols) {
        const count = symbolRefCounts.current.get(sym) || 0;
        symbolRefCounts.current.set(sym, count + 1);
        if (count === 0) {
          newlySubscribed.push(sym);
        }
      }
      if (newlySubscribed.length > 0) {
        sendRaw({ action: "subscribe", symbols: newlySubscribed });
      }
    },
    [sendRaw]
  );

  const unsubscribeSymbols = useCallback(
    (symbols: string[]) => {
      const toUnsubscribe: string[] = [];
      for (const sym of symbols) {
        const count = symbolRefCounts.current.get(sym) || 0;
        if (count <= 1) {
          symbolRefCounts.current.delete(sym);
          toUnsubscribe.push(sym);
        } else {
          symbolRefCounts.current.set(sym, count - 1);
        }
      }
      if (toUnsubscribe.length > 0) {
        sendRaw({ action: "unsubscribe", symbols: toUnsubscribe });
      }
    },
    [sendRaw]
  );

  const connect = useCallback(() => {
    if (socketRef.current) {
      try {
        socketRef.current.close();
      } catch {
        // ignore
      }
    }

    setStatus((prev) => (prev === "connected" ? "reconnecting" : "connecting"));

    let wsUrl = env.VITE_WS_URL;
    if (env.VITE_AUTH_MODE === "dev-bypass") {
      const delimiter = wsUrl.includes("?") ? "&" : "?";
      wsUrl = `${wsUrl}${delimiter}token=dev-bypass-token`;
    }

    const ws = new WebSocket(wsUrl);
    socketRef.current = ws;

    ws.onopen = () => {
      setStatus("connected");
      reconnectAttemptRef.current = 0;
      setLastMessageAt(new Date());
      setIsStale(false);
      setIsDisconnected(false);

      // Re-subscribe any currently active symbols
      const activeSymbols = Array.from(symbolRefCounts.current.keys());
      if (activeSymbols.length > 0) {
        ws.send(JSON.stringify({ action: "subscribe", symbols: activeSymbols }));
      }

      // Invalidate active queries on reconnect per spec B7
      queryClient.invalidateQueries();
    };

    ws.onmessage = (event) => {
      const now = new Date();
      setLastMessageAt(now);
      setIsStale(false);
      setIsDisconnected(false);

      try {
        const envelope: WSEnvelope = JSON.parse(event.data);
        routeWsMessage(envelope, queryClient);
      } catch (err) {
        console.warn("Failed to parse WS envelope:", err);
      }
    };

    ws.onclose = () => {
      setStatus("disconnected");
      scheduleReconnect();
    };

    ws.onerror = () => {
      try {
        ws.close();
      } catch {
        // ignore
      }
    };
  }, [queryClient, sendRaw]);

  const scheduleReconnect = useCallback(() => {
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current);
    }

    const attempt = reconnectAttemptRef.current;
    // Exponential backoff with jitter capped at VITE_RECONNECT_MAX_MS
    const base = env.VITE_RECONNECT_BASE_MS;
    const max = env.VITE_RECONNECT_MAX_MS;
    const exponential = Math.min(base * Math.pow(1.5, attempt), max); // non-configurable: backoff growth factor
    const jitter = Math.random() * 500; // non-configurable: random jitter
    const delay = Math.min(exponential + jitter, max);

    reconnectAttemptRef.current = attempt + 1;
    setStatus("reconnecting");

    reconnectTimerRef.current = window.setTimeout(() => {
      connect();
    }, delay);
  }, [connect]);

  // Connect on mount
  useEffect(() => {
    connect();

    // Ping interval
    pingTimerRef.current = window.setInterval(() => {
      if (socketRef.current && socketRef.current.readyState === WebSocket.OPEN) {
        sendRaw({ action: "ping" });
      }
    }, env.VITE_WS_PING_INTERVAL_MS);

    // Stale guard check interval: 10s stale, 30s disconnected per spec B7
    staleTimerRef.current = window.setInterval(() => {
      if (!lastMessageAt) return;
      const elapsed = Date.now() - lastMessageAt.getTime();
      if (elapsed > 30000) { // non-configurable: 30s disconnection threshold per Spec B7
        setIsDisconnected(true);
        setIsStale(true);
      } else if (elapsed > 10000) { // non-configurable: 10s staleness threshold per Spec B7
        setIsStale(true);
        setIsDisconnected(false);
      } else {
        setIsStale(false);
        setIsDisconnected(false);
      }
    }, 2000); // non-configurable: 2s check interval

    return () => {
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
      if (pingTimerRef.current) clearInterval(pingTimerRef.current);
      if (staleTimerRef.current) clearInterval(staleTimerRef.current);
      if (socketRef.current) {
        socketRef.current.close();
      }
    };
  }, [connect, lastMessageAt, sendRaw]);

  return (
    <WebSocketContext.Provider
      value={{
        status,
        isStale,
        isDisconnected,
        lastMessageAt,
        sendAction,
        subscribeSymbols,
        unsubscribeSymbols,
      }}
    >
      {children}
    </WebSocketContext.Provider>
  );
}

export function useWebSocketContext(): WebSocketContextValue {
  const ctx = useContext(WebSocketContext);
  if (!ctx) {
    throw new Error("useWebSocketContext must be used within a WebSocketProvider");
  }
  return ctx;
}
