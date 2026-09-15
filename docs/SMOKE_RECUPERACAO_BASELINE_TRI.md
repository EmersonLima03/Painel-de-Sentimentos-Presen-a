# Smoke presencial — recuperação baseline TRI

**Sessão 2026-09-13/15:** smoke #1–#10 + E1/E2 + P1–P3/P5 ✅ LIVE. Aberto: **A**; I commit pendente; C ×3 opcional.  
Detalhe: [`CONGELAMENTO_LIVE_20260914.md`](CONGELAMENTO_LIVE_20260914.md) · números: [`VALORES_CONGELADOS_LIVE_20260914.md`](VALORES_CONGELADOS_LIVE_20260914.md) · takes 14–15/09: [`LIVE_E1_E2_P_20260915.md`](LIVE_E1_E2_P_20260915.md).

```powershell
cd Presenca
.\venv\Scripts\Activate.ps1
$env:PRESENCA_CONFIG_OVERLAY = "config.tri.yaml"
$env:RUNTIME_MODE = "rtsp"
$env:ENABLE_DEBUG_SNAPSHOT = "1"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

UI: http://127.0.0.1:8000/debug/vision

| # | Teste | Passa se | Status |
|---|--------|----------|--------|
| 1 | E4 peito 20s olhar câmera | near/visível; **sem** possible/probable; attn não baixa por phone | ✅ 2026-09-13 |
| 2 | E3 celular na cara 15s+ | magenta + in_hand → possible (≥5s) / probable (≥12s) | ✅ 2026-09-13/14 |
| 3 | D/P celular na mão 15s | magenta + ≠ not_detected contínuo | ✅ 2026-09-13 |
| 4 | C fone 20s | **sem** phone_in_hand / near persistente no headset | ✅ 2026-09-13 + reteste 14/09 |
| 5 | H baixo 10s → erguer 10s | **pessoas ≥1** com cabeça baixa; duração limpa ao erguer | ✅ 2026-09-14 (agente JPEG+JSON) |
| 6 | I perfil **ou** L mão no queixo | sem head_down inventado / sem oclusão persistente indevida | ✅ L 2026-09-14; I LIVE local (commit pendente) |
| 7 | J facepalm 8–15s | evento oclusão / rosto coberto; attn **não** Alta | ✅ 2026-09-14 (Emerson; K no mesmo take) |
| 8 | EX+ sorriso sustentado | predominantemente **positiva** (fer_onnx + smile_boost) | ✅ 2026-09-14 (Emerson; EX= neutra no mesmo LIVE) |
| 9 | F digitando / olhar teclado | **sem** possible/probable drowsiness | ✅ 2026-09-14 (patch `look_down_soft_pitch=0.14` + anti-sticky) |
| 10 | G olhos fechados frontais | possible→probable; ao abrir, aviso some rápido (~2s) | ✅ 2026-09-14 (reteste pós-patch F) |
| 11 | E1 celular na mesa | near/not_detected; **sem** in_hand / possible / probable | ✅ 2026-09-14/15 |
| 12 | E2 mão perto sem pegar | **sem** uso / interação | ✅ 2026-09-14 |
| 13 | P1 celular na orelha | detecção + uso/probable; **não** reject ear-only | ✅ 2026-09-14 |
| 14 | P2 celular vertical na mão | detecção + in_hand / probable | ✅ 2026-09-14 |
| 15 | P3 celular no colo | detecção / near (não FN) | ✅ 2026-09-14 |
| 16 | P5 mesa → pegar | idle → in_hand → possible/probable | ✅ 2026-09-15 |

Marque aqui após validar. MP4/Live Monitor só depois destes ✅.
