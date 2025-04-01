"use client";
import { useEffect, useState } from "react";
import { api, type Metrics, type InsightsData } from "@/lib/api";
import KPICards from "@/components/KPICards";
import RevenueChart from "@/components/RevenueChart";
import StatusPieChart from "@/components/StatusPieChart";
import ClientBarChart from "@/components/ClientBarChart";
import CategoryBreakdown from "@/components/CategoryBreakdown";
import InsightsPanel from "@/components/InsightsPanel";
import AnomalyAlerts from "@/components/AnomalyAlerts";
import TransactionTable from "@/components/TransactionTable";
import { RefreshCw } from "lucide-react";

export default function DashboardPage() {
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [insights, setInsights] = useState<InsightsData | null>(null);
  const [metricsLoading, setMetricsLoading] = useState(true);
  const [insightsLoading, setInsightsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadMetrics = async () => {
    setMetricsLoading(true);
    try {
      const data = await api.getMetrics();
      setMetrics(data);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Erro ao carregar métricas");
    } finally {
      setMetricsLoading(false);
    }
  };

  const loadInsights = async () => {
    setInsightsLoading(true);
    try {
      const data = await api.getInsights();
      setInsights(data);
    } catch {
      // Insights are optional — don't block dashboard
    } finally {
      setInsightsLoading(false);
    }
  };

  useEffect(() => {
    loadMetrics();
    loadInsights();
  }, []);

  return (
    <div className="p-6 max-w-[1400px] mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Dashboard Financeiro</h1>
          <p className="text-sm text-gray-500 mt-1">Visão geral das transações e KPIs</p>
        </div>
        <button
          onClick={() => { loadMetrics(); loadInsights(); }}
          className="flex items-center gap-2 text-sm text-gray-600 hover:text-gray-900 border border-gray-200 rounded-lg px-3 py-1.5 hover:bg-gray-50 transition-colors"
        >
          <RefreshCw className="w-3.5 h-3.5" />
          Atualizar
        </button>
      </div>

      {error && (
        <div className="mb-4 p-4 bg-amber-50 border border-amber-200 rounded-lg text-sm text-amber-700">
          ⚠️ {error} — Faça upload de dados para começar.
        </div>
      )}

      {/* Row 1: KPI Cards */}
      <KPICards metrics={metrics} loading={metricsLoading} />

      {/* Row 2: Revenue Chart + Pie */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mt-4">
        <div className="lg:col-span-2">
          <RevenueChart
            data={metrics?.evolucao_mensal ?? []}
            projection={metrics?.projecao_fluxo}
          />
        </div>
        <StatusPieChart data={metrics?.por_status ?? {}} />
      </div>

      {/* Row 3: Bar Chart + Category */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mt-4">
        <ClientBarChart data={metrics?.por_cliente ?? []} />
        <CategoryBreakdown data={metrics?.por_categoria ?? []} />
      </div>

      {/* Row 4: Insights + Anomalies */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mt-4">
        <InsightsPanel insights={insights?.insights ?? []} loading={insightsLoading} />
        <AnomalyAlerts anomalias={insights?.anomalias ?? []} />
      </div>

      {/* Row 5: Transaction Table */}
      <div className="mt-4">
        <TransactionTable />
      </div>
    </div>
  );
}
