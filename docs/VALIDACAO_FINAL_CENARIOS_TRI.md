# Validação final — cenários controlados do TRI (visão)

**Objetivo de qualidade:** 100% de aprovação no conjunto controlado abaixo, com estados conservadores — **não** precisão universal.

**Baseline Git:** HEAD `66e3277` + working tree com entregas TRI/dashboard (não limpo). Checkpoint lógico: validação controlada pós-prints webcam 2026-07-29.

**Disclaimer:** estimativas visuais; sem diagnóstico.

---

## Como capturar payload (Fase 1)

Com servidor TRI:

```powershell
$env:PRESENCA_CONFIG_OVERLAY = "config.tri.yaml"
$env:RUNTIME_MODE = "rtsp"
$env:ENABLE_DEBUG_SNAPSHOT = "1"
```

- Debug UI: `/debug/vision`
- Snapshot: `GET /api/v1/live/debug-snapshot` (localhost)
- Campos úteis: `phones`, `rejected_detections`, tracks → `phone`, `face_occlusion`, `head`, `drowsiness`, `expression`, `observation_quality`, EAR/pitch

Não persistir frames sem consentimento. Vídeos locais: `data/validation/tri/` (gitignored).

---

## Matriz de cenários

| ID | Cenário | Duração | Resultado esperado | Resultado proibido | Antes (webcam 2026-07-29) | Depois | Aprovado |
|----|---------|---------|--------------------|--------------------|---------------------------|--------|----------|
| A | Garrafa transparente na mão | 20s | not_detected / rejeitado | phone_in_hand, possible/probable | — | | |
| B | Copo térmico / garrafa escura | 20s | idem A | interação celular | **FP:** bbox magenta + “Celular na mão” | | |
| C | Fone / região orelha | 20s | não celular | phone_near / eventos | **FP:** bbox no fone + “Celular próximo” | | |
| D | Celular real na mão | 2/5/12/15s | progressão temporal | confirmed_* auto | preservar | | |
| E1 | Celular na mesa parado | 30s | visible/near ok; sem in_hand/interação | uso | | | |
| E2 | Mão perto sem pegar | 10s | sem possible/probable | interação | | | |
| E3 | Pegar e usar | 15s+ | in_hand → possible/probable | confirmed | | | |
| F | Digitando / olhar teclado | 60s | head_down / inconclusivo ok | possible/probable drowsiness | risco EAR↓ | | |
| G | Olhos fechados frontais | limiares 6s/30s | possible/probable nos limiares | evento &lt;2.5s | | | |
| H | Cabeça baixa parcial | &lt;8s / ≥8s | short / persistent descritivo | sono automático | misto: às vezes “Postura inconclusiva” | | |
| I | Cabeça fora / rosto sumiu | 20s | face_not_observable; sem inventar head_down facial | sono | OK parcial (continuidade) | | |
| J | Uma mão no rosto | &lt;8 / &gt;8 / 20s | oclusão + inconclusivos | sono; head_down auto | **OK** oclusão persistente | | |
| K | Duas mãos no rosto | 20s ×3 | oclusão persistente | sono | | | |
| L | Mão perto sem cobrir | 20s | no máx. oclusão breve | persistente; celular FP | | | |

### Achados baseline (prints)

1. **B** — térmico na mão → YOLO celular + `phone_in_hand` (heurística).  
2. **C** — fone → bbox + `phone_near_person`.  
3. **H** — cabeça baixa clara → às vezes `Postura inconclusiva` (pose/landmarks insuficientes).  
4. **J** — mão no rosto → oclusão + expressão/atenção/sono inconclusivos + continuidade **OK**.  
5. **I/H** — cabeça apoiada → às vezes `Cabeça baixa (breve)` **OK**.

### Correções aplicadas (código — 2026-07-29)

| Problema | Correção mínima | Thresholds globais YOLO? |
|----------|-----------------|---------------------------|
| Fone→in_hand | Removido `near_face` sozinho como `in_hand`; exige punho | Não |
| Térmico/garrafa | Rejeição `_context_reject_reason` (altura relativa / lateral) | Não (conf 0.42 mantido) |
| Fone YOLO | `ear_region_implausible` | Não |
| Mesa | `in_hand` lower-body não abaixo de 90% da altura da pessoa | Não |
| Digitação→sono | Não acumular EAR fechado com `head_down`/pitch alto | Limiares 6s/30s intactos |

**Depois (automático):** testes de regressão A/B/C/E/F verdes.  
**Depois (manual):** reexecutar B, C, F, H, J no `/debug/vision` e marcar a coluna Aprovado.

### Causas candidatas (código)

| Problema | Causa provável | Arquivo |
|----------|----------------|---------|
| Fone→celular | Heurística `_phone_near_face_region` promove `in_hand` sem punho; YOLO class 67 na orelha | `person_phone.py`, `phone_yolo.py` |
| Térmico→celular | Aspect ratio passa se bbox não for bem alta; torso pass | `phone_yolo._bbox_plausible` |
| Digitação→sono | EAR baixo com pitch/head_down ainda incrementa `eyes_closed_accum` | `analytics_track.py` |
| Cabeça→inconclusiva | Sem landmarks confiáveis e sem geometria corporal suficiente | `body_pose.py`, arbitragem |

**Presença / IdentityBinding / `/debug/vision` layout:** não alterar nesta etapa.

---

## Thresholds vigentes (não alterar sem teste de fronteira)

| Chave | Valor tipico |
|-------|----------------|
| `phone_yolo_conf_threshold` | 0.42 |
| `phone_yolo_max_height_width_ratio` | 2.7 |
| `phone_possible_after` / `probable` | 5s / 12s |
| `drowsiness_possible` / `probable` | 6s / 30s |
| `head_down_event_min_seconds` | 8s |
| `face_occlusion_persistent_seconds` | 5s |

---

## Fixture estruturada

Ver `tests/fixtures/tri_validation_scenarios.json`.

## Testes de regressão

- `tests/test_phone_false_positive_regression.py`
- `tests/test_phone_table_interaction.py`
- `tests/test_typing_not_drowsiness.py`
- `tests/test_head_down_visibility_gate.py` (amplia oclusão/head)
- existentes: `test_phone_filters.py`, `test_occlusion_hysteresis.py`

---

## Limitações restantes

Webcam real ≠ corpus rotulado; YOLO COCO class 67 confunde objetos; pose lite falha em ângulos extremos. Meta = cenários controlados + regras conservadoras.
