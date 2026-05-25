# Script para iniciar o servidor corretamente

Write-Host "=== Iniciando Dulino Edge Vision ===" -ForegroundColor Cyan

# Verificar se venv existe
if (-not (Test-Path "venv")) {
    Write-Host "ERRO: Ambiente virtual não encontrado!" -ForegroundColor Red
    Write-Host "Execute primeiro:" -ForegroundColor Yellow
    Write-Host "  py -3.11 -m venv venv" -ForegroundColor White
    Write-Host "  .\venv\Scripts\Activate.ps1" -ForegroundColor White
    Write-Host "  pip install -r requirements.txt" -ForegroundColor White
    exit 1
}

# Verificar se está ativado
if (-not $env:VIRTUAL_ENV) {
    Write-Host "Ativando ambiente virtual..." -ForegroundColor Yellow
    & .\venv\Scripts\Activate.ps1
}

# Verificar se uvicorn está instalado
Write-Host "Verificando uvicorn..." -ForegroundColor Cyan
$uvicornCheck = python -c "import uvicorn; print('OK')" 2>&1

if ($LASTEXITCODE -ne 0) {
    Write-Host "uvicorn não encontrado. Instalando..." -ForegroundColor Yellow
    pip install uvicorn[standard]
}

# Verificar se app.main existe
if (-not (Test-Path "app\main.py")) {
    Write-Host "ERRO: app\main.py não encontrado!" -ForegroundColor Red
    exit 1
}

Write-Host "`n=== Iniciando servidor ===" -ForegroundColor Green
Write-Host "Acesse: http://localhost:8000/health" -ForegroundColor Cyan
Write-Host "Pressione CTRL+C para parar`n" -ForegroundColor Yellow

# Iniciar servidor
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
