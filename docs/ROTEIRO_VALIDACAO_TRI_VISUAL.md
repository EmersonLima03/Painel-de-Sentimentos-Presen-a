# Roteiro visual — validação TRI (cenários pendentes)

**Branch:** `tri/congelado-baseline-validado`  
**Perfil obrigatório:** `config.tri.yaml` + `RUNTIME_MODE=rtsp`  
**UI:** `/debug/vision` (validação) · `/dashboard` (relatório pedagógico)

---

## Antes de começar (5 min)

```powershell
cd "C:\Users\dulin\OneDrive\Documentos\Teste de monitoramento\Presenca"
git checkout tri/congelado-baseline-validado
$env:PRESENCA_CONFIG_OVERLAY = "config.tri.yaml"
$env:RUNTIME_MODE = "rtsp"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Abra: `http://127.0.0.1:8000/debug/vision`

### Smoke — não pule (cenários ✅)

| ID | Ação rápida | ✅ se… |
|----|-------------|--------|
| B | Garrafa escura na mão 10s | Sem “Celular na mão” |
| D | Celular na mão 5s | `phone_in_hand` ou near |
| G | Olhos fechados 8s | `possible`/`probable` drowsiness |
| H | Cabeça baixa 10s | `head_down_*` + card com duração |
| J | 1 mão no rosto 10s | Oclusão persistente |
| ATTN | Celular+olhos fechados 15s | Baixa atenção derivada |

**Se qualquer smoke falhar → pare e corrija regressão antes de continuar.**

---

## Legenda visual (painel debug)

```
┌─────────────────────────────────────────────────────────────┐
│  TRACK / PESSOA                                             │
├─────────────────────────────────────────────────────────────┤
│  phone.state          → not_detected | visible | in_hand |  │
│                         possible | probable                 │
│  rejected_detections  → garrafa/fone rejeitados (motivo)    │
│  head.state           → head_down_* | head_turned |        │
│                         pose_inconclusive                   │
│  face_occlusion       → none | possible | persistent        │
│  drowsiness.state     → none | possible | probable | inc.   │
│  eyes_observable      → true/false (gate sono F)            │
│  expression.smoothed  → neutral | positive | negative       │
└─────────────────────────────────────────────────────────────┘
```

| Sinal no debug | Cor mental | Significado |
|----------------|------------|-------------|
| `reject_reason: bottle_like_*` | 🟢 | Garrafa rejeitada (A/B) |
| `reject_reason: ear_region_implausible` | 🟢 | Fone rejeitado (C) |
| `phone_in_hand` + punho | 🟢 | Uso real (D/E3/P) |
| `near_without_wrist` | 🟢 | Mesa/mão perto sem uso (E1/E2) |
| `head_turned` (perfil observável) | 🟢 | Cenário I ok |
| `pose_inconclusive` (geom insuficiente / face sumiu) | 🟢 | Cenário I ok |
| `head_down_persistent` só por perfil | 🔴 | I reprovado |
| `possible`/`probable` drowsiness só por perfil | 🔴 | I reprovado |
| `persistent` oclusão só por mão no queixo (face ok) | 🔴 | L reprovado (near≠oclusão) |
| `probable_drowsiness` digitando | 🔴 | F reprovado |
| `predominantly_negative` cara séria | 🔴 | EX− FP |

---

## Ordem da sessão (~1h30)

```
SMOKE ✅ → EX− → C×3 → I → F → E1→E2→E3 → P1–P5 → A → L×3
```

---

## EX− — Expressão negativa (~10 min)

**Objetivo:** bico/tristeza exagerada 8–10s → negativa; cara séria → neutra.

### Passo 1 — Cara séria (controle negativo)

```
  Você                    Debug esperado
 ┌──────┐                 expression → predominantly_neutral
 │  😐  │  10s            ou inconclusive
 │      │                 NÃO predominantly_negative
 └──────┘
```

| Campo | Esperado | Proibido |
|-------|----------|----------|
| `expression.smoothed` | `neutral` / `inconclusive` | `negative` |
| Dashboard tempos | neutra sobe pouco | raiva/tristeza >5s |

### Passo 2 — Negativa exagerada

```
  Você                    Debug esperado
 ┌──────┐                 expression → predominantly_negative
 │  ☹️  │  8–10s          conf ≥ 0.42, ≥2 amostras
 │ bico │                 frown_boost ativo
 └──────┘
```

| Campo | Esperado | Proibido |
|-------|----------|----------|
| `expression.smoothed` | `predominantly_negative` | 0s no relatório |
| Sorriso rápido | volta positiva/neutra | flicker inconclusivo longo |

