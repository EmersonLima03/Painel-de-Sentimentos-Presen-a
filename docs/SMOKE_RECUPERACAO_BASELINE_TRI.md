# Smoke presencial — recuperação baseline TRI

**Sessão 2026-09-13/14:** #1–#5 e #7–#8 ✅ LIVE. #6 (I/L) ainda aberto.  
Detalhe: [`CONGELAMENTO_LIVE_20260914.md`](CONGELAMENTO_LIVE_20260914.md) · números: [`VALORES_CONGELADOS_LIVE_20260914.md`](VALORES_CONGELADOS_LIVE_20260914.md).

```powershell
cd Presenca
.\venv\Scripts\Activate.ps1
$env:PRESENCA_CONFIG_OVERLAY = "config.tri.yaml"
$env:RUNTIME_MODE = "rtsp"
$env:ENABLE_DEBUG_SNAPSHOT = "1"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

UI: http://127.0.0.1:8000/debug/vision

| # | Teste | Passa se |
|---|--------|----------|
| 1 | E4 peito 20s olhar câmera | near/visível; **sem** possible/probable; attn não baixa por phone | ✅ 2026-09-13 |
| 2 | E3 celular na cara 15s+ | magenta + in_hand → possible (≥5s) / probable (≥12s) | ✅ 2026-09-13/14 |
| 3 | D/P celular na mão 15s | magenta + ≠ not_detected contínuo | ✅ 2026-09-13 |
| 4 | C fone 20s | **sem** phone_in_hand / near persistente no headset | ✅ 2026-09-13 (1 take) |
| 5 | H baixo 10s → erguer 10s | **pessoas ≥1** com cabeça baixa; duração limpa ao erguer | ✅ 2026-09-14 (agente JPEG+JSON) |
| 6 | I perfil **ou** L mão no queixo | sem head_down inventado / sem oclusão persistente indevida | |
| 7 | J facepalm 8–15s | evento oclusão / rosto coberto; attn **não** Alta | ✅ 2026-09-14 (Emerson; K no mesmo take) |
| 8 | EX+ sorriso sustentado | predominantemente **positiva** (fer_onnx + smile_boost) | ✅ 2026-09-14 (Emerson; EX= neutra no mesmo LIVE) |

Marque aqui após validar. MP4/Live Monitor só depois destes ✅.
