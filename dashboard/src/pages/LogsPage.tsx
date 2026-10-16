import React, { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Terminal, Pause, Play, Download, Trash2, Search } from "lucide-react";
import { apiClient } from "../api/client";
import { endpoints } from "../config/endpoints";
import { useLogStore } from "../state/logStore";
import { LogEntry } from "../types/dashboard";

export function LogsPage() {
  const wsLogs = useLogStore((s) => s.logs);
  const paused = useLogStore((s) => s.paused);
  const togglePause = useLogStore((s) => s.togglePause);
  const clearLogs = useLogStore((s) => s.clear);

  const [levelFilter, setLevelFilter] = useState<string>("");
  const [search, setSearch] = useState<string>("");

  // REST initial logs
  const { data: initialLogs = [] } = useQuery<LogEntry[]>({
    queryKey: ["logs", "initial"],
    queryFn: () => apiClient(endpoints.logs({ limit: 100 })),
    enabled: wsLogs.length === 0,
  });

  const allLogs = useMemo(() => {
    const combined = wsLogs.length > 0 ? wsLogs : initialLogs;
    return combined.filter((log) => {
      const matchesLevel = !levelFilter || log.level.toUpperCase() === levelFilter.toUpperCase();
      const matchesSearch =
        !search ||
        log.message.toLowerCase().includes(search.toLowerCase()) ||
        log.correlation_id.toLowerCase().includes(search.toLowerCase()) ||
        log.logger_name.toLowerCase().includes(search.toLowerCase());
      return matchesLevel && matchesSearch;
    });
  }, [wsLogs, initialLogs, levelFilter, search]);

  const handleDownload = () => {
    if (allLogs.length === 0) return;
    const blob = new Blob([JSON.stringify(allLogs, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `quantflow_logs_${new Date().toISOString()}.json`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  const getLevelColor = (level: string) => {
    switch (level.toUpperCase()) {
      case "ERROR":
        return "text-rose-400 bg-rose-500/10 border-rose-500/30";
      case "WARNING":
      case "WARN":
        return "text-amber-400 bg-amber-500/10 border-amber-500/30";
      case "INFO":
        return "text-emerald-400 bg-emerald-500/10 border-emerald-500/30";
      case "DEBUG":
        return "text-cyan-400 bg-cyan-500/10 border-cyan-500/30";
      default:
        return "text-slate-400 bg-slate-800 border-slate-700";
    }
  };

  return (
    <div className="space-y-6">
      {/* Controls Bar */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 p-4 rounded-xl bg-slate-900 border border-slate-800">
        <div className="flex flex-wrap items-center gap-3">
          <select
            value={levelFilter}
            onChange={(e) => setLevelFilter(e.target.value)}
            className="px-3 py-1.5 bg-slate-950 border border-slate-800 rounded-lg text-xs font-mono text-slate-200 focus:outline-none focus:border-emerald-500"
          >
            <option value="">All Levels</option>
            <option value="INFO">INFO</option>
            <option value="WARNING">WARNING</option>
            <option value="ERROR">ERROR</option>
            <option value="DEBUG">DEBUG</option>
          </select>

          <div className="relative w-64">
            <Search className="absolute left-3 top-2.5 h-3.5 w-3.5 text-slate-500" />
            <input
              type="text"
              placeholder="Search message, correlation ID..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-full pl-8 pr-3 py-1.5 bg-slate-950 border border-slate-800 rounded-lg text-xs font-mono text-slate-200 placeholder-slate-500 focus:outline-none focus:border-emerald-500"
            />
          </div>
        </div>

        <div className="flex items-center space-x-2">
          <button
            type="button"
            onClick={togglePause}
            className={`px-3 py-1.5 rounded-lg text-xs font-mono font-semibold flex items-center space-x-1.5 transition ${
              paused
                ? "bg-amber-500/20 text-amber-400 border border-amber-500/40"
                : "bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700"
            }`}
          >
            {paused ? <Play className="h-3.5 w-3.5" /> : <Pause className="h-3.5 w-3.5" />}
            <span>{paused ? "Resume Tail" : "Pause Tail"}</span>
          </button>

          <button
            type="button"
            onClick={handleDownload}
            disabled={allLogs.length === 0}
            className="p-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 disabled:opacity-40 transition"
            title="Download Logs"
          >
            <Download className="h-4 w-4" />
          </button>

          <button
            type="button"
            onClick={clearLogs}
            className="p-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 transition"
            title="Clear Buffer"
          >
            <Trash2 className="h-4 w-4" />
          </button>
        </div>
      </div>

      {/* Log Output Stream */}
      <div className="p-4 rounded-xl bg-slate-950 border border-slate-800 font-mono text-xs overflow-hidden flex flex-col h-[600px]">
        <div className="flex items-center justify-between pb-3 mb-2 border-b border-slate-800/80 text-slate-500 text-[11px]">
          <div className="flex items-center space-x-2">
            <Terminal className="h-4 w-4 text-emerald-400" />
            <span>STREAM LOGS ({allLogs.length} buffered)</span>
          </div>
          <div>{paused ? "TAIL PAUSED" : "LIVE TAIL STREAMING"}</div>
        </div>

        <div className="flex-1 overflow-y-auto space-y-1.5 pr-2">
          {allLogs.length > 0 ? (
            allLogs.map((log, i) => (
              <div
                key={`${log.correlation_id}-${i}`}
                className="p-2 rounded bg-slate-900/40 hover:bg-slate-900 border border-slate-800/40 flex items-start space-x-3 text-[11px] leading-relaxed transition"
              >
                <span className="text-slate-500 shrink-0 select-none">
                  {log.received_at ? new Date(log.received_at).toLocaleTimeString() : "--:--:--"}
                </span>

                <span className={`px-1.5 py-0.2 rounded border uppercase font-bold shrink-0 ${getLevelColor(log.level)}`}>
                  {log.level}
                </span>

                <span className="text-slate-400 font-semibold shrink-0">
                  [{log.logger_name}]
                </span>

                <span className="text-slate-200 flex-1 break-all">
                  {log.message}
                </span>

                <span className="text-slate-600 shrink-0 select-all text-[10px]">
                  {log.correlation_id.slice(0, 8)}
                </span>
              </div>
            ))
          ) : (
            <div className="h-full flex items-center justify-center text-slate-600">
              No logs received matching filter
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
