# FinTech Intel — AI-Powered Financial Intelligence Platform

Plataforma fullstack para análise inteligente de transações financeiras, combinando pipelines de dados com LLM (Gemma 4) e busca semântica (RAG + FAISS).

---

## 1. Visão Geral e Decisões Técnicas

| Camada | Tecnologia | Motivação |
|---|---|---|
| Backend API | FastAPI + Python 3.11 | async nativo, tipagem forte, OpenAPI automático |
| Banco de dados | SQLite + WAL mode | zero-config, portável, suficiente para ~100k txn |
| Embeddings | sentence-transformers `all-MiniLM-L6-v2` | modelo compacto (384d), excelente custo-benefício semântico |
| Vector store | FAISS `IndexFlatIP` | cosine similarity via inner product com normalização L2 |
| LLM | Gemma 4 (`Gemma 4-chat`) | custo muito baixo vs GPT-4, compatível com SDK OpenAI |
| Frontend | Next.js 14 App Router + TypeScript | SSR, routing nativo, ecosistema maduro |
| Charts | Recharts | declarativo, integrado ao React sem overhead |
| Infra | Docker Compose | reprodutibilidade, isolamento, zero-dependency |

**Diferenciais implementados:**
- **Client Risk Score** — heurística (inadimplência + ticket médio + frequência) → input para churn prediction
- **Classificação inteligente de transações** — LLM categoriza descrições em texto livre em categorias estruturadas de negócio
- **Detecção de anomalias** — Z-score por cliente + P75 de atrasados, contextualizado pelo LLM
- **RAG com citação de fontes** — cada resposta do chat cita os IDs das transações consultadas
- **Projeção de fluxo de caixa** — regressão linear nos últimos 6 meses → 3 meses projetados

---

## 2. Arquitetura

```
┌─────────────────────────────────────────────────────────────┐
│                        Docker Compose                       │
│  ┌────────────────────┐       ┌──────────────────────────┐  │
│  │  Frontend (3000)   │──────▶│   Backend (8000)          │  │
│  │  Next.js 14        │       │   FastAPI                 │  │
│  │  TypeScript        │       │   ├── /api/upload         │  │
│  │  Recharts          │       │   ├── /api/metrics        │  │
│  │  Tailwind CSS      │       │   ├── /api/transactions   │  │
│  └────────────────────┘       │   ├── /api/insights       │  │
│                               │   └── /api/chat           │  │
│                               │                           │  │
│                               │   Services:               │  │
│                               │   ├── ingestion.py        │  │
│                               │   ├── metrics_engine.py   │  │
│                               │   ├── classifier.py       │  │
│                               │   ├── rag.py              │  │
│                               │   ├── insights_gen.py     │  │
│                               │   └── anomaly.py          │  │
│                               └──────────┬───────────────┘  │
│                                          │                   │
│                          ┌───────────────▼──────────────┐   │
│                          │  data/ (volume montado)        │   │
│                          │  ├── fintech.db (SQLite)       │   │
│                          │  ├── faiss.index               │   │
│                          │  └── faiss_meta.json           │   │
│                          └──────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘

Ingestion Pipeline:
XLSX/CSV ──▶ Pandas ──▶ SQLite ──▶ Gemma 4 Classifier ──▶ FAISS Index
                                       (batches of 20)     (sentence-transformers)
```

---

## 3. Como Executar

### Pré-requisitos
- Docker + Docker Compose v2+
- Chave de API Gemma 4 (para features de LLM)

### Setup

```bash
# 1. Clone o repositório
git clone <repo-url>
cd fintech-intel

# 2. Configure as variáveis de ambiente
cp .env.example .env
# Edite .env e adicione sua Gemma 4_API_KEY

# 3. Suba os serviços
docker-compose up --build

# Frontend: http://localhost:3000
# Backend API: http://localhost:8000
# Swagger UI: http://localhost:8000/docs
```

### Desenvolvimento local (sem Docker)

