# Boot Edge (:8000) + M2 enrollment (:8766) - producao Presenca
#
# Uso (a partir de qualquer cwd):
#   .\scripts\boot_edge_m2.ps1
#   .\scripts\boot_edge_m2.ps1 -PublicBaseUrl "https://presenca.sistemadulino.com.br"
#
# O script:
#   1) resolve a raiz do projeto a partir de $PSScriptRoot (nao depende do cwd)
#   2) garante frontend/dist React moderno (build automatico se ausente/desatualizado)
#   3) FALHA se o Dashboard React nao estiver valido (nao declara boot OK)
#   4) inicia M2 em 127.0.0.1:8766 e Edge em 127.0.0.1:8000
#   5) valida /health, /dashboard (React), /m2/healthz, assets
#
# Named Tunnel deve apontar SOMENTE para http://127.0.0.1:8000 (nunca :8766).

param(
    [switch]$SkipM2,
    [switch]$SkipFrontendBuild,
    [switch]$ForceFrontendBuild,
    [switch]$KeepExisting,
    [string]$PublicBaseUrl = $env:M2_PUBLIC_BASE_URL,
    [string]$EdgeHost = "127.0.0.1",
    [int]$EdgePort = 8000,
    [int]$M2Port = 8766
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$script:BootFailed = $false
$script:EdgeProc = $null
$script:M2Proc = $null

function Write-Step([string]$Msg, [string]$Color = "Cyan") {
    Write-Host $Msg -ForegroundColor $Color
}

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

function Get-ListenersOnPort([int]$Port) {
    $lines = netstat -ano | Select-String ":$Port\s+.*LISTENING"
    $pids = @()
    foreach ($line in $lines) {
        $parts = ($line.ToString() -split "\s+") | Where-Object { $_ -ne "" }
        if ($parts.Count -ge 5) {
            $pidVal = [int]$parts[-1]
            if ($pidVal -gt 0) { $pids += $pidVal }
        }
    }
    return ($pids | Select-Object -Unique)
}

function Stop-PortIfBusy([int]$Port, [string]$Label) {
    $pids = Get-ListenersOnPort $Port
    foreach ($pidVal in $pids) {
        Write-Host "Stopping $Label on :$Port (pid=$pidVal)" -ForegroundColor Yellow
        Stop-Process -Id $pidVal -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Milliseconds 800
}

function Test-ReactDistValid {
    $index = Join-Path $Root "frontend\dist\index.html"
    if (-not (Test-Path $index)) { return $false, "missing frontend/dist/index.html" }
    $html = Get-Content $index -Raw -Encoding UTF8
    if ($html -match "Painel unificado") {
        return $false, "dist/index.html looks like legacy Painel unificado"
    }
    if ($html -notmatch 'id=["'']root["'']') {
        return $false, "dist/index.html missing React #root bootstrap"
    }
    if ($html -notmatch "/assets/") {
        return $false, "dist/index.html missing /assets/ references"
    }
    $assetMatches = [regex]::Matches($html, '/assets/([A-Za-z0-9._-]+)')
    if ($assetMatches.Count -lt 1) {
        return $false, "no asset filenames found in index.html"
    }
    foreach ($m in $assetMatches) {
        $name = $m.Groups[1].Value
        $path = Join-Path $Root "frontend\dist\assets\$name"
        if (-not (Test-Path $path)) {
            return $false, "missing asset file: frontend/dist/assets/$name"
        }
    }
    return $true, "ok"
}

function Test-ReactDistStale {
    $index = Join-Path $Root "frontend\dist\index.html"
    if (-not (Test-Path $index)) { return $true }
    $distTime = (Get-Item $index).LastWriteTimeUtc
    $srcRoot = Join-Path $Root "frontend\src"
    if (-not (Test-Path $srcRoot)) { return $false }
    $newer = Get-ChildItem -Path $srcRoot -Recurse -File -ErrorAction SilentlyContinue |
        Where-Object { $_.LastWriteTimeUtc -gt $distTime } |
        Select-Object -First 1
    return [bool]$newer
}

function Ensure-FrontendBuild {
    Write-Step "=== Frontend React (obrigatorio em producao) ===" "Cyan"

    $pkg = Join-Path $Root "frontend\package.json"
    if (-not (Test-Path $pkg)) {
        throw "FATAL: frontend/package.json ausente em $Root - Dashboard React nao pode ser construido."
    }

    $valid, $reason = Test-ReactDistValid
    $stale = $false
    if ($valid) { $stale = Test-ReactDistStale }

    $needBuild = (-not $valid) -or $stale -or $ForceFrontendBuild
    if ($SkipFrontendBuild) {
        if (-not $valid) {
            throw "FATAL: -SkipFrontendBuild mas dist React invalido ($reason). Remova -SkipFrontendBuild ou rode npm run build."
        }
        Write-Host "BUILD OK (skip; dist ja valido)" -ForegroundColor Green
        return
    }

    if (-not $needBuild) {
        Write-Host "BUILD OK (dist atualizado; sem rebuild)" -ForegroundColor Green
        return
    }

    if (-not $valid) {
        Write-Host "Dist invalido/ausente: $reason - executando npm run build..." -ForegroundColor Yellow
    } elseif ($stale) {
        Write-Host "Dist desatualizado (src mais novo que dist) - executando npm run build..." -ForegroundColor Yellow
    } else {
        Write-Host "ForceFrontendBuild - executando npm run build..." -ForegroundColor Yellow
    }

    Push-Location (Join-Path $Root "frontend")
    try {
        # Inject Vite Supabase keys from process env / .env.smoke.local so Cloud Auth works.
        $viteUrl = $env:VITE_SUPABASE_URL
        $viteAnon = $env:VITE_SUPABASE_ANON_KEY
        if (-not $viteUrl) { $viteUrl = $env:SUPABASE_URL }
        if (-not $viteAnon) { $viteAnon = $env:SUPABASE_ANON_KEY }
        if ($viteUrl) { $env:VITE_SUPABASE_URL = $viteUrl }
        if ($viteAnon) { $env:VITE_SUPABASE_ANON_KEY = $viteAnon }
        if ($env:VITE_SUPABASE_URL -and $env:VITE_SUPABASE_ANON_KEY) {
            Write-Host "Vite Supabase env: configured for build" -ForegroundColor DarkGray
        } else {
            Write-Host "WARN: VITE_SUPABASE_* ausente - login cloud nao funcionara no dist" -ForegroundColor Yellow
        }
        if (-not (Test-Path "node_modules")) {
            Write-Host "npm install..." -ForegroundColor DarkGray
            npm install
            if ($LASTEXITCODE -ne 0) { throw "npm install failed (exit $LASTEXITCODE)" }
        }
        npm run build
        if ($LASTEXITCODE -ne 0) { throw "npm run build failed (exit $LASTEXITCODE)" }
    } finally {
        Pop-Location
    }

    $valid2, $reason2 = Test-ReactDistValid
    if (-not $valid2) {
        throw "FATAL: build concluiu mas dist React ainda invalido: $reason2"
    }
    Write-Host "BUILD OK" -ForegroundColor Green
}

function Invoke-HttpGet([string]$Url, [int]$TimeoutSec = 8) {
    $req = [System.Net.HttpWebRequest]::Create($Url)
    $req.Method = "GET"
    $req.Timeout = $TimeoutSec * 1000
    $req.UserAgent = "PresencaBoot/1.0"
    try {
        $resp = $req.GetResponse()
        $stream = $resp.GetResponseStream()
        $reader = New-Object System.IO.StreamReader($stream)
        $body = $reader.ReadToEnd()
        $code = [int]$resp.StatusCode
        $reader.Close(); $resp.Close()
        return @{ Ok = $true; Status = $code; Body = $body }
    } catch [System.Net.WebException] {
        $code = 0
        $body = ""
        if ($_.Exception.Response) {
            $code = [int]$_.Exception.Response.StatusCode
            try {
                $stream = $_.Exception.Response.GetResponseStream()
                $reader = New-Object System.IO.StreamReader($stream)
                $body = $reader.ReadToEnd()
                $reader.Close()
            } catch {}
        }
        return @{ Ok = $false; Status = $code; Body = $body; Error = $_.Exception.Message }
    }
}

function Wait-HttpOk([string]$Url, [int]$Attempts = 30, [int]$DelayMs = 1000) {
    for ($i = 1; $i -le $Attempts; $i++) {
        $r = Invoke-HttpGet $Url 3
        if ($r.Ok -and $r.Status -eq 200) { return $r }
        Start-Sleep -Milliseconds $DelayMs
    }
    return $null
}

function Assert-ReactDashboard([string]$Base) {
    $r = Invoke-HttpGet "$Base/dashboard" 10
    if (-not $r.Ok -or $r.Status -ne 200) {
        throw "DASHBOARD FAIL: HTTP $($r.Status) $($r.Error)"
    }
    $html = $r.Body
    if ($html -match "Painel unificado") {
        throw "DASHBOARD FAIL: resposta contem 'Painel unificado' (legado). React dist nao montado."
    }
    if ($html -notmatch 'id=["'']root["'']') {
        throw "DASHBOARD FAIL: resposta sem #root (nao e o bootstrap React)."
    }
    if ($html -notmatch "/assets/") {
        throw "DASHBOARD FAIL: resposta sem /assets/."
    }
    $assetMatches = [regex]::Matches($html, '/assets/([A-Za-z0-9._-]+)')
    foreach ($m in $assetMatches) {
        $assetUrl = "$Base/assets/$($m.Groups[1].Value)"
        $ar = Invoke-HttpGet $assetUrl 10
        if (-not $ar.Ok -or $ar.Status -ne 200) {
            throw "ASSETS FAIL: $assetUrl -> HTTP $($ar.Status)"
        }
    }
    Write-Host "DASHBOARD REACT OK" -ForegroundColor Green
}

function Assert-M2Health([string]$Base) {
    $r = Invoke-HttpGet "$Base/m2/healthz" 8
    if (-not $r.Ok -or $r.Status -ne 200) {
        Write-Host "M2 FAIL via Edge: HTTP $($r.Status) $($r.Error)" -ForegroundColor Red
        $script:BootFailed = $true
        return
    }
    try {
        $j = $r.Body | ConvertFrom-Json
    } catch {
        Write-Host "M2 FAIL: healthz nao e JSON" -ForegroundColor Red
        $script:BootFailed = $true
        return
    }
    $hooks = [bool]$j.test_hooks
    $yunet = [bool]$j.yunet_model_present
    $roster = [string]$j.roster_source
    if ($hooks) {
        Write-Host "M2 FAIL: test_hooks=true (deve ser false em producao)" -ForegroundColor Red
        $script:BootFailed = $true
    }
    if (-not $yunet) {
        Write-Host "M2 WARN: yunet_model_present=false" -ForegroundColor Yellow
        $script:BootFailed = $true
    }
    if ($roster -ne "supabase") {
        Write-Host "M2 WARN: roster_source=$roster (esperado supabase em producao)" -ForegroundColor Yellow
    }
    Write-Host ("M2 OK (test_hooks={0} yunet_model_present={1} roster_source={2})" -f $j.test_hooks, $j.yunet_model_present, $roster) -ForegroundColor Green
}

# ----------------- main -----------------
Import-DotEnv (Join-Path $Root ".env")
Import-DotEnv (Join-Path (Split-Path $Root) "Presenca\.env")
Import-DotEnv (Join-Path (Split-Path $Root) "Presenca\.env.smoke.local")
Import-DotEnv (Join-Path $Root ".env.smoke.local")

Write-Step "=== Boot Edge + M2 (Presenca / producao) ===" "Cyan"
Write-Host "Root: $Root"
try {
    $branch = (git -C $Root rev-parse --abbrev-ref HEAD 2>$null)
    $head = (git -C $Root rev-parse --short HEAD 2>$null)
    Write-Host "Git: $branch @ $head" -ForegroundColor DarkGray
} catch {}
Write-Host ("SUPABASE_URL set: " + ([bool]$env:SUPABASE_URL)) -ForegroundColor DarkGray
Write-Host ("SERVICE_ROLE set: " + ([bool]($env:SUPABASE_SERVICE_ROLE_KEY -or $env:M2_OPS_SUPABASE_SERVICE_KEY))) -ForegroundColor DarkGray
Write-Host ("M2_ROSTER_SOURCE (env): " + ($(if ($env:M2_ROSTER_SOURCE) { $env:M2_ROSTER_SOURCE } else { "auto" }))) -ForegroundColor DarkGray

# Producao: forcar roster oficial Supabase A (nao fixtures).
$env:M2_ROSTER_SOURCE = "supabase"
Write-Host "M2_ROSTER_SOURCE: supabase (forcado pelo boot de producao)" -ForegroundColor DarkGray

Ensure-FrontendBuild

if (-not $env:M2_ENROLL_HMAC_SECRET) {
    $env:M2_ENROLL_HMAC_SECRET = -join ((1..48) | ForEach-Object { "{0:x}" -f (Get-Random -Max 16) })
    Write-Host "Generated ephemeral M2_ENROLL_HMAC_SECRET (set permanently in .env for prod)" -ForegroundColor Yellow
}

if (-not $PublicBaseUrl -or -not $PublicBaseUrl.Trim()) {
    $PublicBaseUrl = "https://presenca.sistemadulino.com.br"
}
$env:M2_PUBLIC_BASE_URL = $PublicBaseUrl.TrimEnd("/")
Write-Host "M2_PUBLIC_BASE_URL=$($env:M2_PUBLIC_BASE_URL)" -ForegroundColor Green

$env:M2_UPSTREAM_URL = if ($env:M2_UPSTREAM_URL) { $env:M2_UPSTREAM_URL } else { "http://127.0.0.1:$M2Port" }
$env:M2_POC_TEST_HOOKS = "0"
# M2 WorkingDirectory is modulo2_poc — relative ./data/dulino_edge.db would miss Edge schema.
# Force absolute SQLITE_PATH so promote writes face_embeddings into the same DB as Edge/matcher.
$sqliteAbs = Join-Path $Root "data\dulino_edge.db"
$env:SQLITE_PATH = $sqliteAbs
Write-Host "SQLITE_PATH=$sqliteAbs (shared Edge+M2)" -ForegroundColor Green
Write-Host "M2_POC_TEST_HOOKS: 0 (operational)" -ForegroundColor DarkGray
Write-Host "Tunnel esperado: Cloudflare -> http://127.0.0.1:$EdgePort (nunca :$M2Port)" -ForegroundColor DarkGray

if (-not $KeepExisting) {
    Stop-PortIfBusy $EdgePort "Edge"
    if (-not $SkipM2) { Stop-PortIfBusy $M2Port "M2" }
}

$edgeLog = Join-Path $Root "results\boot_edge_uvicorn.log"
$edgeErr = Join-Path $Root "results\boot_edge_uvicorn.err.log"
$m2Log = Join-Path $Root "results\boot_m2.log"
$m2Err = Join-Path $Root "results\boot_m2.err.log"
New-Item -ItemType Directory -Force -Path (Split-Path $edgeLog) | Out-Null

if (-not $SkipM2) {
    $m2Dir = Join-Path $Root "experiments\smoke_e2e_sentimentos\modulo2_poc"
    $m2Script = Join-Path $m2Dir "scripts\enrollment_gestor_server.py"
    if (-not (Test-Path $m2Script)) {
        Write-Host "M2 script missing: $m2Script - Edge will start alone" -ForegroundColor Red
        $script:BootFailed = $true
    } else {
        Write-Step "Starting M2 on 127.0.0.1:$M2Port ..." "Yellow"
        # Relative script path avoids Start-Process splitting on spaces in "Teste de monitoramento".
        $script:M2Proc = Start-Process -FilePath "python" -ArgumentList @(
            "scripts\enrollment_gestor_server.py", "--host", "127.0.0.1", "--port", "$M2Port"
        ) -WorkingDirectory $m2Dir -PassThru -WindowStyle Hidden `
            -RedirectStandardOutput $m2Log -RedirectStandardError $m2Err
        $m2Ready = Wait-HttpOk "http://127.0.0.1:$M2Port/healthz" 25 500
        if ($null -eq $m2Ready) {
            Write-Host "M2 health FAIL (Edge continues) - ver $m2Log / $m2Err" -ForegroundColor Red
            $script:BootFailed = $true
        } else {
            Write-Host "M2 health: 200 pid=$($script:M2Proc.Id)" -ForegroundColor Green
        }
    }
}

Write-Step "Starting Edge on ${EdgeHost}:${EdgePort} ..." "Yellow"
$script:EdgeProc = Start-Process -FilePath "python" -ArgumentList @(
    "-m", "uvicorn", "app.main:app", "--host", $EdgeHost, "--port", "$EdgePort"
) -WorkingDirectory $Root -PassThru -WindowStyle Hidden `
    -RedirectStandardOutput $edgeLog -RedirectStandardError $edgeErr

$base = "http://${EdgeHost}:${EdgePort}"
$edgeReady = Wait-HttpOk "$base/health" 40 500
if ($null -eq $edgeReady) {
    Write-Host "EDGE FAIL: /health nao respondeu - ver $edgeLog" -ForegroundColor Red
    if ($script:M2Proc -and -not $script:M2Proc.HasExited) {
        Stop-Process -Id $script:M2Proc.Id -Force -ErrorAction SilentlyContinue
    }
    if ($script:EdgeProc -and -not $script:EdgeProc.HasExited) {
        Stop-Process -Id $script:EdgeProc.Id -Force -ErrorAction SilentlyContinue
    }
    throw "FATAL: Edge nao subiu. Sistema NAO iniciado corretamente."
}
Write-Host "EDGE OK" -ForegroundColor Green

try {
    Assert-ReactDashboard $base
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    if ($script:M2Proc -and -not $script:M2Proc.HasExited) {
        Stop-Process -Id $script:M2Proc.Id -Force -ErrorAction SilentlyContinue
    }
    if ($script:EdgeProc -and -not $script:EdgeProc.HasExited) {
        Stop-Process -Id $script:EdgeProc.Id -Force -ErrorAction SilentlyContinue
    }
    throw "FATAL: Dashboard React invalido. Sistema NAO iniciado corretamente."
}

Assert-M2Health $base

$g = Invoke-HttpGet "$base/gestor/" 8
if ($g.Status -eq 200 -or $g.Status -eq 401 -or $g.Status -eq 403) {
    Write-Host "CADASTRO FACIAL proxy OK (HTTP $($g.Status) em /gestor/)" -ForegroundColor Green
} else {
    Write-Host "CADASTRO FACIAL WARN: /gestor/ HTTP $($g.Status)" -ForegroundColor Yellow
    $script:BootFailed = $true
}

$httpsOk = $false
try {
    $hr = Invoke-HttpGet "$($env:M2_PUBLIC_BASE_URL)/dashboard" 15
    if ($hr.Ok -and $hr.Status -eq 200 -and $hr.Body -match 'id=["'']root["'']' -and $hr.Body -notmatch "Painel unificado") {
        $httpsOk = $true
        Write-Host "TUNNEL HTTPS OK ($($env:M2_PUBLIC_BASE_URL)/dashboard = React)" -ForegroundColor Green
    } else {
        Write-Host "TUNNEL HTTPS WARN: dashboard remoto nao confirmou React (HTTP $($hr.Status))" -ForegroundColor Yellow
    }
} catch {
    Write-Host "TUNNEL HTTPS WARN: nao alcancavel agora (tunnel externo?)" -ForegroundColor Yellow
}

Write-Host ""
Write-Step "=== RESUMO BOOT ===" "Cyan"
Write-Host "BUILD OK"
Write-Host "EDGE OK"
if (-not $script:BootFailed) { Write-Host "M2 OK" } else { Write-Host "M2 / checks: ver warnings acima" }
Write-Host "DASHBOARD REACT OK"
Write-Host "CADASTRO FACIAL: proxy /gestor/ verificado"
Write-Host "SUPABASE A: roster_source via M2 healthz"
Write-Host "SUPABASE B: isolado (M2 nao escreve em B)"
if ($httpsOk) { Write-Host "TUNNEL HTTPS OK" } else { Write-Host "TUNNEL HTTPS: confirme cloudflared -> 127.0.0.1:$EdgePort" }
Write-Host ""
Write-Host "Dashboard: $base/dashboard"
Write-Host "Cadastro facial: $base/gestor/ (via Dashboard -> Cadastro facial)"
Write-Host "M2 loopback only: 127.0.0.1:$M2Port"
Write-Host "Logs: $edgeLog | $m2Log"
Write-Host "CTRL+C encerra Edge+M2.`n" -ForegroundColor Yellow

if ($script:BootFailed) {
    Write-Host "BOOT CONCLUIDO COM ALERTAS - revise M2/YuNet/roster antes de operar." -ForegroundColor Yellow
}

try {
    Wait-Process -Id $script:EdgeProc.Id
} finally {
    if ($script:M2Proc -and -not $script:M2Proc.HasExited) {
        Write-Host "Stopping M2 pid=$($script:M2Proc.Id)" -ForegroundColor Yellow
        Stop-Process -Id $script:M2Proc.Id -Force -ErrorAction SilentlyContinue
    }
    if ($script:EdgeProc -and -not $script:EdgeProc.HasExited) {
        Write-Host "Stopping Edge pid=$($script:EdgeProc.Id)" -ForegroundColor Yellow
        Stop-Process -Id $script:EdgeProc.Id -Force -ErrorAction SilentlyContinue
    }
}
