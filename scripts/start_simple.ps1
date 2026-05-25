# Script para iniciar servidor de forma simples (sem RTSP)

Write-Host "=== Iniciando Servidor (Modo Simples) ===" -ForegroundColor Cyan

# Ativar venv se não estiver
if (-not $env:VIRTUAL_ENV) {
    Write-Host "Ativando ambiente virtual..." -ForegroundColor Yellow
    & .\venv\Scripts\Activate.ps1
}

# Verificar se app existe
if (-not (Test-Path "app\main.py")) {
    Write-Host "ERRO: app\main.py não encontrado!" -ForegroundColor Red
    exit 1
}

Write-Host "`nIniciando servidor em localhost:8000..." -ForegroundColor Green
Write-Host "Acesse: http://localhost:8000/health" -ForegroundColor Cyan
Write-Host "Pressione CTRL+C para parar`n" -ForegroundColor Yellow

# Iniciar com localhost (mais confiável no Windows)
python -m uvicorn app.main:app --reload --host localhost --port 8000
