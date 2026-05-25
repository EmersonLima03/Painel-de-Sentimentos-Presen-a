# Script para testar se o servidor está respondendo

Write-Host "=== Testando Servidor ===" -ForegroundColor Cyan

$urls = @(
    "http://localhost:8000/health",
    "http://127.0.0.1:8000/health",
    "http://0.0.0.0:8000/health"
)

foreach ($url in $urls) {
    Write-Host "`nTestando: $url" -ForegroundColor Yellow
    try {
        $response = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 5 -ErrorAction Stop
        Write-Host "✓ SUCESSO! Status: $($response.StatusCode)" -ForegroundColor Green
        Write-Host "Resposta:" -ForegroundColor Cyan
        $response.Content | ConvertFrom-Json | ConvertTo-Json -Depth 10
        break
    } catch {
        Write-Host "✗ FALHOU: $($_.Exception.Message)" -ForegroundColor Red
    }
}

Write-Host "`n=== Verificando Porta 8000 ===" -ForegroundColor Cyan
$port = Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue
if ($port) {
    Write-Host "✓ Porta 8000 está em uso" -ForegroundColor Green
    Write-Host "Estado: $($port.State)" -ForegroundColor Cyan
} else {
    Write-Host "✗ Porta 8000 NÃO está em uso" -ForegroundColor Red
    Write-Host "O servidor pode não estar rodando!" -ForegroundColor Yellow
}
