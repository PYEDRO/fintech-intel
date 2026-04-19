<<<<<<< HEAD
from pydantic import BaseModel, Field
from typing import Optional, List, Literal, Any
from datetime import date
=======
from typing import List, Literal, Optional
>>>>>>> 2eb76bd40a96b88b53abc41d623cae6580f1e188

from pydantic import BaseModel, Field

# ─── Upload (síncrono — mantido para compatibilidade com testes) ──────────────

class UploadResponse(BaseModel):
    total_rows: int
    classified: int
    indexed: int
    metrics_summary: dict


# ─── Upload Assíncrono (BackgroundTasks) ──────────────────────────────────────

class UploadJobResponse(BaseModel):
    """Retornado imediatamente ao aceitar o arquivo para processamento."""
    job_id: str
    status: Literal["queued"]
    message: str


class UploadStatusResponse(BaseModel):
    """Estado atual do job de processamento, retornado pelo endpoint de polling."""
    job_id: str
    status: Literal["queued", "processing", "done", "error"]
    progress: int = Field(ge=0, le=100, description="Percentual de progresso (0-100)")
    step: str = Field(description="Descrição da etapa atual")
    result: Optional[dict] = None   # Preenchido quando status='done'
    error: Optional[str] = None     # Preenchido quando status='error'
    created_at: str


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


class ProjectionPoint(BaseModel):
    mes: str
    receita_projetada: float


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
    projecao_fluxo: Optional[List[ProjectionPoint]] = None


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
