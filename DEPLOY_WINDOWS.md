# Deploy no Windows — Do Zero ao GCP Cloud Run + Vercel

> Guia sequencial para quem está partindo do zero no Windows.
> Tempo estimado: 45–60 min (inclui downloads).

---

## Visão Geral das Etapas

```
1. Instalar WSL2          (subsistema Linux no Windows)
2. Instalar Docker Desktop
3. Instalar gcloud CLI
4. Instalar Node.js + Vercel CLI
5. Criar conta GCP + projeto + billing
6. Configurar GCP (APIs, Secret Manager, Artifact Registry)
7. Build + push da imagem Docker
8. Deploy no Cloud Run
9. Deploy frontend no Vercel
10. Configurar CORS e testar end-to-end
```

---

## Etapa 1 — Instalar WSL2 (Ubuntu no Windows)

WSL2 é obrigatório para rodar Docker Desktop de forma estável no Windows.

### 1.1 Abrir PowerShell como Administrador

Clique com botão direito no menu Iniciar → **Windows PowerShell (Administrador)**.

### 1.2 Instalar WSL2 com Ubuntu

```powershell
wsl --install
```

> Isso instala o WSL2 + Ubuntu 22.04 automaticamente.
> **Reinicie o computador** quando solicitado.

### 1.3 Configurar o usuário Ubuntu

Após reiniciar, o Ubuntu abrirá automaticamente pedindo um nome de usuário e senha.
Escolha qualquer nome (ex: `pedro`) e uma senha simples.

### 1.4 Verificar instalação

No PowerShell:
```powershell
wsl --list --verbose
```
Esperado:
```
  NAME      STATE           VERSION
* Ubuntu    Running         2
```

---

## Etapa 2 — Instalar Docker Desktop

### 2.1 Download

Acesse: https://www.docker.com/products/docker-desktop/
Baixe a versão **Windows (AMD64)**.

### 2.2 Instalar

Execute o instalador. Na tela de opções, mantenha marcado:
- ✅ **Use WSL 2 instead of Hyper-V**

### 2.3 Configurar integração com WSL

Após instalar e abrir o Docker Desktop:
1. Vá em **Settings** (engrenagem no canto superior direito)
2. Clique em **Resources → WSL Integration**
3. Ative o toggle do **Ubuntu**
4. Clique em **Apply & Restart**

### 2.4 Verificar

Abra o **Ubuntu** (pelo menu Iniciar) e execute:
```bash
docker --version
# Docker version 26.x.x
```

---

## Etapa 3 — Instalar Google Cloud SDK (gcloud)

> Execute todos os comandos abaixo dentro do terminal **Ubuntu** (WSL2).

### 3.1 Instalar dependências

```bash
sudo apt-get update && sudo apt-get install -y apt-transport-https ca-certificates gnupg curl
```

### 3.2 Adicionar repositório Google

```bash
curl https://packages.cloud.google.com/apt/doc/apt-key.gpg | \
  sudo gpg --dearmor -o /usr/share/keyrings/cloud.google.gpg

echo "deb [signed-by=/usr/share/keyrings/cloud.google.gpg] \
  https://packages.cloud.google.com/apt cloud-sdk main" | \
  sudo tee /etc/apt/sources.list.d/google-cloud-sdk.list
```

### 3.3 Instalar

```bash
sudo apt-get update && sudo apt-get install -y google-cloud-cli
```

### 3.4 Verificar

```bash
gcloud --version
# Google Cloud SDK 500.x.x
```

---

## Etapa 4 — Instalar Node.js + Vercel CLI

### 4.1 Instalar Node.js via nvm (dentro do Ubuntu)

```bash
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash

# Recarregar o shell
source ~/.bashrc

# Instalar Node.js LTS
nvm install --lts
nvm use --lts

node --version   # v20.x.x
npm --version    # 10.x.x
```

### 4.2 Instalar Vercel CLI

```bash
npm install -g vercel
vercel --version   # Vercel CLI 37.x.x
```

---

## Etapa 5 — Criar Conta GCP e Projeto

### 5.1 Criar conta Google Cloud

1. Acesse: https://cloud.google.com/
2. Clique em **Comece gratuitamente** (US$300 em créditos por 90 dias)
3. Faça login com sua conta Google
4. Preencha os dados de cobrança (cartão necessário, mas **não será cobrado** no free tier)

### 5.2 Autenticar o gcloud CLI

No terminal Ubuntu:
```bash
gcloud auth login
```
Um link será exibido. Abra no navegador Windows, faça login com a conta Google e copie o código de verificação de volta no terminal.

### 5.3 Criar o projeto GCP

```bash
# Cria o projeto (ID único globalmente — mude se já existir)
gcloud projects create fintech-intel-prod --name="FinTech Intel"

# Define como projeto padrão
gcloud config set project fintech-intel-prod
```

