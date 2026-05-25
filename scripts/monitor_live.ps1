# Monitor ao vivo: faces_detected_last e last_presence_match (nome + confidence)
# Uso: .\scripts\monitor_live.ps1
# Requer: servidor rodando em http://127.0.0.1:8000
# Atualiza a cada 1 segundo. Nao quebra com last_presence_match null, objeto unico ou lista.

$baseUrl = "http://127.0.0.1:8000"
$intervalSec = 1

while ($true) {
  try {
    $camResp = Invoke-WebRequest "$baseUrl/cameras" -UseBasicParsing
    $camData = $camResp.Content | ConvertFrom-Json
    $healthResp = Invoke-WebRequest "$baseUrl/health" -UseBasicParsing
    $health = $healthResp.Content | ConvertFrom-Json

    $detector = $health.detector_backend
    $embedder = $health.embedder_backend
    $faiss = $health.faiss_enabled

    foreach ($cam in $camData.cameras) {
      $faces = $cam.faces_detected_last
      $raw = $cam.last_presence_match
      $list = if ($null -eq $raw) { @() } else { @($raw) }
      $valid = @($list | Where-Object { $_ -and $_.student_id })

      Write-Host "[$($cam.camera_id)] faces=$faces | detector=$detector embedder=$embedder faiss=$faiss"
      if ($valid.Count -gt 0) {
        foreach ($m in $valid) {
          Write-Host "  Reconhecido: $($m.student_id) confidence=$($m.confidence)"
        }
      } else {
        Write-Host "  Reconhecido: NINGUEM"
      }
    }
    Write-Host "---"
  } catch {
    Write-Host "Erro: $($_.Exception.Message)"
  }
  Start-Sleep -Seconds $intervalSec
}
