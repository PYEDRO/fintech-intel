"use client";
import { DollarSign, CreditCard, AlertTriangle, Activity } from "lucide-react";
import type { Metrics } from "@/lib/api";

function fmt(value: number) {
  return new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" }).format(value);
}

interface Props {
  metrics: Metrics | null;
  loading?: boolean;
}

const CARDS = [
  {
    key: "receita_total" as const,
    label: "Receita Total",
    icon: DollarSign,
    color: "bg-blue-500",
    format: fmt,
  },
  {
    key: "ticket_medio" as const,
    label: "Ticket Médio",
    icon: CreditCard,
    color: "bg-emerald-500",
    format: fmt,
  },
  {
    key: "taxa_inadimplencia" as const,
    label: "Taxa de Inadimplência",
    icon: AlertTriangle,
    color: "bg-amber-500",
    format: (v: number) => `${v.toFixed(1)}%`,
  },
  {
    key: "total_transacoes" as const,
    label: "Total de Transações",
    icon: Activity,
    color: "bg-violet-500",
    format: (v: number) => v.toLocaleString("pt-BR"),
  },
];

export default function KPICards({ metrics, loading }: Props) {
  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
      {CARDS.map(({ key, label, icon: Icon, color, format }) => (
        <div key={key} className="bg-white rounded-xl shadow-sm border border-gray-100 p-5">
          <div className="flex items-start justify-between">
            <div>
              <p className="text-xs font-medium text-gray-500 uppercase tracking-wide">{label}</p>
              {loading ? (
                <div className="mt-2 h-7 w-28 bg-gray-100 rounded animate-pulse" />
              ) : (
                <p className="mt-1 text-2xl font-bold text-gray-900">
                  {metrics ? format(metrics[key] as number) : "—"}
                </p>
              )}
            </div>
            <div className={`${color} p-2.5 rounded-lg`}>
              <Icon className="w-5 h-5 text-white" />
            </div>
          </div>
          {/* Sub-info */}
          {!loading && metrics && key === "total_transacoes" && (
            <p className="mt-2 text-xs text-gray-400">
              {metrics.transacoes_pagas} pagas · {metrics.transacoes_pendentes} pendentes · {metrics.transacoes_atrasadas} atrasadas
            </p>
          )}
        </div>
      ))}
    </div>
  );
}
