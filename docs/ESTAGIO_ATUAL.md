# Estágio atual — Módulo Emoções e Dashboard (jul/2026)

Documento de checkpoint do branch `feat/painel-de-sentimentos`. Descreve **o que já funciona**, **o que está instável** e **o que ainda não entrou**.

---

## Resumo executivo

Estamos no **Módulo de Emoções e Dashboard (~40% do MVP maior)**, com pipeline edge rodando em **webcam USB / RTSP**, identidade por rosto, dashboard React unificado e sinais comportamentais agregados.

**Não é produto final:** LXP real, OTA, alertas push e compliance LGPD completo ainda não estão fechados.

**Disclaimer permanente:** todas as métricas são **estimativas visuais observáveis** — não diagnóstico emocional, psicológico ou médico.

---

## O que está funcionando (validado em testes locais)

| Área | Status | Evidência |
|------|--------|-----------|
| Presença + identidade | OK | YuNet + FaceNet/FAISS, binding por track, reconfirmação |
| Pipeline person-first | OK | Detecção de pessoa → rosto → analytics por track |
| Dashboard unificado | OK | `/dashboard` (React): câmera, KPIs, pessoa, timeline |
| WebSocket ao vivo | OK | `/api/v1/ws/live` + snapshot debug |
| Qualidade de observação | OK | Score % + texto “imagem adequada / parcialmente observável” |
| Atenção visual aparente | OK | Alta / baixa / **inconclusiva** quando rosto some |
| Expressão aparente | Parcial | Providers experimentais (FER+, HSEmotion); muitas vezes **inconclusivo** |
| Sonolência | Parcial | PERCLOS/landmarks quando rosto visível; **inconclusivo** se ocluído |
| Celular | Parcial | YOLO + filtros; redução de falso positivo em progresso |
| Sessão + presença periódica | OK | `class_sessions`, sightings na sessão |
| Sync offline-first | OK | Fila SQLite → Supabase (quando configurado) |
| Webcam USB auto | OK | `rtsp_url: "auto"` escolhe maior resolução (evita notebook) |

---

## Resultado visual atual (suas capturas)

### Cenário A — rosto visível, fones, expressão neutra/sorriso leve

- Qualidade ~94%, atenção **alta**, expressão ainda pode cair em **inconclusivo** (providers conservadores).
- Identidade confirmada (~93%).
- Processamento ~37–61 ms.

### Cenário B — mão na frente do rosto / cabeça baixa

- Qualidade cai (~56%), atenção **inconclusiva** (correto).
- Evento: **“Cabeça baixa prolongada”** após ~1 s (limiar curto em tuning).
- Identidade **mantida por continuidade** do corpo (~41 s sem rosto) — esperado.
- Sonolência e expressão: **inconclusivos** (correto quando rosto ocluído).

---

## Lacuna principal (instabilidade conhecida)

### Cabeça baixa vs rosto ocluído (mão/objeto na frente)

**Problema:** o sistema ainda **não separa com confiança estável**:

| Situação real | Comportamento desejado | Comportamento atual |
|---------------|------------------------|---------------------|
| Lendo / escrevendo (cabeça baixa, rosto parcialmente visível) | `head_down_short` / leitura — **não** alerta | Pode virar “cabeça baixa prolongada” cedo |
| Mão/objeto tampando rosto | `face_occlusion` → métricas **inconclusivas** | Parcialmente OK, mas pode misturar com head_down |
| Corpo visível, rosto sumiu | Identidade por continuidade + inconclusivo | OK |
| Cabeça baixa prolongada real (sono/leitura longa) | Evento após N segundos + revisão humana | Limiar de tempo ainda sendo calibrado |

**Causa técnica:** head pose + oclusão de pulso/mão usam sinais independentes com histerese curta; quando landmarks falham, o fallback não distingue bem “pitch alto” de “face mesh indisponível”.

**Próximo passo de engenharia (não bloqueia este checkpoint):**

1. Exigir landmarks faciais mínimos antes de emitir `head_down_persistent`.
2. Priorizar `face_occlusion` sobre `head_down` quando pulso/mão próximo ao rosto.
3. Aumentar `head_down_event_min_seconds` (config) após corpus de testes.
4. Ground truth com professor marcando: leitura / mão na face / sono simulado.

---

## Branch e repositório

- **Branch:** `feat/painel-de-sentimentos`
- **Remote:** https://github.com/EmersonLima03/Painel-de-Sentimentos-Presen-a
- **Base edge:** Presença (YuNet, FAISS, SQLite, sync)

---

## Como reproduzir este estágio

```powershell
cd Presenca
.\venv\Scripts\Activate.ps1
$env:RUNTIME_MODE = "rtsp"
$env:ENABLE_DEBUG_SNAPSHOT = "1"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

- Dashboard: http://127.0.0.1:8000/dashboard  
- Debug visão: http://127.0.0.1:8000/debug/vision  

**Webcam:** `config.yaml` → `cam-web` com `rtsp_url: "auto"` (USB 1080p).

---

## Testes automatizados incluídos neste checkpoint

```powershell
pytest tests/test_occlusion_hysteresis.py tests/test_session_aggregator.py tests/test_live_session_dashboard.py -q
```

---

## Fora de escopo deste checkpoint

- Integração LXP (chamada automática)
- Cloud Command / OTA
- Alertas e-mail/webhook
- LGPD operacional completo (consentimento em produção)
- Ranking ou nota emocional individual
- DeepFace como motor de produção

---

## Critério de “pronto para piloto escolar”

- [ ] Separar estável: oclusão vs cabeça baixa vs leitura
- [ ] Calibrar tempos mínimos com vídeo real da sala
- [ ] Revisão humana validada em >80% dos eventos de alto risco
- [ ] Auth + consentimento mínimo
- [ ] Intelbras RTSP validado na escola piloto
