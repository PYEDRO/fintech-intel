const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function fetcher<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Request failed");
  }
  return res.json() as Promise<T>;
}

// ── Types ─────────────────────────────────────────────────────────────────────

export interface MonthlyEvolution {
  mes: string;
  receita: number;
  count: number;
}

export interface ClientMetric {
  cliente: string;
  receita: number;
  count: number;
}

export interface CategoryMetric {
  categoria: string;
  receita: number;
  count: number;
}

export interface Projection {
  mes: string;
  receita_projetada: number;
}

export interface Metrics {
  receita_total: number;
  ticket_medio: number;
  taxa_inadimplencia: number;
  total_transacoes: number;
  transacoes_pagas: number;
  transacoes_pendentes: number;
  transacoes_atrasadas: number;
  evolucao_mensal: MonthlyEvolution[];
  por_cliente: ClientMetric[];
  por_categoria: CategoryMetric[];
  por_status: Record<string, number>;
  projecao_fluxo?: Projection[];
}

export interface Transaction {
  id: string;
  valor: number;
  data: string;
  status: string;
  cliente: string;
  descricao: string;
  categoria: string | null;
}

export interface TransactionList {
  items: Transaction[];
  total: number;
  page: number;
  pages: number;
}

export interface Insight {
  titulo: string;
  descricao: string;
  tipo: "oportunidade" | "risco" | "tendencia";
  severidade: "alta" | "media" | "baixa";
}

export interface Anomaly {
  transacao_id: string;
  motivo: string;
  score: number;
}

export interface ClientScore {
  cliente: string;
  score: number;
  risco: "alto" | "medio" | "baixo";
  motivo: string;
}

export interface InsightsData {
  insights: Insight[];
  anomalias: Anomaly[];
  score_clientes: ClientScore[];
}

export interface ChatSource {
  id: string;
  descricao: string;
  relevance: number;
}

export interface ChatResponse {
  answer: string;
  sources: ChatSource[];
}

export interface UploadResponse {
  total_rows: number;
  classified: number;
  indexed: number;
  metrics_summary: Record<string, unknown>;
}

// ── API calls ─────────────────────────────────────────────────────────────────

export const api = {
  getMetrics: (params?: { start_date?: string; end_date?: string; cliente?: string }) => {
    const qs = new URLSearchParams(
      Object.entries(params ?? {}).filter(([, v]) => v != null) as [string, string][]
    ).toString();
    return fetcher<Metrics>(`/api/metrics${qs ? `?${qs}` : ""}`);
  },

  getTransactions: (params: {
    page?: number;
    per_page?: number;
    status?: string;
    cliente?: string;
    search?: string;
    start_date?: string;
    end_date?: string;
    sort_by?: string;
    sort_order?: "asc" | "desc";
  }) => {
    const qs = new URLSearchParams(
      Object.entries(params).filter(([, v]) => v != null && v !== "") as [string, string][]
    ).toString();
    return fetcher<TransactionList>(`/api/transactions?${qs}`);
  },

  getInsights: () => fetcher<InsightsData>("/api/insights"),

  chat: (question: string) =>
    fetcher<ChatResponse>("/api/chat", {
      method: "POST",
      body: JSON.stringify({ question }),
    }),

  upload: async (file: File): Promise<UploadResponse> => {
    const form = new FormData();
    form.append("file", file);
    const res = await fetch(`${BASE_URL}/api/upload`, { method: "POST", body: form });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail ?? "Upload failed");
    }
    return res.json();
  },
};