```bash
# Backend
cd backend
pip install -r requirements.txt
python generate_sample_data.py   # gera dados de exemplo
uvicorn app.main:app --reload

# Frontend (outro terminal)
cd frontend
npm install
npm run dev
```

---

## 4. Variáveis de Ambiente

| Variável | Obrigatório | Descrição |
|---|---|---|
| `Gemma 4_API_KEY` | Sim | Chave da API Gemma 4 |
| `Gemma 4_BASE_URL` | Não | Default: `https://api.Gemma 4.com` |
| `Gemma 4_MODEL` | Não | Default: `Gemma 4-chat` |
| `DB_PATH` | Não | Path do SQLite. Default: `data/fintech.db` |
| `FAISS_INDEX_PATH` | Não | Default: `data/faiss.index` |
| `RAG_TOP_K` | Não | Top-K retrieval. Default: `10` |
| `CLASSIFIER_BATCH_SIZE` | Não | Default: `20` |

> **Nota:** sem `Gemma 4_API_KEY`, o sistema funciona em modo degradado — métricas e tabelas funcionam normalmente, mas classificação LLM, insights e RAG retornam resultados estáticos/fallback.

---

## 5. API Endpoints

| Método | Rota | Descrição |
|---|---|---|
| `POST` | `/api/upload` | Upload XLSX/CSV → pipeline completo |
| `GET` | `/api/metrics` | KPIs agregados com filtros opcionais |
| `GET` | `/api/transactions` | Listagem paginada com filtros e ordenação |
| `GET` | `/api/insights` | Insights IA + anomalias + client scores |
| `POST` | `/api/chat` | Chat RAG com citação de transações |
| `GET` | `/health` | Health check do serviço |

Documentação completa: `http://localhost:8000/docs` (Swagger UI automático)

---

## 6. Estrutura de Dados

O arquivo de upload deve conter as seguintes colunas:

| Coluna | Tipo | Exemplo |
|---|---|---|
| `id` | string | `txn_00001` |
| `valor` | float | `1500.00` |
| `data` | date | `2024-03-15` |
| `status` | string | `pago` / `pendente` / `atrasado` |
| `cliente` | string | `Empresa A` |
| `descricao` | string | `Assinatura plataforma educacional` |

Para gerar dados de exemplo:
```bash
cd backend && python generate_sample_data.py
# Gera: data/transacoes_sample.xlsx (1000 transações)
```

---

## 7. Testes

```bash
cd backend
pip install -r requirements.txt
pytest --cov=app --cov-report=term-missing
```

Cobertura mínima: 70% (configurada no `pytest.ini`)

Suítes:
- `test_ingestion.py` — parsing XLSX/CSV, limpeza, persistência
- `test_metrics.py` — cálculo correto de KPIs, filtros por data/cliente
- `test_rag.py` — indexação FAISS, retrieval semântico, pipeline RAG

---

## 8. Trade-offs e Próximos Passos

**Escolhas com trade-offs conscientes:**

- **SQLite vs PostgreSQL** — Para o scope deste case, SQLite é suficiente e elimina infraestrutura extra. Com >500k transações ou multi-usuário concorrente, migrar para PostgreSQL.
- **FAISS IndexFlatIP vs IVF** — FlatIP é exato (brute-force) e correto para ~100k vetores. Para escala maior, usar `IndexIVFFlat` com treinamento.
- **Embedding on-the-fly vs pre-computed** — Modelo carregado em memória no startup. Em produção, usar um serviço de embedding dedicado (e.g. Azure OpenAI Embeddings).
- **Gemma 4 sync classification** — Batches processados sequencialmente. Com volume alto, paralelizar com `asyncio.gather` e rate limiting.

**O que faria diferente com mais tempo:**

1. **Auth layer** — JWT + RBAC para multi-tenant (crítico para SaaS edtech)
4. **Cache de métricas** — Redis com TTL curto para evitar recalcular aggregations a cada request
6. **Observabilidade** — OpenTelemetry + Prometheus/Grafana para métricas de latência e throughput
7. **Migrations** — Alembic para versionamento de schema SQLite/PostgreSQL


