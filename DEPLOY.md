# Deploy: GCP Cloud Run (Backend) + Vercel (Frontend)

## Visão Geral da Arquitetura

```
Browser → Vercel (Next.js) → GCP Cloud Run (FastAPI) → SQLite / FAISS
```

> **Nota sobre SQLite em produção:** O SQLite é adequado para MVPs e cargas de
> trabalho de leitura intensiva. Para produção com múltiplas instâncias, migre
> para Cloud SQL (PostgreSQL) ou Firestore. O FAISS index também deve ser
> movido para Cloud Storage. Veja a seção "Escalabilidade" no final.

---

## Pré-requisitos

```bash
# Instalar CLIs
brew install google-cloud-sdk        # macOS
# ou: https://cloud.google.com/sdk/docs/install (Linux/Windows)

npm install -g vercel                # Vercel CLI
```

---

## Parte 1: Backend no GCP Cloud Run

### 1.1 Configurar o projeto GCP

```bash
# Login e seleção de projeto
gcloud auth login
gcloud projects create fintech-intel-prod --name="FinTech Intel"
gcloud config set project fintech-intel-prod

# Habilitar APIs necessárias
gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com \
  cloudbuild.googleapis.com
```

### 1.2 Configurar o Secret Manager (chaves sensíveis)

```bash
# NUNCA coloque a API key em variável de ambiente plain text em produção.
# Use o Secret Manager do GCP.

echo -n "sk-sua-chave-deepseek-aqui" | \
  gcloud secrets create DEEPSEEK_API_KEY \
    --data-file=- \
    --replication-policy=automatic

# Verificar
gcloud secrets versions access latest --secret=DEEPSEEK_API_KEY
```

### 1.3 Criar o Artifact Registry (repositório de imagens Docker)

```bash
gcloud artifacts repositories create fintech-backend \
  --repository-format=docker \
  --location=us-central1 \
  --description="FinTech Intel backend images"

# Autenticar o Docker no Artifact Registry
gcloud auth configure-docker us-central1-docker.pkg.dev
```

### 1.4 Build e push da imagem Docker

```bash
# Na raiz do projeto
cd fintech-intel

PROJECT_ID=$(gcloud config get-value project)
REGION=us-central1
IMAGE="$REGION-docker.pkg.dev/$PROJECT_ID/fintech-backend/api:latest"

# Build para linux/amd64 (obrigatório para Cloud Run)
docker build \
  --platform linux/amd64 \
  -t "$IMAGE" \
  ./backend

docker push "$IMAGE"
```

### 1.5 Deploy no Cloud Run

```bash
# Obter o secret
SECRET_NAME="projects/$PROJECT_ID/secrets/DEEPSEEK_API_KEY/versions/latest"

gcloud run deploy fintech-intel-api \
  --image="$IMAGE" \
  --region="$REGION" \
  --platform=managed \
  --allow-unauthenticated \
  --port=8000 \
  --memory=2Gi \
  --cpu=2 \
  --min-instances=0 \
  --max-instances=5 \
  --set-secrets="DEEPSEEK_API_KEY=$SECRET_NAME" \
  --set-env-vars="\
DB_PATH=/tmp/fintech.db,\
FAISS_INDEX_PATH=/tmp/faiss.index,\
FAISS_META_PATH=/tmp/faiss_meta.json,\
EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2,\
RAG_TOP_K=10,\
CLASSIFIER_BATCH_SIZE=20"

# Obter a URL do serviço
BACKEND_URL=$(gcloud run services describe fintech-intel-api \
  --region="$REGION" \
  --format="value(status.url)")

echo "Backend URL: $BACKEND_URL"
```

> **Atenção:** Com `--min-instances=0`, a primeira requisição pode demorar ~10s
> (cold start + carregamento do modelo ONNX). Para produção, use `--min-instances=1`.

### 1.6 Verificar o deploy

```bash
curl "$BACKEND_URL/health"
# Esperado: {"status":"ok","version":"1.0.0"}
```

### 1.7 Configurar CI/CD com Cloud Build (opcional)

Crie o arquivo `cloudbuild.yaml` na raiz:

```yaml
# cloudbuild.yaml
steps:
  - name: 'gcr.io/cloud-builders/docker'
    args:
      - build
      - '--platform'
      - 'linux/amd64'
      - '-t'
      - 'us-central1-docker.pkg.dev/$PROJECT_ID/fintech-backend/api:$COMMIT_SHA'
      - './backend'

  - name: 'gcr.io/cloud-builders/docker'
    args:
      - push
      - 'us-central1-docker.pkg.dev/$PROJECT_ID/fintech-backend/api:$COMMIT_SHA'

  - name: 'gcr.io/google.com/cloudsdktool/cloud-sdk'
    entrypoint: gcloud
    args:
      - run
      - deploy
      - fintech-intel-api
      - '--image=us-central1-docker.pkg.dev/$PROJECT_ID/fintech-backend/api:$COMMIT_SHA'
      - '--region=us-central1'
      - '--platform=managed'

images:
  - 'us-central1-docker.pkg.dev/$PROJECT_ID/fintech-backend/api:$COMMIT_SHA'
```

```bash
# Conectar repositório GitHub ao Cloud Build
gcloud builds triggers create github \
  --repo-name=fintech-intel \
  --repo-owner=SEU_USUARIO_GITHUB \
  --branch-pattern='^main$' \
  --build-config=cloudbuild.yaml
```

---

## Parte 2: Frontend no Vercel

