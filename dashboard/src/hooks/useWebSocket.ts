import { useEffect, useRef, useState, useCallback } from 'react';
import { WSMessage } from '../types/dashboard';

export interface WebSocketOptions {
  url?: string;
  token?: string;
  onMessage?: (message: WSMessage) => void;
  reconnect?: boolean;
}

export function useWebSocket(options: WebSocketOptions = {}) {
  const {
    url = (typeof window !== 'undefined'
      ? `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/ws/dashboard`
      : 'ws://localhost:8000/ws/dashboard'),
    token,
    onMessage,
    reconnect = true,
  } = options;

  const [isConnected, setIsConnected] = useState(false);
  const [lastMessage, setLastMessage] = useState<WSMessage | null>(null);
  const [connectionError, setConnectionError] = useState<string | null>(null);

  const socketRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const backoffRef = useRef(1000);
  const pingIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const pongTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const onMessageRef = useRef(onMessage);
  onMessageRef.current = onMessage;

  const connect = useCallback(() => {
    try {
      const targetUrl = token ? `${url}?token=${encodeURIComponent(token)}` : url;
      const ws = new WebSocket(targetUrl);
      socketRef.current = ws;

      ws.onopen = () => {
        setIsConnected(true);
        setConnectionError(null);
        backoffRef.current = 1000;

        // Setup ping every 30 seconds
        pingIntervalRef.current = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ action: 'ping' }));
            // Expect pong within 10s
            pongTimeoutRef.current = setTimeout(() => {
              // Missed pong - reconnect
              ws.close();
            }, 10000);
          }
        }, 30000);
      };

      ws.onmessage = (event) => {
        try {
          const parsed: WSMessage = JSON.parse(event.data);
          setLastMessage(parsed);

          if (parsed.event === 'pong') {
            if (pongTimeoutRef.current) {
              clearTimeout(pongTimeoutRef.current);
              pongTimeoutRef.current = null;
            }
          }

          if (onMessageRef.current) {
            onMessageRef.current(parsed);
          }
        } catch {
          // Non-json or malformed message
        }
      };

      ws.onerror = () => {
        setConnectionError('WebSocket encountered a network error');
      };

      ws.onclose = () => {
        setIsConnected(false);
        if (pingIntervalRef.current) clearInterval(pingIntervalRef.current);
        if (pongTimeoutRef.current) clearTimeout(pongTimeoutRef.current);

        if (reconnect) {
          const nextBackoff = Math.min(backoffRef.current * 2, 30000);
          backoffRef.current = nextBackoff;
          reconnectTimeoutRef.current = setTimeout(() => {
            connect();
          }, nextBackoff);
        }
      };
    } catch (err) {
      setConnectionError(String(err));
    }
  }, [url, token, reconnect]);

  useEffect(() => {
    connect();
    return () => {
      if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current);
      if (pingIntervalRef.current) clearInterval(pingIntervalRef.current);
      if (pongTimeoutRef.current) clearTimeout(pongTimeoutRef.current);
      if (socketRef.current) {
        socketRef.current.close();
      }
    };
  }, [connect]);

  const sendAction = useCallback((action: string, symbols?: string[]) => {
    if (socketRef.current && socketRef.current.readyState === WebSocket.OPEN) {
      socketRef.current.send(
        JSON.stringify({
          action,
          ...(symbols ? { symbols } : {}),
        })
      );
    }
  }, []);

  const subscribe = useCallback(
    (symbols: string[]) => sendAction('subscribe', symbols),
    [sendAction]
  );
  const unsubscribe = useCallback(
    (symbols: string[]) => sendAction('unsubscribe', symbols),
    [sendAction]
  );

  return {
    isConnected,
    lastMessage,
    connectionError,
    subscribe,
    unsubscribe,
  };
}
