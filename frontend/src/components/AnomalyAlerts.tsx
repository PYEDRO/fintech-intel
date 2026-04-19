"use client";
import { ShieldAlert } from "lucide-react";
import type { Anomaly } from "@/lib/api";

interface Props {
  anomalias: Anomaly[];
}

function scoreColor(score: number) {
  if (score >= 0.8) return "bg-red-100 text-red-700 border-red-200";
  if (score >= 0.5) return "bg-amber-50 text-amber-700 border-amber-200";
  return "bg-yellow-50 text-yellow-700 border-yellow-200";
}

export default function AnomalyAlerts({ anomalias }: Props) {
  if (!anomalias.length) {
    return (
      <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-5">
        <h3 className="font-semibold text-gray-800 mb-2">Anomalias Detectadas</h3>
        <p className="text-sm text-gray-400">Nenhuma anomalia identificada.</p>
      </div>
    );
  }

  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-5">
      <div className="flex items-center gap-2 mb-4">
        <ShieldAlert className="w-4 h-4 text-amber-500" />
        <h3 className="font-semibold text-gray-800">Anomalias Detectadas</h3>
        <span className="ml-auto text-xs bg-amber-100 text-amber-700 px-2 py-0.5 rounded-full font-medium">
          {anomalias.length}
        </span>
      </div>
      <div className="space-y-2 max-h-64 overflow-y-auto">
        {anomalias.map((a) => (
          <div key={a.transacao_id} className={`border rounded-lg px-4 py-3 ${scoreColor(a.score)}`}>
            <div className="flex justify-between items-center gap-2">
              <span className="font-mono text-xs font-medium">{a.transacao_id}</span>
              <span className="text-xs font-medium">Score: {(a.score * 100).toFixed(0)}%</span>
            </div>
            <p className="text-xs mt-1 leading-relaxed">{a.motivo}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