**Registro:** copiar template em `VALIDACAO_FINAL_CENARIOS_TRI.md`

---

## C ×3 — Fone na orelha (~15 min)

**Objetivo:** fone grande ≠ celular (3 repetições).

```
     ┌─fone──┐
     │       │
  ┌──┴───┐   │
  │ rosto│   │
  └──────┘   │
```

| Campo | Esperado | Proibido |
|-------|----------|----------|
| `rejected_detections` | `ear_region_implausible` OU sem detecção | `phone_in_hand` |
| `interaction_level` | `not_detected` / `phone_visible` | `possible` / `probable` |
| Evento dashboard | nenhum de celular | “Celular na mão” |

**Rep 1/2/3:** anotar iluminação e lado da orelha.

---

## I — Perfil / lateral / rosto sumiu (~5 min) ✅ FECHADO 2026-09-09

**Objetivo:** perfil/lateral verdadeiro → `head_turned` **ou** `pose_inconclusive`; sem inventar cabeça baixa nem sono.

```
  Antes          Durante 20s           Debug
 ┌──────┐       ┌──────┐ (perfil)     head → head_turned | pose_inconclusive
 │ 😊   │  →    │ 👤   │               occ → none (sem punho)
 └──────┘       └──────┘               drowsiness → none | inconclusive
```

| Campo | Esperado | Proibido |
|-------|----------|----------|
| `head.state` | `head_turned` **ou** `pose_inconclusive` | `head_down_persistent` (ou short promovido) só por perfil |
| `drowsiness` | `none` / `inconclusive` | `possible` / `probable` só por perfil |
| `face_occlusion` | `none` ou breve | persistente 20s sem mão |
| Reasons (exemplos) | `lateral_nose_offset`; `face_missing_lateral_or_out_of_frame`; `no_pose_landmarks` | look-down geom sem evidência |

**Semântica:** `head_turned` = lateralidade observável; `pose_inconclusive` = geometria insuficiente para afirmar pose com segurança. Ambos válidos.

**Ação:** vire a cabeça para fora do enquadramento ou de lado, **sem** olhar para baixo.

---

## F — Digitando / olhar teclado (~5 min)

**Objetivo:** cabeça baixa ok; sono pausado.

```
       tela
  ┌─────────┐
  │         │
  └─────────┘
      ↓ olhar
  ┌──────┐
  │ 😊↓  │  60s
  └──────┘
```

| Campo | Esperado | Proibido |
|-------|----------|----------|
| `head.state` | `head_down_*` (opcional) | — |
| `eyes_observable` | `true` (olhos abertos) | — |
| `drowsiness.state` | `none` / `inconclusive` | `possible` / `probable` |

---

## E1 → E2 → E3 — Mesa e uso (~15 min)

### E1 — Celular parado na mesa (30s)

```
  ┌──────┐
  │ você │
  └──────┘
      📱  ← mesa, mãos longe
```

| Esperado | Proibido |
|----------|----------|
| `phone_visible` ou `near` | `phone_in_hand` |
| Sem `possible`/`probable` | evento de uso |

### E2 — Mão perto sem pegar (10s)

```
  ┌──────┐
  │  ✋  │─── perto ─── 📱
  └──────┘
```

| Esperado | Proibido |
|----------|----------|
| `near_without_wrist_not_interaction` | `possible`/`probable` |

### E3 — Pegar e usar (15s+)

```
  t=0     t=5s        t=12s+
  📱      ✋📱         ✋📱 possible → probable
 mesa    in_hand
```

| Tempo | Esperado |
|-------|----------|
| 0–3s | `in_hand` após pegar |
| ≥5s | `possible_phone_interaction` |
| ≥12s | `probable_phone_interaction` |

**Proibido:** card “não indica uso” com o aparelho na cara. Qualquer ajuste de peito (E4) **obrigatório** retestar este passo.

### E4 — Celular no peito, olhar à câmera (20s)

```
  olhar  →  câmera
  📱 no peito (não na cara)
```

| Esperado | Proibido |
|----------|----------|
| bbox magenta ok; `phone_near_person` / visível | `possible` / `probable` |
| atenção **não** baixa por `derived_from_phone` | “Provável interação” só porque está no peito |

**Par E3+E4:** sempre os dois no mesmo restart. Não validar peito isolado.

---

## P1–P5 — Controles positivos (~15 min)

