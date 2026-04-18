# ============================================================
# limpar_espaco_windows.ps1
# Execute como Administrador no PowerShell:
#   Set-ExecutionPolicy -Scope Process Bypass
#   .\limpar_espaco_windows.ps1
# ============================================================

$ErrorActionPreference = "SilentlyContinue"

function Show-Size($path) {
    if (Test-Path $path) {
        $size = (Get-ChildItem $path -Recurse -Force | Measure-Object -Property Length -Sum).Sum
        "{0:N0} MB" -f ($size / 1MB)
    } else { "N/A" }
}

Write-Host "`n=== LIMPEZA DE DISCO — C: ===" -ForegroundColor Cyan
$before = (Get-PSDrive C).Free / 1GB
Write-Host ("Espaço livre ANTES: {0:N1} GB" -f $before) -ForegroundColor Yellow

# ── 1. Windows Temp ───────────────────────────────────────────────────────────
Write-Host "`n[1/9] Limpando pastas Temp do Windows..." -ForegroundColor Green
Remove-Item "$env:TEMP\*" -Recurse -Force
Remove-Item "C:\Windows\Temp\*" -Recurse -Force

# ── 2. Prefetch ───────────────────────────────────────────────────────────────
Write-Host "[2/9] Limpando Prefetch..." -ForegroundColor Green
Remove-Item "C:\Windows\Prefetch\*" -Force

# ── 3. Windows Update cache ───────────────────────────────────────────────────
Write-Host "[3/9] Limpando cache do Windows Update..." -ForegroundColor Green
Stop-Service wuauserv -Force
Remove-Item "C:\Windows\SoftwareDistribution\Download\*" -Recurse -Force
Start-Service wuauserv

# ── 4. Recycle Bin ───────────────────────────────────────────────────────────
Write-Host "[4/9] Esvaziando Lixeira..." -ForegroundColor Green
Clear-RecycleBin -Force

# ── 5. Docker — imagens/containers sem uso ───────────────────────────────────
Write-Host "[5/9] Limpando Docker (imagens/containers parados/build cache)..." -ForegroundColor Green
if (Get-Command docker -ErrorAction SilentlyContinue) {
    docker system prune -af --volumes 2>$null
    Write-Host "  Docker limpo." -ForegroundColor Gray
} else {
    Write-Host "  Docker não encontrado, pulando." -ForegroundColor Gray
}

# ── 6. npm cache ──────────────────────────────────────────────────────────────
Write-Host "[6/9] Limpando cache npm..." -ForegroundColor Green
if (Get-Command npm -ErrorAction SilentlyContinue) {
    npm cache clean --force 2>$null
}

# ── 7. pip cache ──────────────────────────────────────────────────────────────
Write-Host "[7/9] Limpando cache pip..." -ForegroundColor Green
if (Get-Command pip -ErrorAction SilentlyContinue) {
    pip cache purge 2>$null
}

# ── 8. Thumbnail cache ────────────────────────────────────────────────────────
Write-Host "[8/9] Limpando thumbnails do Explorer..." -ForegroundColor Green
Remove-Item "$env:LOCALAPPDATA\Microsoft\Windows\Explorer\thumbcache_*.db" -Force

# ── 9. Browser caches ─────────────────────────────────────────────────────────
Write-Host "[9/9] Limpando caches de navegadores..." -ForegroundColor Green
$browserCaches = @(
    "$env:LOCALAPPDATA\Google\Chrome\User Data\Default\Cache\Cache_Data\*",
    "$env:LOCALAPPDATA\Microsoft\Edge\User Data\Default\Cache\Cache_Data\*",
    "$env:APPDATA\Mozilla\Firefox\Profiles\*\cache2\entries\*"
)
foreach ($path in $browserCaches) {
    Remove-Item $path -Recurse -Force
}

# ── Resultado ─────────────────────────────────────────────────────────────────
$after = (Get-PSDrive C).Free / 1GB
$freed = $after - $before
Write-Host "`n=== RESULTADO ===" -ForegroundColor Cyan
Write-Host ("Espaço livre ANTES : {0:N1} GB" -f $before) -ForegroundColor Yellow
Write-Host ("Espaço livre DEPOIS : {0:N1} GB" -f $after)  -ForegroundColor Green
Write-Host ("Liberado            : +{0:N1} GB" -f $freed)  -ForegroundColor Green

# ── Mover Docker para D: (instrução) ─────────────────────────────────────────
Write-Host @"

=== AÇÃO RECOMENDADA: Mover Docker para D: ===
O Docker guarda todas as imagens em C: por padrão (pode ser 10-50GB).
Para mover para D: (que tem mais espaço):

  1. Abra Docker Desktop
  2. Settings → Resources → Advanced
  3. Em "Disk image location": troque para D:\Docker
  4. Clique "Apply & Restart"

Isso libera o espaço das imagens Docker do C: permanentemente.
"@ -ForegroundColor Magenta
