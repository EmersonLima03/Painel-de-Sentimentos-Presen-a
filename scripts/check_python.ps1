# Script para verificar versões do Python instaladas

Write-Host "=== Verificando versões do Python instaladas ===" -ForegroundColor Cyan
Write-Host ""

# Listar todas as versões
Write-Host "Versões disponíveis:" -ForegroundColor Yellow
py -0p

Write-Host "`nTestando versões específicas:" -ForegroundColor Yellow

$versions = @("3.11", "3.12", "3.13", "3.14")

foreach ($ver in $versions) {
    try {
        $result = py -$ver --version 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Host "  ✓ Python $ver : $result" -ForegroundColor Green
        } else {
            Write-Host "  ✗ Python $ver : Não encontrado" -ForegroundColor Red
        }
    } catch {
        Write-Host "  ✗ Python $ver : Erro" -ForegroundColor Red
    }
}

Write-Host "`nRecomendação:" -ForegroundColor Cyan
Write-Host "  Para este projeto, use Python 3.11 ou 3.12" -ForegroundColor White
Write-Host "  Python 3.14 requer compilação de código-fonte (mais complexo)" -ForegroundColor Yellow
