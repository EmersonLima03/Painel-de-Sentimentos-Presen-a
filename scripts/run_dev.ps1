# Script para rodar em desenvolvimento (Windows PowerShell)

Write-Host "=== Dulino Edge Vision - Dev Mode ===" -ForegroundColor Cyan

# Verificar se .env existe
if (-not (Test-Path .env)) {
    Write-Host "Criando .env a partir de .env.example..." -ForegroundColor Yellow
    Copy-Item .env.example .env
    Write-Host "Por favor, edite .env com suas configurações" -ForegroundColor Yellow
}

# Criar diretório de dados
New-Item -ItemType Directory -Force -Path data | Out-Null

# Verificar ambiente virtual
if (-not (Test-Path venv)) {
    Write-Host "Criando ambiente virtual..." -ForegroundColor Yellow
    python -m venv venv
}

# Ativar ambiente virtual
& .\venv\Scripts\Activate.ps1

Write-Host "Instalando dependências..." -ForegroundColor Cyan
# python -m evita bloqueio do Windows (App Control) em pip.exe/uvicorn.exe no venv
python -m pip install -r requirements.txt

Write-Host "Iniciando aplicação..." -ForegroundColor Green
$env:PYTHONUNBUFFERED = "1"
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