### 2.1 Instalar e configurar o Vercel CLI

```bash
cd fintech-intel/frontend
vercel login    # Abre o browser para autenticação
```

### 2.2 Primeiro deploy (configuração interativa)

```bash
vercel

# Responda as perguntas:
# ? Set up and deploy "fintech-intel/frontend"? → Y
# ? Which scope? → Selecione sua conta
# ? Link to existing project? → N
# ? What's your project's name? → fintech-intel-frontend
# ? In which directory is your code located? → ./
# ? Want to modify settings? → N
```

### 2.3 Configurar variável de ambiente no Vercel

```bash
# Substitua pela URL real do Cloud Run obtida no Passo 1.5
BACKEND_URL="https://fintech-intel-api-XXXX-uc.a.run.app"

vercel env add NEXT_PUBLIC_API_URL production
# Cole o valor: https://fintech-intel-api-XXXX-uc.a.run.app
# Confirme com Enter

# Para preview e development também (opcional):
vercel env add NEXT_PUBLIC_API_URL preview
vercel env add NEXT_PUBLIC_API_URL development
```

> **Importante:** `NEXT_PUBLIC_` vars são embutidas no bundle em build time.
> Toda vez que mudar a URL do backend, rode `vercel --prod` novamente.

### 2.4 Deploy de produção

```bash
vercel --prod
# URL de produção: https://fintech-intel-frontend.vercel.app
```

### 2.5 CORS — configurar o backend para aceitar o domínio Vercel

Edite `backend/app/main.py`, substitua o CORS wildcard por:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://fintech-intel-frontend.vercel.app",
        "https://seu-dominio-customizado.com",
        "http://localhost:3000",  # dev local
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

Faça o rebuild e redeploy do backend após esta mudança.

### 2.6 CI/CD no Vercel (automático via GitHub)

1. Acesse https://vercel.com/dashboard
2. Selecione o projeto → Settings → Git
3. Conecte ao repositório GitHub
4. Configure: Production Branch = `main`
5. Cada push para `main` → deploy automático

---

## Parte 3: Variáveis de ambiente — resumo completo

### Backend (Cloud Run / local)

| Variável | Obrigatória | Descrição |
|---|---|---|
| `DEEPSEEK_API_KEY` | Sim | Chave API do DeepSeek |
| `DEEPSEEK_BASE_URL` | Não | Default: `https://api.deepseek.com` |
| `DEEPSEEK_MODEL` | Não | Default: `deepseek-chat` |
| `DB_PATH` | Não | Path do SQLite. Default: `data/fintech.db` |
| `FAISS_INDEX_PATH` | Não | Default: `data/faiss.index` |
| `FAISS_META_PATH` | Não | Default: `data/faiss_meta.json` |
| `EMBEDDING_MODEL` | Não | Default: `sentence-transformers/all-MiniLM-L6-v2` |
| `RAG_TOP_K` | Não | Default: `10` |

### Frontend (Vercel)

| Variável | Obrigatória | Descrição |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | Sim | URL completa do backend Cloud Run |

---

## Parte 4: Domínio customizado (opcional)

### Vercel (frontend)
```bash
vercel domains add seudominio.com
# Siga as instruções para configurar DNS (CNAME ou A record)
```

### Cloud Run (backend)
```bash
gcloud run domain-mappings create \
  --service=fintech-intel-api \
  --domain=api.seudominio.com \
  --region=us-central1
# Configure o DNS conforme instrução (CNAME para ghs.googlehosted.com)
```

---

## Parte 5: Escalabilidade — próximos passos para produção real

### Problema 1: SQLite não escala com múltiplas instâncias
Cloud Run pode ter múltiplas instâncias simultâneas. Cada uma teria seu próprio
SQLite em `/tmp`, sem compartilhamento.

**Solução:** Migrar para Cloud SQL (PostgreSQL):
```bash
gcloud sql instances create fintech-db \
  --database-version=POSTGRES_15 \
  --tier=db-f1-micro \
  --region=us-central1

gcloud sql databases create fintech --instance=fintech-db
```

### Problema 2: FAISS index em `/tmp` é volátil
O `/tmp` no Cloud Run é limpo entre instâncias e cold starts.

**Solução:** Usar Cloud Storage para persistir o índice:
```bash
gsutil mb -l us-central1 gs://fintech-intel-faiss/
```
E modificar `build_faiss_index` e `_load_index` para usar `google-cloud-storage`.

### Problema 3: Job store in-memory não funciona em múltiplas instâncias
O `job_store.py` usa memória local. Em múltiplas instâncias, o polling pode
bater em instâncias diferentes.

**Solução:** Substituir por Redis (via Memorystore) ou Firestore:
```bash
gcloud redis instances create fintech-jobs \
  --size=1 \
  --region=us-central1 \
  --tier=BASIC
```

---

## Checklist de deploy

- [ ] `gcloud auth login` executado
- [ ] APIs GCP habilitadas (run, artifactregistry, secretmanager)
- [ ] `DEEPSEEK_API_KEY` criado no Secret Manager
- [ ] Artifact Registry criado
- [ ] Imagem Docker buildada para `linux/amd64`
- [ ] Cloud Run deployado e `/health` respondendo
- [ ] `NEXT_PUBLIC_API_URL` configurado no Vercel
- [ ] Frontend deployado no Vercel
- [ ] CORS atualizado com o domínio Vercel real
- [ ] Teste end-to-end: upload → chat → insights
