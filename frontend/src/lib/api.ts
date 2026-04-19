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

// Upload assíncrono
export interface UploadJobResponse {
  job_id: string;
  status: "queued";
  message: string;
}

export interface UploadStatusData {
  job_id: string;
  status: "queued" | "processing" | "done" | "error";
  progress: number;
  step: string;
  result: Record<string, unknown> | null;
  error: string | null;
  created_at: string;
}

// Mantido para compatibilidade com testes / código legado
export interface UploadResponse {
  total_rows: number;
  classified: number;
  indexed: number;
  metrics_summary: Record<string, unknown>;
}

// Callbacks para streaming
export interface StreamCallbacks {
  onToken: (token: string) => void;
  onSources: (sources: ChatSource[]) => void;
  onDone: () => void;
  onError?: (message: string) => void;
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

  // ── Chat JSON (LangGraph, sem streaming) ─────────────────────────────────────
  chat: (question: string) =>
    fetcher<ChatResponse>("/api/chat", {
      method: "POST",
      body: JSON.stringify({ question }),
    }),

  // ── Chat Streaming (SSE via fetch + ReadableStream) ───────────────────────
  chatStream: async (question: string, callbacks: StreamCallbacks): Promise<void> => {
    const response = await fetch(`${BASE_URL}/api/chat/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    });

    if (!response.ok) {
      const err = await response.json().catch(() => ({ detail: response.statusText }));
      throw new Error(err.detail ?? "Stream request failed");
    }

    if (!response.body) {
      throw new Error("Resposta sem corpo — streaming não suportado.");
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      // SSE: eventos separados por \n\n
      const blocks = buffer.split("\n\n");
      buffer = blocks.pop() ?? ""; // Mantém bloco incompleto no buffer

      for (const block of blocks) {
        if (!block.trim()) continue;
        // Cada linha do bloco com "data: " prefixo
        const dataLine = block
          .split("\n")
          .find((l) => l.startsWith("data: "));
        if (!dataLine) continue;

        try {
          const payload = JSON.parse(dataLine.slice(6));
          switch (payload.type) {
            case "token":
              callbacks.onToken(payload.data as string);
              break;
            case "sources":
              callbacks.onSources(payload.data as ChatSource[]);
              break;
            case "done":
              callbacks.onDone();
              break;
            case "error":
              callbacks.onError?.(payload.data as string);
              callbacks.onDone();
              break;
          }
        } catch {
          // Ignora eventos malformados
        }
      }
    }
  },

  // ── Upload assíncrono ──────────────────────────────────────────────────────
  upload: async (file: File): Promise<UploadJobResponse> => {
    const form = new FormData();
    form.append("file", file);
    const res = await fetch(`${BASE_URL}/api/upload`, { method: "POST", body: form });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail ?? "Upload failed");
    }
    return res.json();
  },

  // ── Polling de status do job de upload ────────────────────────────────────
  getUploadStatus: (jobId: string) =>
    fetcher<UploadStatusData>(`/api/upload/status/${jobId}`),
};
