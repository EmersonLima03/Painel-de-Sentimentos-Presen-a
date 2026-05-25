# Script para configurar ambiente com Python 3.11
# Execute este script APÓS instalar Python 3.11

Write-Host "=== Configurando ambiente Python 3.11 ===" -ForegroundColor Cyan

# Verificar se Python 3.11 está disponível
Write-Host "`nVerificando Python 3.11..." -ForegroundColor Yellow
try {
    $python311 = py -3.11 --version 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "✓ Python 3.11 encontrado: $python311" -ForegroundColor Green
    } else {
        Write-Host "✗ Python 3.11 não encontrado!" -ForegroundColor Red
        Write-Host "`nPor favor, instale Python 3.11 primeiro:" -ForegroundColor Yellow
        Write-Host "  https://www.python.org/downloads/release/python-31111/" -ForegroundColor Cyan
        Write-Host "`nMarque 'Add Python to PATH' durante a instalação." -ForegroundColor Yellow
        exit 1
    }
} catch {
    Write-Host "✗ Erro ao verificar Python 3.11" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}

# Desativar venv atual se estiver ativo
if ($env:VIRTUAL_ENV) {
    Write-Host "`nDesativando venv atual..." -ForegroundColor Yellow
    deactivate
}

# Remover venv antigo
if (Test-Path "venv") {
    Write-Host "Removendo venv antigo..." -ForegroundColor Yellow
    Remove-Item -Recurse -Force venv
    Write-Host "✓ Venv antigo removido" -ForegroundColor Green
}

# Criar novo venv com Python 3.11
Write-Host "`nCriando novo venv com Python 3.11..." -ForegroundColor Cyan
py -3.11 -m venv venv

if ($LASTEXITCODE -ne 0) {
    Write-Host "✗ Erro ao criar venv" -ForegroundColor Red
    exit 1
}

Write-Host "✓ Venv criado com sucesso" -ForegroundColor Green

# Ativar venv
Write-Host "`nAtivando venv..." -ForegroundColor Cyan
& .\venv\Scripts\Activate.ps1

# Verificar versão
$version = python --version
Write-Host "✓ Versão do Python no venv: $version" -ForegroundColor Green

if ($version -notmatch "Python 3\.(11|12)") {
    Write-Host "⚠ AVISO: Versão do Python não é 3.11 ou 3.12!" -ForegroundColor Yellow
    Write-Host "  Versão atual: $version" -ForegroundColor Yellow
}

# Atualizar pip
Write-Host "`nAtualizando pip, setuptools e wheel..." -ForegroundColor Cyan
python -m pip install --upgrade pip setuptools wheel

if ($LASTEXITCODE -ne 0) {
    Write-Host "✗ Erro ao atualizar pip" -ForegroundColor Red
    exit 1
}

Write-Host "✓ Pip atualizado" -ForegroundColor Green

# Instalar dependências
Write-Host "`nInstalando dependências do projeto..." -ForegroundColor Cyan
Write-Host "Isso pode levar alguns minutos..." -ForegroundColor Yellow

pip install -r requirements.txt

if ($LASTEXITCODE -eq 0) {
    Write-Host "`n=== ✓ Instalação concluída com sucesso! ===" -ForegroundColor Green
    Write-Host "`nPróximos passos:" -ForegroundColor Cyan
    Write-Host "  1. Copie .env.example para .env" -ForegroundColor White
    Write-Host "  2. Edite .env com suas configurações" -ForegroundColor White
    Write-Host "  3. Execute: uvicorn app.main:app --reload" -ForegroundColor White
} else {
    Write-Host "`n✗ Erro na instalação de dependências" -ForegroundColor Red
    Write-Host "Verifique os erros acima e tente novamente." -ForegroundColor Yellow
    exit 1
}
