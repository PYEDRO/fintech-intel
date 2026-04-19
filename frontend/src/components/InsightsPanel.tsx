"use client";
import { TrendingUp, AlertTriangle, Lightbulb } from "lucide-react";
import type { Insight } from "@/lib/api";

const TYPE_CONFIG = {
  oportunidade: { icon: Lightbulb, bg: "bg-emerald-50", border: "border-emerald-200", text: "text-emerald-700", badge: "bg-emerald-100 text-emerald-700" },
  risco: { icon: AlertTriangle, bg: "bg-red-50", border: "border-red-200", text: "text-red-700", badge: "bg-red-100 text-red-700" },
  tendencia: { icon: TrendingUp, bg: "bg-blue-50", border: "border-blue-200", text: "text-blue-700", badge: "bg-blue-100 text-blue-700" },
};

const SEVERITY_LABEL: Record<string, string> = {
  alta: "Alto",
  media: "Médio",
  baixa: "Baixo",
};

interface Props {
  insights: Insight[];
  loading?: boolean;
}

export default function InsightsPanel({ insights, loading }: Props) {
  if (loading) {
    return (
      <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-5">
        <h3 className="font-semibold text-gray-800 mb-4">Insights IA</h3>
        <div className="space-y-3">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-20 bg-gray-100 rounded-lg animate-pulse" />
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-5">
      <h3 className="font-semibold text-gray-800 mb-4">Insights IA</h3>
      {!insights.length && (
        <p className="text-sm text-gray-400">Faça upload de dados para gerar insights.</p>
      )}
      <div className="space-y-3">
        {insights.map((insight, idx) => {
          const cfg = TYPE_CONFIG[insight.tipo] ?? TYPE_CONFIG.tendencia;
          const Icon = cfg.icon;
          return (
            <div key={idx} className={`${cfg.bg} ${cfg.border} border rounded-lg p-4`}>
              <div className="flex items-start gap-3">
                <Icon className={`w-4 h-4 mt-0.5 flex-shrink-0 ${cfg.text}`} />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap mb-1">
                    <span className={`font-semibold text-sm ${cfg.text}`}>{insight.titulo}</span>
                    <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${cfg.badge}`}>
                      {SEVERITY_LABEL[insight.severidade] ?? insight.severidade}
                    </span>
                  </div>
                  <p className="text-xs text-gray-600 leading-relaxed">{insight.descricao}</p>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
