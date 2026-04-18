from pydantic import BaseModel, Field
from typing import Optional, List, Literal


# ─── Upload ───────────────────────────────────────────────────────────────────

class UploadResponse(BaseModel):
    total_rows: int
    classified: int
    indexed: int
    metrics_summary: dict


# ─── Transactions ─────────────────────────────────────────────────────────────

class Transaction(BaseModel):
    id: str
    valor: float
    data: str
    status: str
    cliente: str
    descricao: str
    categoria: Optional[str] = None


class TransactionListResponse(BaseModel):
    items: List[Transaction]
    total: int
    page: int
    pages: int


# ─── Metrics ──────────────────────────────────────────────────────────────────

class MonthlyEvolution(BaseModel):
    mes: str
    receita: float
    count: int


class ClientMetric(BaseModel):
    cliente: str
    receita: float
    count: int


class CategoryMetric(BaseModel):
    categoria: str
    receita: float
    count: int


class MetricsResponse(BaseModel):
    receita_total: float
    ticket_medio: float
    taxa_inadimplencia: float
    total_transacoes: int
    transacoes_pagas: int
    transacoes_pendentes: int
    transacoes_atrasadas: int
    evolucao_mensal: List[MonthlyEvolution]
    por_cliente: List[ClientMetric]
    por_categoria: List[CategoryMetric]
    por_status: dict


# ─── Insights ─────────────────────────────────────────────────────────────────

class Insight(BaseModel):
    titulo: str
    descricao: str
    tipo: Literal["oportunidade", "risco", "tendencia"]
    severidade: Literal["alta", "media", "baixa"]


class Anomaly(BaseModel):
    transacao_id: str
    motivo: str
    score: float


class ClientScore(BaseModel):
    cliente: str
    score: float
    risco: Literal["alto", "medio", "baixo"]
    motivo: str


class InsightsResponse(BaseModel):
    insights: List[Insight]
    anomalias: List[Anomaly]
    score_clientes: List[ClientScore]


# ─── Chat ─────────────────────────────────────────────────────────────────────

class ChatSource(BaseModel):
    id: str
    descricao: str
    relevance: float


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=500)


class ChatResponse(BaseModel):
    answer: str
    sources: List[ChatSource]