> **Nota:** Se o ID `fintech-intel-prod` já existir globalmente, use outro nome, ex: `fintech-intel-prod-2026`.

### 5.4 Verificar projeto ativo

```bash
gcloud config get-value project
# fintech-intel-prod
```

### 5.5 Ativar o billing no projeto

1. Acesse: https://console.cloud.google.com/billing
2. Selecione sua conta de faturamento
3. Associe ao projeto `fintech-intel-prod`

> Sem billing ativo, as APIs não funcionam.

---

## Etapa 6 — Configurar GCP (APIs + Secrets + Registry)

### 6.1 Habilitar APIs necessárias

```bash
gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com \
  cloudbuild.googleapis.com
```

> Aguarde ~1 minuto. Cada API será habilitada em sequência.

### 6.2 Armazenar a chave DeepSeek no Secret Manager

Substitua `sk-sua-chave-aqui` pela sua chave real do DeepSeek
(obtenha em https://platform.deepseek.com/api_keys):

```bash
echo -n "sk-sua-chave-aqui" | \
  gcloud secrets create DEEPSEEK_API_KEY \
    --data-file=- \
    --replication-policy=automatic
```

Verificar se foi salvo:
```bash
gcloud secrets versions access latest --secret=DEEPSEEK_API_KEY
# deve exibir: sk-sua-chave-aqui
```

### 6.3 Criar Artifact Registry (repositório de imagens Docker)

```bash
gcloud artifacts repositories create fintech-backend \
  --repository-format=docker \
  --location=us-central1 \
  --description="FinTech Intel backend images"
```

### 6.4 Autenticar o Docker no Artifact Registry

```bash
gcloud auth configure-docker us-central1-docker.pkg.dev
```

Responda `Y` quando perguntado.

---

## Etapa 7 — Build e Push da Imagem Docker

### 7.1 Navegar até o projeto

No terminal Ubuntu, navegue até a pasta do projeto.
A pasta do Windows fica disponível em `/mnt/c/` no WSL2.

Por exemplo, se o projeto está em `C:\Users\Pedro\fintech-intel`:
```bash
cd /mnt/c/Users/Pedro/fintech-intel
```

> **Dica:** Para descobrir o caminho, abra o Explorer do Windows na pasta do projeto,
> clique na barra de endereços e copie o caminho. Substitua `C:\` por `/mnt/c/`
> e troque `\` por `/`.

### 7.2 Definir variáveis de ambiente

```bash
PROJECT_ID=$(gcloud config get-value project)
REGION=us-central1
IMAGE="$REGION-docker.pkg.dev/$PROJECT_ID/fintech-backend/api:latest"

echo "PROJECT_ID: $PROJECT_ID"
echo "IMAGE: $IMAGE"
```

### 7.3 Build da imagem (linux/amd64 obrigatório para Cloud Run)

```bash
docker build \
  --platform linux/amd64 \
  -t "$IMAGE" \
  ./backend
```

> Este passo pode demorar 5–15 min na primeira vez (baixa as dependências Python).
> Nas próximas vezes será muito mais rápido (cache de layers).

### 7.4 Push para o Artifact Registry

```bash
docker push "$IMAGE"
```

---

## Etapa 8 — Deploy no Cloud Run

### 8.1 Deploy do serviço

```bash
PROJECT_ID=$(gcloud config get-value project)
REGION=us-central1
IMAGE="$REGION-docker.pkg.dev/$PROJECT_ID/fintech-backend/api:latest"
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
  --set-env-vars="DB_PATH=/tmp/fintech.db,FAISS_INDEX_PATH=/tmp/faiss.index,FAISS_META_PATH=/tmp/faiss_meta.json,EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2,RAG_TOP_K=10,CLASSIFIER_BATCH_SIZE=20"
```

Responda `Y` se perguntado sobre a região.

### 8.2 Obter a URL do backend

```bash
BACKEND_URL=$(gcloud run services describe fintech-intel-api \
  --region="$REGION" \
  --format="value(status.url)")

echo "Backend URL: $BACKEND_URL"
```

Anote essa URL — ela terá o formato:
```
https://fintech-intel-api-XXXXXXXXXX-uc.a.run.app
```

### 8.3 Testar o backend

```bash
curl "$BACKEND_URL/health"
# Esperado: {"status":"ok","version":"1.0.0"}
```

---

## Etapa 9 — Deploy Frontend no Vercel

### 9.1 Entrar na pasta do frontend

```bash
cd /mnt/c/Users/Pedro/fintech-intel/frontend
```

### 9.2 Fazer login no Vercel

```bash
vercel login
```

Escolha **Continue with Email** ou **Continue with GitHub**.
Um link de confirmação será enviado. Abra no navegador e confirme.

### 9.3 Primeiro deploy (configuração interativa)

```bash
vercel
```

Responda as perguntas:
```
? Set up and deploy? → Y
? Which scope? → (sua conta)
? Link to existing project? → N
? What's your project's name? → fintech-intel-frontend
? In which directory is your code located? → ./
? Want to modify settings? → N
```

### 9.4 Configurar a variável de ambiente NEXT_PUBLIC_API_URL

Substitua pela URL real obtida na Etapa 8.2:

```bash
vercel env add NEXT_PUBLIC_API_URL production
# Cole a URL: https://fintech-intel-api-XXXXXXXXXX-uc.a.run.app
# Pressione Enter para confirmar
```

### 9.5 Deploy de produção (com a variável correta)

```bash
vercel --prod
```

A URL de produção será exibida:
```
✅  Production: https://fintech-intel-frontend.vercel.app
```

---

## Etapa 10 — Configurar CORS e Testar

### 10.1 Atualizar o CORS no backend

Edite o arquivo `backend/app/main.py` e substitua o `allow_origins=["*"]` pelo domínio Vercel real:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://fintech-intel-frontend.vercel.app",
        "http://localhost:3000",  # dev local
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

### 10.2 Rebuild e redeploy do backend após mudança do CORS

```bash
cd /mnt/c/Users/Pedro/fintech-intel

PROJECT_ID=$(gcloud config get-value project)
REGION=us-central1
IMAGE="$REGION-docker.pkg.dev/$PROJECT_ID/fintech-backend/api:latest"

docker build --platform linux/amd64 -t "$IMAGE" ./backend
docker push "$IMAGE"

gcloud run deploy fintech-intel-api \
  --image="$IMAGE" \
  --region="$REGION" \
  --platform=managed
```

### 10.3 Teste end-to-end

1. Abra no navegador: `https://fintech-intel-frontend.vercel.app`
2. Faça upload de um arquivo `.xlsx` de transações
3. Aguarde o processamento (barra de progresso)
4. Navegue até a aba **Chat**
5. Pergunte: *"Qual é a receita total do período?"*
6. Verifique se a resposta vem com streaming (tokens aparecendo um a um)

---

## Checklist Final

- [ ] WSL2 + Ubuntu instalado e rodando
- [ ] Docker Desktop com integração WSL2 ativa
- [ ] `gcloud` instalado e autenticado (`gcloud auth login`)
- [ ] Projeto GCP criado com billing ativo
- [ ] APIs habilitadas: run, artifactregistry, secretmanager
- [ ] `DEEPSEEK_API_KEY` criado no Secret Manager
- [ ] Artifact Registry `fintech-backend` criado
- [ ] Imagem buildada para `linux/amd64` e enviada ao registry
- [ ] Cloud Run respondendo em `/health`
- [ ] `NEXT_PUBLIC_API_URL` configurada no Vercel
- [ ] Frontend deployado e acessível
- [ ] CORS atualizado com o domínio Vercel real
- [ ] Rebuild do backend com CORS correto
- [ ] Teste end-to-end: upload → chat → streaming funcionando

---

## Problemas Comuns no Windows

### "docker: command not found" no WSL2
→ Verifique se o Docker Desktop está aberto e a integração WSL2 está ativa (Etapa 2.3).

### "permission denied" ao acessar /mnt/c/
→ Execute: `sudo chmod 755 /mnt/c/Users/SeuUsuario`

### gcloud auth login não abre o browser
→ Copie o link exibido manualmente e abra no browser do Windows.

### Build Docker falha com "no space left on device"
→ No Docker Desktop → Settings → Resources → aumente o Disk image size para 60GB+.

### Cloud Run retorna 403 na primeira requisição
→ Execute: `gcloud run services add-iam-policy-binding fintech-intel-api --region=us-central1 --member=allUsers --role=roles/run.invoker`

### "DEEPSEEK_API_KEY not found" no Cloud Run
→ Verifique se o service account do Cloud Run tem permissão: `roles/secretmanager.secretAccessor`.
Execute:
```bash
PROJECT_ID=$(gcloud config get-value project)
PROJECT_NUMBER=$(gcloud projects describe $PROJECT_ID --format="value(projectNumber)")
gcloud secrets add-iam-policy-binding DEEPSEEK_API_KEY \
  --member="serviceAccount:$PROJECT_NUMBER-compute@developer.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
```

---

## Custos Estimados (GCP Free Tier)

| Serviço | Free Tier | Custo após |
|---|---|---|
| Cloud Run | 2M req/mês + 360k vCPU-s | ~$0.00002/req |
| Artifact Registry | 0.5 GB/mês | $0.10/GB |
| Secret Manager | 10k acessos/mês | $0.06/10k |
| **Total MVP** | **Praticamente gratuito** | < $5/mês com uso leve |

> Vercel é **gratuito** para projetos pessoais (Hobby plan).
