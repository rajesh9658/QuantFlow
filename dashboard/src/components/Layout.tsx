import React, { useState } from "react";
import { Link, useLocation } from "react-router-dom";
import {
  LayoutDashboard,
  PieChart,
  ArrowLeftRight,
  ListOrdered,
  Radio,
  Cpu,
  ShieldAlert,
  Globe,
  Terminal,
  LineChart,
  Zap,
  Menu,
  X,
  AlertTriangle,
  Wifi,
  WifiOff,
} from "lucide-react";
import { useWebSocket } from "../state/ws/useWebSocket";
import { useRiskStore } from "../state/riskStore";
import { useUIStore } from "../state/uiStore";
import { EmergencyStopModal } from "./EmergencyStopModal";

interface LayoutProps {
  children: React.ReactNode;
}

const NAV_ITEMS = [
  { path: "/", label: "Overview", icon: LayoutDashboard },
  { path: "/portfolio", label: "Portfolio", icon: PieChart },
  { path: "/trades", label: "Trades", icon: ArrowLeftRight },
  { path: "/orders", label: "Orders", icon: ListOrdered },
  { path: "/signals", label: "Signals", icon: Radio },
  { path: "/strategies", label: "Strategies", icon: Cpu },
  { path: "/risk", label: "Risk & Limits", icon: ShieldAlert },
  { path: "/exchanges", label: "Exchanges", icon: Globe },
  { path: "/logs", label: "Live Logs", icon: Terminal },
  { path: "/backtest", label: "Backtest", icon: LineChart },
];

export function Layout({ children }: LayoutProps) {
  const location = useLocation();
  const { status, isStale, isDisconnected } = useWebSocket();
  const emergencyStop = useRiskStore((s) => s.status.emergency_stop);
  const { sidebarOpen, toggleSidebar } = useUIStore();
  const [showEmergencyModal, setShowEmergencyModal] = useState(false);

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col font-sans">
      {/* Stale / Disconnected Banner per Spec B7 */}
      {isDisconnected ? (
        <div className="bg-rose-600 text-white text-xs font-semibold py-1.5 px-4 text-center flex items-center justify-center space-x-2 animate-pulse">
          <WifiOff className="h-4 w-4" />
          <span>Disconnected from QuantFlow Engine — Attempting automated reconnect...</span>
        </div>
      ) : isStale ? (
        <div className="bg-amber-600 text-white text-xs font-semibold py-1.5 px-4 text-center flex items-center justify-center space-x-2">
          <AlertTriangle className="h-4 w-4" />
          <span>Warning: WebSocket data stream stale (&gt;10s without telemetry heartbeat)</span>
        </div>
      ) : null}

      {/* Top Navbar */}
      <header className="sticky top-0 z-40 border-b border-slate-800 bg-slate-950/90 backdrop-blur-md px-4 sm:px-6 py-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center space-x-4">
            <button
              type="button"
              onClick={toggleSidebar}
              className="p-1.5 rounded-lg bg-slate-900 border border-slate-800 text-slate-400 hover:text-white lg:hidden"
            >
              {sidebarOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
            </button>

            <Link to="/" className="flex items-center space-x-3">
              <div className="w-8 h-8 rounded-lg bg-emerald-500/20 border border-emerald-500/40 flex items-center justify-center">
                <Zap className="w-4 h-4 text-emerald-400" />
              </div>
              <div className="flex items-center space-x-2">
                <span className="font-bold text-base tracking-wider text-slate-100 font-mono">
                  QUANT<span className="text-emerald-400">FLOW</span>
                </span>
                <span className="hidden sm:inline-block text-[10px] uppercase font-mono px-1.5 py-0.5 rounded bg-slate-800 text-slate-400 border border-slate-700">
                  PROD DESK
                </span>
              </div>
            </Link>
          </div>

          <div className="flex items-center space-x-3 sm:space-x-4">
            {/* Connection Status Pill */}
            <div className="flex items-center space-x-2 bg-slate-900 px-3 py-1.5 rounded-full border border-slate-800 text-xs font-mono">
              {status === "connected" ? (
                <>
                  <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
                  <span className="text-emerald-400 hidden sm:inline">WS LIVE</span>
                </>
              ) : status === "connecting" || status === "reconnecting" ? (
                <>
                  <span className="w-2 h-2 rounded-full bg-amber-400 animate-ping" />
                  <span className="text-amber-400 hidden sm:inline">RECONNECTING</span>
                </>
              ) : (
                <>
                  <span className="w-2 h-2 rounded-full bg-rose-500" />
                  <span className="text-rose-400 hidden sm:inline">OFFLINE</span>
                </>
              )}
            </div>

            {/* Emergency Stop Button */}
            <button
              type="button"
              onClick={() => setShowEmergencyModal(true)}
              className={`px-3 py-1.5 rounded-lg text-xs font-mono font-bold uppercase transition flex items-center space-x-1.5 shadow-sm ${
                emergencyStop
                  ? "bg-rose-600 text-white animate-pulse border border-rose-400 shadow-rose-900/50"
                  : "bg-rose-950/70 hover:bg-rose-900 text-rose-300 border border-rose-800/80"
              }`}
            >
              <AlertTriangle className="h-3.5 w-3.5 text-rose-400" />
              <span>{emergencyStop ? "HALTED" : "EMERGENCY STOP"}</span>
            </button>
          </div>
        </div>
      </header>

      {/* Main Body with Sidebar */}
      <div className="flex flex-1 overflow-hidden">
        {/* Sidebar */}
        <aside
          className={`fixed inset-y-0 left-0 z-30 pt-16 w-64 bg-slate-950 border-r border-slate-800/80 flex flex-col transition-transform duration-200 lg:static lg:pt-0 ${
            sidebarOpen ? "translate-x-0" : "-translate-x-full lg:translate-x-0"
          }`}
        >
          <div className="p-4 space-y-1 overflow-y-auto flex-1">
            <div className="text-[10px] font-mono uppercase text-slate-500 px-3 py-2">
              Trading Desks & Analytics
            </div>
            {NAV_ITEMS.map((item) => {
              const Icon = item.icon;
              const isActive = location.pathname === item.path;
              return (
                <Link
                  key={item.path}
                  to={item.path}
                  className={`flex items-center space-x-3 px-3 py-2.5 rounded-lg text-xs font-mono transition ${
                    isActive
                      ? "bg-emerald-500/15 text-emerald-400 border border-emerald-500/30 font-semibold"
                      : "text-slate-400 hover:text-slate-100 hover:bg-slate-900"
                  }`}
                >
                  <Icon className={`h-4 w-4 ${isActive ? "text-emerald-400" : "text-slate-500"}`} />
                  <span>{item.label}</span>
                </Link>
              );
            })}
          </div>

          <div className="p-4 border-t border-slate-900 text-[11px] font-mono text-slate-600">
            <div>QuantFlow v0.1.0</div>
            <div>Institutional Event Core</div>
          </div>
        </aside>

        {/* Content Area */}
        <main className="flex-1 overflow-y-auto p-4 sm:p-6 bg-slate-950/40">
          <div className="max-w-7xl mx-auto">{children}</div>
        </main>
      </div>

      <EmergencyStopModal
        isOpen={showEmergencyModal}
        onClose={() => setShowEmergencyModal(false)}
      />
    </div>
  );
}
