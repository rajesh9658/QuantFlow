import { QueryClient } from "@tanstack/react-query";
import { usePortfolioStore } from "../portfolioStore";
import { useRiskStore } from "../riskStore";
import { useExchangeStore } from "../exchangeStore";
import { useLogStore } from "../logStore";
import { useTickerStore } from "../tickerStore";

export interface WSEnvelope<T = unknown> {
  event: string;
  timestamp: string;
  data: T;
}

export function routeWsMessage(
  envelope: WSEnvelope,
  queryClient: QueryClient
): void {
  const { event, data } = envelope;

  switch (event) {
    case "connected":
      // Handshake established
      break;

    case "portfolio_update": {
      const pData = data as any;
      usePortfolioStore.getState().updateSnapshot({
        cash: pData.cash,
        total_equity: pData.total_equity,
        total_exposure: pData.total_exposure,
        realized_pnl: pData.realized_pnl,
        unrealized_pnl: pData.unrealized_pnl,
        positions: pData.positions || [],
      });
      // Append equity curve point
      usePortfolioStore.getState().appendHistoryPoint({
        timestamp: envelope.timestamp,
        equity: pData.total_equity,
        drawdown: pData.total_equity > 0 ? (pData.unrealized_pnl < 0 ? Math.abs(pData.unrealized_pnl) / pData.total_equity : 0) : 0,
        exposure: pData.total_exposure,
      });
      // Query invalidation per Spec B3 Rule 4
      queryClient.invalidateQueries({ queryKey: ["portfolio"] });
      break;
    }

    case "fill": {
      // Refresh historical trades & orders tables
      queryClient.invalidateQueries({ queryKey: ["trades"] });
      queryClient.invalidateQueries({ queryKey: ["orders"] });
      break;
    }

    case "signal": {
      queryClient.invalidateQueries({ queryKey: ["signals"] });
      break;
    }

    case "risk_status": {
      const rData = data as any;
      useRiskStore.getState().updateStatus({
        emergency_stop: rData.emergency_stop,
        circuit_breaker_active: rData.circuit_breaker_active,
        daily_pnl: rData.daily_pnl,
        daily_loss_limit: rData.daily_loss_limit,
        current_exposure: rData.current_exposure,
        max_exposure: rData.max_exposure,
      });
      break;
    }

    case "exchange_status": {
      const eData = data as any;
      if (eData.name) {
        useExchangeStore.getState().updateExchange(eData.name, {
          connected: eData.connected,
          latency_ms: eData.latency_ms,
          last_heartbeat: eData.last_heartbeat,
          symbols_subscribed: eData.symbols_subscribed,
        });
      }
      break;
    }

    case "log": {
      const lData = data as any;
      useLogStore.getState().addLog({
        correlation_id: lData.correlation_id || "system",
        level: lData.level || "INFO",
        logger_name: lData.logger_name || "system",
        message: lData.message || "",
        metadata: lData.metadata,
        received_at: lData.received_at || envelope.timestamp,
      });
      break;
    }

    case "ticker": {
      const tData = data as any;
      if (tData.symbol) {
        useTickerStore.getState().updateTicker({
          symbol: tData.symbol,
          bid: tData.bid,
          ask: tData.ask,
          last: tData.last,
        });
      }
      break;
    }

    case "pong":
      // Heartbeat roundtrip acknowledged
      break;

    case "error":
      console.warn("WebSocket error received:", data);
      break;

    default:
      break;
  }
}
