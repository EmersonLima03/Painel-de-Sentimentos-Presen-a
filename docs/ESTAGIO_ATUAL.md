# Estágio atual — Módulo Emoções e Dashboard (jul/2026)

Documento de checkpoint do branch `feat/painel-de-sentimentos`. Descreve **o que já funciona**, **o que está instável** e **o que ainda não entrou**.

> **Fechamento TRI:** ver [ENTREGA_TRI_EMOCOES_DASHBOARD.md](ENTREGA_TRI_EMOCOES_DASHBOARD.md) — perfil `config.tri.yaml`; emoção default **HSEmotion VGAF** (`hsemotion_vgaf`, worker ~2s) com **FER+** como fallback/rollback — [EMOTION_BACKEND_HSEMOTION_VGAF.md](EMOTION_BACKEND_HSEMOTION_VGAF.md).

---

## Resumo executivo

O **MVP do TRI (emoções aparentes + dashboard unificado)** está em fechamento funcional: pipeline edge (webcam/RTSP), FER+ ONNX via perfil documentado, dashboard React (Ao vivo + Relatório), atenção, clima e qualidade/inconclusivo.

**Não é produto final escolar completo:** LXP real, OTA, multi-escola, histórico semanal, contexto pedagógico (P1) e compliance LGPD completo ficam **pós-TRI**.

**Disclaimer permanente:** todas as métricas são **estimativas visuais observáveis** — não diagnóstico emocional, psicológico ou médico.

---

## O que está funcionando (validado em testes locais)

| Área | Status | Evidência |
|------|--------|-----------|
| Presença + identidade | OK | YuNet + FaceNet/FAISS, binding por track, reconfirmação |
| Pipeline person-first | OK | Detecção de pessoa → rosto → analytics por track |
| Dashboard unificado | OK | `/dashboard` (React): Ao vivo + Relatório com abas |
| Expressão no Ao vivo | OK (TRI) | Grade: “Expressão aparente”; clique → atenção/confiança/amostras |
| FER+ ONNX (fallback) | OK | `provider: fer_onnx` + `EXPRESSION_EMOTION_BACKEND=fer_onnx` para rollback |
| HSEmotion VGAF (default) | OK | `emotion_backend: hsemotion_vgaf` async ~2s — ver EMOTION_BACKEND_HSEMOTION_VGAF.md |
| WebSocket ao vivo | OK | `/api/v1/ws/live` + snapshot debug |
| Qualidade de observação | OK | Score % + texto “imagem adequada / parcialmente observável” |
| Atenção visual aparente | OK | Alta / baixa / **inconclusiva** quando rosto some |
| Expressão aparente | OK (perfil TRI) | FER+ ONNX; inconclusivo se baixa qualidade |
| Clima visual aparente | OK | Barras no Ao vivo e Relatório |
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

**Status (jul/2026):** calibrado — ver [CALIBRACAO_OCLUSAO_VS_CABECA_BAIXA.md](CALIBRACAO_OCLUSAO_VS_CABECA_BAIXA.md).

### Fantasmas de corpo + oclusão que some (reteste jul/2026)

| Problema | Correção |
|----------|----------|
| Vários boxes `temporarily_lost` / `pessoas: 4` com 1 pessoa | Overlay filtra `is_displayable_track`; tracks fracos expiram em 2s; conf mín. YOLO 0.40 |
| Mão no rosto 1+ min, alerta só ~10s e some | Não anular oclusão por landmarks se há punho; `clear_hold` 4s; evento oclusão hold ≥5s |

| Situação real | Comportamento |
|---------------|---------------|
| Lendo / escrevendo (cabeça baixa, rosto parcial) | `head_down_*` após limiar; **não** oclusão |
| Mão/objeto tampando rosto | `face_occlusion` → métricas **inconclusivas**; head_down **suprimido** |
| Corpo visível, rosto sumiu (sem punho) | Identidade por continuidade + **inconclusivo** (não inventa head_down) |
| Cabeça baixa prolongada real | Evento após `event_min_seconds` (8s) + revisão humana |

**Causa antiga:** proxy “rosto sumiu ⇒ cabeça baixa” + promoção a `persistent` em 2.5s.

**Correção:** visibility gate + prioridade oclusão; `allow_face_missing_proxy: false`.

---

## Branch e repositório

- **Branch de congelamento TRI (baseline ✅):** `tri/congelado-baseline-validado` — ver [`TRI_CONGELADO.md`](TRI_CONGELADO.md)
- **Branch de desenvolvimento anterior:** `feat/painel-de-sentimentos`
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
pytest tests/test_fer_onnx.py -m tri -q
pytest tests/test_occlusion_hysteresis.py tests/test_session_aggregator.py tests/test_live_session_dashboard.py -q
```

Perfil TRI (FER+ ONNX):

```powershell
$env:PRESENCA_CONFIG_OVERLAY = "config.tri.yaml"
```

---

## Fora de escopo deste checkpoint / pós-TRI

- Contexto pedagógico por aula (P1 — pausado)
- Integração LXP (chamada automática)
- Cloud Command / OTA
- Histórico semanal/mensal e multi-escola
- Alertas e-mail/webhook
- LGPD operacional completo (consentimento em produção)
- Ranking ou nota emocional individual
- DeepFace / HSEmotion como motor obrigatório da entrega TRI

---

## Critério de “pronto para piloto escolar”

- [ ] Separar estável: oclusão vs cabeça baixa vs leitura
- [ ] Calibrar tempos mínimos com vídeo real da sala
- [ ] Revisão humana validada em >80% dos eventos de alto risco
- [ ] Auth + consentimento mínimo
- [ ] Intelbras RTSP validado na escola piloto