| ID | Pose | ✅ Passa se |
|----|------|-------------|
| P1 | Celular na orelha + punho | `in_hand`, **não** rejeitado por `ear_region` |
| P2 | Celular vertical na mão | detectado + `in_hand` |
| P3 | Celular no colo | `in_hand` com punho |
| P4 | Mão cobrindo parte do celular | ainda `in_hand` / near |
| P5 | Mesa → pegar | E1 idle → E3 após pegar |

**Ordem:** rode **depois** de C e A — valida que filtros não mataram celular real.

---

## A — Garrafa transparente (~5 min)

```
  ┌──────┐
  │ ✋🧴 │  20s (transparente)
  └──────┘
```

| Campo | Esperado | Proibido |
|-------|----------|----------|
| `rejected_detections` | `bottle_like_wide_handheld` ou `bottle_like_relative_height` | — |
| `phone_in_hand` | false | true |
| Eventos | nenhum de celular | uso de celular |

---

## L — Mão próxima / apoio no rosto sem bloquear (~15 min)

**Contrato (fechado 2026-09-09):** `hand_near_face` é sinal **observacional opcional**.  
`face_occlusion` só quando a mão **prejudica** observabilidade facial. Proximidade ≠ oclusão.

```
  ┌──────┐
  │ ✋😊 │  mão no queixo/bochecha — olhos/boca/landmarks utilizáveis
  └──────┘
```

Exemplos L: mão no queixo; mão na bochecha; toque breve no rosto (sem tapar olhos/nariz/boca).

| Campo | Esperado | Proibido |
|-------|----------|----------|
| `face_occlusion` | **`none`** (válido e preferido se face observável) | `persistent_possible_face_occlusion` só por proximidade |
| `hands.state` | `not_near_face` **ou** `hand_near_face` (opcional) | exigir `hand_near_face` como critério de aprovação |
| `head.state` | forward / inconclusive | `head_down` inventado |
| drowsiness / attention | normais se face observável | sono/atenção inventados por mão no queixo |

**Oclusão real** (cenários J / `L_uma_mao_cobrindo` / K — fora do critério “L parcial”):

| Estado | Quando |
|--------|--------|
| `possible_face_occlusion_by_hand` | mão cobre regiões relevantes / reduz observabilidade |
| `persistent_possible_face_occlusion` | oclusão efetiva sustentada ~**5 s** |
| recuperação | mão sai e rosto volta observável → `none` |

**Reps L (sem cobrir):** queixo, bochecha, testa (olhos/boca visíveis).  
Evidência: `L_mao_parcial_rosto.mp4` — sem oclusão com face utilizável = **correto**.

---

## Template de registro (copiar por teste)

```
ID/rep: ___
Commit: $(git rev-parse --short HEAD)
Iluminação: ___
Duração: ___s

┌ Esperado ─────────────────┐  ┌ Obtido ────────────────────┐
│                           │  │                            │
└───────────────────────────┘  └────────────────────────────┘

phone.state: ___
rejected: ___
head: ___
occ: ___
drowsiness: ___
expression: ___

APROVADO / REPROVADO: ___
```

---

## Após a sessão

1. Marcar matriz em `docs/VALIDACAO_FINAL_CENARIOS_TRI.md`
2. Aprovados novos → `docs/BASELINE_MANUAL_APROVADO_TRI.md`
3. Rodar gate técnico:

```powershell
pytest tests/test_tri_pending_scenarios.py tests/test_phone_false_positive_regression.py tests/test_phone_positive_controls.py tests/test_phone_table_interaction.py tests/test_head_down_visibility_gate.py tests/test_expression_negative_contract.py -q
pytest tests/test_fer_onnx.py tests/test_tri_config_overlay.py -m tri -q
cd frontend; npm run typecheck; npm run build
```

4. Se 100% manual + gate → tag `tri-emocoes-dashboard-v1.0`

---

## Árvore de decisão rápida (reprovou?)

```
Reprovou?
├── A (garrafa transparente) → phone_yolo bottle_like_wide
├── C (fone) → ear_region_implausible limiares
├── E1/E2 → person_phone mesa / punho
├── E3/P5 → timers phone possible/probable
├── F (digitar) → eyes_observable / drowsiness gate
├── I (perfil) → head_turned|pose_inconclusive OK; proibido head_down/sono só por perfil
├── L (mão perto sem cobrir) → oclusão deve ser `none`; near opcional; não persistir por proximidade
├── EX− → frown_boost + minimum_confidence_negative
└── Quebrou ✅ smoke → PARAR, reverter, retestar smoke
```
