import React, { useState } from "react";
import { AlertTriangle, X } from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "../api/client";
import { endpoints } from "../config/endpoints";
import { useRiskStore } from "../state/riskStore";

interface EmergencyStopModalProps {
  isOpen: boolean;
  onClose: () => void;
}

const CONFIRMATION_PHRASE = "EMERGENCY STOP";

export function EmergencyStopModal({ isOpen, onClose }: EmergencyStopModalProps) {
  const queryClient = useQueryClient();
  const setEmergencyStop = useRiskStore((s) => s.setEmergencyStop);
  const [confirmText, setConfirmText] = useState("");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: async () => {
      return apiClient(endpoints.risk.emergencyStop(), {
        method: "POST",
        body: JSON.stringify({ enabled: true, trigger: "manual_dashboard" }),
      });
    },
    onSuccess: () => {
      setEmergencyStop(true);
      queryClient.invalidateQueries({ queryKey: ["risk"] });
      onClose();
      setConfirmText("");
    },
    onError: (err: Error) => {
      setErrorMessage(err.message || "Failed to trigger emergency stop");
    },
  });

  if (!isOpen) return null;

  const isConfirmed = confirmText.trim() === CONFIRMATION_PHRASE;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4">
      <div className="relative w-full max-w-md rounded-xl border border-rose-600/60 bg-slate-900 p-6 shadow-2xl shadow-rose-950/50">
        <button
          onClick={onClose}
          className="absolute right-4 top-4 text-slate-400 hover:text-white"
          type="button"
        >
          <X className="h-5 w-5" />
        </button>

        <div className="flex items-center space-x-3 text-rose-500 mb-4">
          <div className="p-2 rounded-lg bg-rose-500/20 border border-rose-500/30">
            <AlertTriangle className="h-6 w-6" />
          </div>
          <div>
            <h2 className="text-lg font-bold text-white tracking-wide">CONFIRM EMERGENCY STOP</h2>
            <p className="text-xs text-rose-400">Immediate circuit breaker activation</p>
          </div>
        </div>

        <p className="text-sm text-slate-300 mb-4 leading-relaxed">
          Activating the emergency stop will immediately halt all order submission,
          cancel open orders across active exchanges, and disable strategy execution.
        </p>

        <div className="mb-4">
          <label className="block text-xs font-mono text-slate-400 mb-1">
            Type <span className="text-rose-400 font-bold select-all font-mono">{CONFIRMATION_PHRASE}</span> to confirm:
          </label>
          <input
            type="text"
            value={confirmText}
            onChange={(e) => setConfirmText(e.target.value)}
            placeholder="Type EMERGENCY STOP"
            className="w-full px-3 py-2 bg-slate-950 border border-slate-700 rounded-lg text-slate-100 font-mono text-sm focus:outline-none focus:border-rose-500"
            autoFocus
          />
        </div>

        {errorMessage && (
          <div className="mb-4 p-2.5 rounded bg-rose-950/60 border border-rose-800 text-xs text-rose-300">
            {errorMessage}
          </div>
        )}

        <div className="flex space-x-3 justify-end">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 text-sm font-medium transition"
          >
            Cancel
          </button>
          <button
            type="button"
            disabled={!isConfirmed || mutation.isPending}
            onClick={() => mutation.mutate()}
            className={`px-4 py-2 rounded-lg text-sm font-bold tracking-wider transition ${
              isConfirmed && !mutation.isPending
                ? "bg-rose-600 hover:bg-rose-500 text-white cursor-pointer shadow-lg shadow-rose-600/30"
                : "bg-slate-800 text-slate-500 cursor-not-allowed border border-slate-700"
            }`}
          >
            {mutation.isPending ? "HALTING SYSTEM..." : "CONFIRM EMERGENCY STOP"}
          </button>
        </div>
      </div>
    </div>
  );
}
