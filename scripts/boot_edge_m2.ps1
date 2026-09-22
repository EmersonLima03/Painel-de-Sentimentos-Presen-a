# Boot Edge (:8000) + M2 enrollment (:8766)
# M2 failure must NOT stop Edge. Named Tunnel points only to :8000.

param(
    [switch]$SkipM2,
    [switch]$SkipFrontendBuild,
    [string]$PublicBaseUrl = $env:M2_PUBLIC_BASE_URL
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Import-DotEnv([string]$Path) {
    if (-not (Test-Path $Path)) { return }
    Get-Content $Path | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#")) { return }
        $idx = $line.IndexOf("=")
        if ($idx -lt 1) { return }
        $k = $line.Substring(0, $idx).Trim()
        $v = $line.Substring($idx + 1).Trim().Trim('"').Trim("'")
        if (-not [string]::IsNullOrWhiteSpace($k)) {
            [Environment]::SetEnvironmentVariable($k, $v, "Process")
        }
    }
    Write-Host "Loaded env from $Path (values not printed)" -ForegroundColor DarkGray
}

# Prefer worktree .env, then sibling Presenca .env (never print secrets)
Import-DotEnv (Join-Path $Root ".env")
Import-DotEnv (Join-Path (Split-Path $Root) "Presenca\.env")

Write-Host "=== Boot Edge + M2 (Presenca) ===" -ForegroundColor Cyan
Write-Host "Root: $Root"
Write-Host ("SUPABASE_URL set: " + ([bool]$env:SUPABASE_URL)) -ForegroundColor DarkGray
Write-Host ("SERVICE_ROLE set: " + ([bool]($env:SUPABASE_SERVICE_ROLE_KEY -or $env:M2_OPS_SUPABASE_SERVICE_KEY))) -ForegroundColor DarkGray
Write-Host ("M2_ROSTER_SOURCE: " + ($(if ($env:M2_ROSTER_SOURCE) { $env:M2_ROSTER_SOURCE } else { "auto" }))) -ForegroundColor DarkGray

if (-not $SkipFrontendBuild) {
    if (Test-Path "frontend\package.json") {
        Write-Host "Building Dashboard frontend..." -ForegroundColor Yellow
        Push-Location frontend
        if (-not (Test-Path "node_modules")) { npm install }
        npm run build
        Pop-Location
    }
}

# Ensure HMAC for M2 tokens
if (-not $env:M2_ENROLL_HMAC_SECRET) {
    $env:M2_ENROLL_HMAC_SECRET = -join ((1..48) | ForEach-Object { "{0:x}" -f (Get-Random -Max 16) })
    Write-Host "Generated ephemeral M2_ENROLL_HMAC_SECRET (set permanently in .env for prod)" -ForegroundColor Yellow
}

if ($PublicBaseUrl) {
    $env:M2_PUBLIC_BASE_URL = $PublicBaseUrl.TrimEnd("/")
    Write-Host "M2_PUBLIC_BASE_URL=$($env:M2_PUBLIC_BASE_URL)" -ForegroundColor Green
} else {
    Write-Host "M2_PUBLIC_BASE_URL not set — QR will use request host (ok for lab; set HTTPS host for Named Tunnel)" -ForegroundColor Yellow
}

$env:M2_UPSTREAM_URL = if ($env:M2_UPSTREAM_URL) { $env:M2_UPSTREAM_URL } else { "http://127.0.0.1:8766" }

# Operational boot: test hooks ALWAYS off (force-step / synthetic embeddings).
# Automated F3/F4 harnesses set M2_POC_TEST_HOOKS=1 themselves when starting pytest.
$env:M2_POC_TEST_HOOKS = "0"
Write-Host "M2_POC_TEST_HOOKS: 0 (operational)" -ForegroundColor DarkGray

$m2Proc = $null
if (-not $SkipM2) {
    $m2Dir = Join-Path $Root "experiments\smoke_e2e_sentimentos\modulo2_poc"
    $m2Script = Join-Path $m2Dir "scripts\enrollment_gestor_server.py"
    if (-not (Test-Path $m2Script)) {
        Write-Host "M2 script missing: $m2Script — Edge will start alone" -ForegroundColor Red
    } else {
        Write-Host "Starting M2 on :8766 ..." -ForegroundColor Yellow
        $m2Proc = Start-Process -FilePath "python" -ArgumentList @(
            $m2Script, "--host", "127.0.0.1", "--port", "8766"
        ) -WorkingDirectory $m2Dir -PassThru -WindowStyle Minimized
        Start-Sleep -Seconds 2
        try {
            $h = Invoke-WebRequest -Uri "http://127.0.0.1:8766/healthz" -UseBasicParsing -TimeoutSec 3
            Write-Host "M2 health: $($h.StatusCode) pid=$($m2Proc.Id)" -ForegroundColor Green
        } catch {
            Write-Host "M2 health FAIL (Edge continues): $_" -ForegroundColor Red
        }
    }
}

Write-Host "Starting Edge on :8000 ..." -ForegroundColor Yellow
Write-Host "Dashboard: http://127.0.0.1:8000/dashboard" -ForegroundColor Cyan
Write-Host "Cadastro facial (via Edge): http://127.0.0.1:8000/gestor/" -ForegroundColor Cyan
Write-Host "M2 health via Edge: http://127.0.0.1:8000/m2/healthz" -ForegroundColor Cyan
Write-Host "Debug Vision: http://127.0.0.1:8000/debug/vision" -ForegroundColor Cyan
Write-Host "CTRL+C stops Edge; M2 child (if any) should be stopped manually if orphaned.`n" -ForegroundColor Yellow

try {
    python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
} finally {
    if ($m2Proc -and -not $m2Proc.HasExited) {
        Write-Host "Stopping M2 pid=$($m2Proc.Id)" -ForegroundColor Yellow
        Stop-Process -Id $m2Proc.Id -Force -ErrorAction SilentlyContinue
    }
}
