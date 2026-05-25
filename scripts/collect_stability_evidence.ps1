# Coleta evidências para testes de estabilidade (5 pessoas).
# Uso: .\scripts\collect_stability_evidence.ps1 [nome_cenario]
# Exemplo: .\scripts\collect_stability_evidence.ps1 "2_pessoas_cadastradas"
# Salva em: ./data/evidence_YYYYMMDD_HHMMSS_[nome].json (ou evidence_*.json)

$baseUrl = "http://127.0.0.1:8000"
$label = if ($args[0]) { $args[0] } else { "snapshot" }
$ts = Get-Date -Format "yyyyMMdd_HHmmss"
$outDir = "data"
$outFile = Join-Path $outDir "evidence_${ts}_${label}.json"

if (-not (Test-Path $outDir)) { New-Item -ItemType Directory -Path $outDir | Out-Null }

$evidence = @{
  timestamp_iso = (Get-Date -Format "o")
  scenario      = $label
  health        = $null
  cameras       = $null
  overlay_matches = $null
  events_checkin = $null
}

try {
  $evidence.health = (Invoke-WebRequest "$baseUrl/health" -UseBasicParsing).Content | ConvertFrom-Json
} catch { $evidence.health = "erro: $($_.Exception.Message)" }

try {
  $evidence.cameras = (Invoke-WebRequest "$baseUrl/cameras" -UseBasicParsing).Content | ConvertFrom-Json
} catch { $evidence.cameras = "erro: $($_.Exception.Message)" }

try {
  $evidence.overlay_matches = (Invoke-WebRequest "$baseUrl/debug/overlay_matches?camera_id=cam-web" -UseBasicParsing).Content | ConvertFrom-Json
} catch { $evidence.overlay_matches = "erro: $($_.Exception.Message)" }

try {
  $evidence.events_checkin = (Invoke-WebRequest "$baseUrl/events?event_type=attendance_checkin&limit=30" -UseBasicParsing).Content | ConvertFrom-Json
} catch { $evidence.events_checkin = "erro: $($_.Exception.Message)" }

$evidence | ConvertTo-Json -Depth 8 | Set-Content -Path $outFile -Encoding UTF8
Write-Host "Evidencia salva: $outFile"
