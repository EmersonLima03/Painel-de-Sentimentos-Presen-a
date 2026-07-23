# Monitor de presença - script robusto para last_presence_match (lista ou objeto único)
# Uso: .\scripts\monitor_presence.ps1

while ($true) {
  try {
    $resp = Invoke-WebRequest "http://127.0.0.1:8000/cameras" -UseBasicParsing
    $data = $resp.Content | ConvertFrom-Json
    $cam = $data.cameras[0]

    Write-Host "Faces detectadas:" $cam.faces_detected_last
    # @() força array (PowerShell deserializa [objeto] como objeto único)
    $raw = $cam.last_presence_match
    $list = if ($null -eq $raw) { @() } else { @($raw) }
    $valid = @($list | Where-Object { $_ -and $_.student_id })
    if ($valid.Count -gt 0) {
      foreach ($m in $valid) {
        Write-Host "Reconhecido:" $m.student_id "Confianca:" $m.confidence
      }
    } else {
      Write-Host "Reconhecido: NINGUEM"
    }
    Write-Host "-----------------------------"
  } catch {
    Write-Host "Erro:" $_.Exception.Message
  }
  Start-Sleep -Seconds 2
}
