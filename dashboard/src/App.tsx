import React from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { env } from "./config/env";
import { WebSocketProvider } from "./state/ws/WebSocketProvider";
import { Layout } from "./components/Layout";
import { OverviewPage } from "./pages/OverviewPage";
import { PortfolioPage } from "./pages/PortfolioPage";
import { TradesPage } from "./pages/TradesPage";
import { OrdersPage } from "./pages/OrdersPage";
import { SignalsPage } from "./pages/SignalsPage";
import { StrategiesPage } from "./pages/StrategiesPage";
import { RiskPage } from "./pages/RiskPage";
import { ExchangesPage } from "./pages/ExchangesPage";
import { LogsPage } from "./pages/LogsPage";
import { BacktestPage } from "./pages/BacktestPage";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: env.VITE_QUERY_STALE_MS,
      retry: 1, // non-configurable: single retry for failed REST reads
      refetchOnWindowFocus: false,
    },
  },
});

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <WebSocketProvider>
        <BrowserRouter>
          <Layout>
            <Routes>
              <Route path="/" element={<OverviewPage />} />
              <Route path="/portfolio" element={<PortfolioPage />} />
              <Route path="/trades" element={<TradesPage />} />
              <Route path="/orders" element={<OrdersPage />} />
              <Route path="/signals" element={<SignalsPage />} />
              <Route path="/strategies" element={<StrategiesPage />} />
              <Route path="/risk" element={<RiskPage />} />
              <Route path="/exchanges" element={<ExchangesPage />} />
              <Route path="/logs" element={<LogsPage />} />
              <Route path="/backtest" element={<BacktestPage />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </Layout>
        </BrowserRouter>
      </WebSocketProvider>
    </QueryClientProvider>
  );
}

export default App;
