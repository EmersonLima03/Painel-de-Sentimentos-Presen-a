# Script de instalação de dependências para Windows
# Resolve problemas de compatibilidade com Python 3.14+

Write-Host "=== Instalando dependências ===" -ForegroundColor Cyan

# Verificar se está no ambiente virtual
if (-not $env:VIRTUAL_ENV) {
    Write-Host "AVISO: Ambiente virtual não detectado. Ative o venv primeiro:" -ForegroundColor Yellow
    Write-Host "  .\venv\Scripts\Activate.ps1" -ForegroundColor Yellow
    exit 1
}

# Atualizar pip, setuptools e wheel primeiro
Write-Host "Atualizando pip, setuptools e wheel..." -ForegroundColor Cyan
python -m pip install --upgrade pip setuptools wheel

# Verificar versão do Python
$pythonVersion = python --version
Write-Host "Python: $pythonVersion" -ForegroundColor Green

# Verificar se é Python 3.14+
if ($pythonVersion -match "Python 3\.(1[4-9]|[2-9]\d)") {
    Write-Host "Python 3.14+ detectado. Usando requirements-py314.txt..." -ForegroundColor Yellow
    $requirementsFile = "requirements-py314.txt"
} else {
    Write-Host "Usando requirements.txt padrão..." -ForegroundColor Green
    $requirementsFile = "requirements.txt"
}

# Instalar dependências
Write-Host "Instalando dependências de $requirementsFile..." -ForegroundColor Cyan
pip install -r $requirementsFile

if ($LASTEXITCODE -eq 0) {
    Write-Host "`n=== Instalação concluída com sucesso! ===" -ForegroundColor Green
    Write-Host "Execute: uvicorn app.main:app --reload" -ForegroundColor Cyan
} else {
    Write-Host "`n=== Erro na instalação ===" -ForegroundColor Red
    Write-Host "Tente instalar manualmente ou verifique os logs acima." -ForegroundColor Yellow
    exit 1
}
