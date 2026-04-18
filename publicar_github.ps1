# ============================================================
# publicar_github.ps1
# Inicializa o repositorio git local e publica no GitHub.
#
# PRE-REQUISITOS:
#   - Git instalado: https://git-scm.com/download/win
#   - GitHub CLI (gh): https://cli.github.com  (opcional)
#
# USO:
#   1. Abra o PowerShell nesta pasta
#   2. Execute:  .\publicar_github.ps1
# ============================================================

$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectDir

# -- Configuracoes: EDITE AQUI ----------------------------------------
$REPO_NAME   = "fintech-intel"
$DESCRIPTION = "AI-Powered Financial Intelligence Platform - FastAPI + Next.js + RAG + DeepSeek"
$VISIBILITY  = "public"
# ---------------------------------------------------------------------

Write-Host "`n=== Publicando $REPO_NAME no GitHub ===" -ForegroundColor Cyan

# 1. Remove .git corrompido se existir
if (Test-Path ".git") {
    Write-Host "[1/6] Removendo .git anterior..." -ForegroundColor Yellow
    Remove-Item -Recurse -Force ".git"
}

# 2. Inicializa repositorio
Write-Host "[2/6] Inicializando repositorio git..." -ForegroundColor Green
git init -b main
git config user.email (git config --global user.email)
git config user.name  (git config --global user.name)

# 3. Stage de todos os arquivos
Write-Host "[3/6] Adicionando arquivos..." -ForegroundColor Green
git add .
git status --short | Select-Object -First 20

# 4. Commit inicial via arquivo temporario (evita problemas de parsing no PS)
Write-Host "[4/6] Criando commit inicial..." -ForegroundColor Green
$commitMsg = "feat: initial commit - AI-Powered Financial Intelligence Platform

FastAPI backend with SQLite + FAISS vector search
DeepSeek LLM for classification, insights and RAG chat
Next.js 14 frontend with Recharts dashboard
Docker Compose setup (backend + frontend)
Anomaly detection Z-score + client risk scores
Cash flow projection via linear regression
23 unit tests passing
GitHub Actions CI/CD pipeline"

$tmpFile = [System.IO.Path]::GetTempFileName()
[System.IO.File]::WriteAllText($tmpFile, $commitMsg, [System.Text.Encoding]::UTF8)
git commit -F $tmpFile
Remove-Item $tmpFile

# 5. Cria repo no GitHub via gh CLI (se disponivel)
Write-Host "[5/6] Verificando GitHub CLI..." -ForegroundColor Green

if (Get-Command gh -ErrorAction SilentlyContinue) {
    $authStatus = gh auth status 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  Fazendo login no GitHub..." -ForegroundColor Yellow
        gh auth login
    }
    gh repo create $REPO_NAME --description $DESCRIPTION --$VISIBILITY --source=. --remote=origin --push
    Write-Host "[6/6] Publicado com sucesso!" -ForegroundColor Green
    $url = gh repo view --json url -q ".url"
    Write-Host "`n OK Repositorio disponivel em: $url" -ForegroundColor Cyan
} else {
    Write-Host "[5/6] GitHub CLI nao encontrado. Passos manuais:" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  OPCAO A - Pelo site (mais simples):" -ForegroundColor White
    Write-Host "    1. Acesse https://github.com/new"
    Write-Host "    2. Nome do repo: $REPO_NAME"
    Write-Host "    3. Deixe sem README (ja temos um)"
    Write-Host "    4. Clique Create repository"
    Write-Host "    5. Execute no PowerShell:"
    Write-Host ""
    Write-Host "       git remote add origin https://github.com/SEU_USUARIO/$REPO_NAME.git" -ForegroundColor Yellow
    Write-Host "       git push -u origin main" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  OPCAO B - Instalar GitHub CLI e rodar este script de novo:" -ForegroundColor White
    Write-Host "    winget install --id GitHub.cli" -ForegroundColor Yellow
}
