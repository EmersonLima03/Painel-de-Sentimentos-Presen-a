# Valores congelados LIVE — 14/09/2026

**Commit de código do LIVE de celular:** `eb6590e`  
**Este documento:** contrato + números do perfil TRI no momento em que H / J / K / EX+ / EX= foram reaprovados na webcam.

**Não alterar estes números sem reteste presencial** dos ✅ afetados.

Fonte: `config.tri.yaml` (overlay obrigatório). VGAF **não** é TRI.

---

## Como subir (igual ao take aprovado)

```powershell
$env:PRESENCA_CONFIG_OVERLAY = "config.tri.yaml"
$env:RUNTIME_MODE = "rtsp"
$env:ENABLE_DEBUG_SNAPSHOT = "1"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

UI: http://127.0.0.1:8000/debug/vision

---

## Aprovado LIVE 13–14/09 (não regressar)

| ID | Quem observou | Contrato |
|----|---------------|----------|
| E4 / E3 / D / C / E-lat | Agente + Emerson (JPEG+JSON) | ver tabela celular em [`CONGELAMENTO_LIVE_20260914.md`](CONGELAMENTO_LIVE_20260914.md) |
| **H** | Agente (JPEG+JSON) + Emerson | ereto `head_forward` → baixo `head_down_persistent` contínuo → erguer limpa; sono inconclusivo; **não** oclusão J |
| **J** | Emerson (bonus no mesmo LIVE) | 1 mão no rosto → evento oclusão / rosto coberto |
| **K** | Emerson (bonus no mesmo LIVE) | 2 mãos no rosto → evento oclusão contínuo |
| **EX+ / EX=** | Emerson (bonus no mesmo LIVE) | sorriso → positiva; neutro → neutra (`fer_onnx` + `smile_boost`) |

Take H (agente): ereto `head_forward` attn alta; baixo `head_down_persistent` ~9 s → ~20 s no overlay; ao erguer `head_forward` imediato, eventos ativos vazios. Episódio fechou em ~63 s (tempo real do take + `inconclusive_hold` 12 s).

Ainda aberto neste smoke: **I** (perfil) e **L** (mão no queixo sem cobrir).

---

## Números TRAVADOS (`config.tri.yaml`)

### Expressão (EX+ / EX=)

| Chave | Valor |
|-------|--------|
| `expression.emotion_backend` | `fer_onnx` |
| `expression.provider` | `fer_onnx` |
| `expression.fallback_chain` | `[fer_onnx]` |
| `expression.smile_boost_enabled` | `true` |
| `expression.frown_boost_enabled` | `true` |
| `expression.interval_seconds` | `1.0` |
| `expression.window_seconds` | `5` |
| `expression.minimum_samples` | `3` |
| `expression.minimum_confidence` | `0.45` |
| `expression.minimum_confidence_positive` | `0.50` |
| `expression.minimum_confidence_negative` | `0.42` |
| `expression.minimum_negative_samples` | `2` |
| `expression.negative_min_seconds` | `6.0` |
| `expression.minimum_observation_quality` | `0.55` |

**Proibido:** `emotion_backend: hsemotion_vgaf` no overlay TRI (sorriso já virou negativa).

### Cabeça baixa (H)

| Chave | Valor |
|-------|--------|
| `head_down.event_min_seconds` | `8.0` |
| `head_down.short_to_persistent_seconds` | `8.0` |
| `head_down.inconclusive_hold_seconds` | `12.0` |
| `head_down.suppress_when_occlusion` | `true` |
| `head_down.allow_face_missing_proxy` | `false` |

### Oclusão (J / K)

| Chave | Valor |
|-------|--------|
| `face_occlusion.wrist_near_ratio` | `0.70` |
| `face_occlusion.confirm_seconds` | `0.35` |
| `face_occlusion.clear_hold_seconds` | `4.0` |
| `face_occlusion.face_missing_hold_seconds` | `15.0` |
| `face_occlusion.persistent_seconds` | `5.0` |
| `face_occlusion.suppress_when_landmarks_clear` | `true` |

### Celular (E3 / E4 / D / C) — já em `eb6590e`

| Chave | Valor |
|-------|--------|
| `vision.phone_yolo.conf_threshold` | `0.30` |
| `vision.phone_yolo.torso_conf_threshold` | `0.30` |
| `phone.possible_after_seconds` | `5` |
| `phone.probable_after_seconds` | `12` |
| `phone.interaction_requires_in_hand` | `true` |
| `phone.association_clear_hold_seconds` | `2.0` |
| `behavioral_events.clear_hold_phone_seconds` | `2.5` |

### Sonolência (G — não mexer para “salvar” H/J)

| Chave | Valor |
|-------|--------|
| `drowsiness.possible_after_seconds` | `6` |
| `drowsiness.probable_after_seconds` | `30` |
| `drowsiness.eye_closed_ear_threshold` | `0.18` |
| `drowsiness.minimum_observation_quality` | `0.60` |
| `drowsiness.head_down_possible_multiplier` | `2.0` |
| `drowsiness.head_down_probable_seconds` | `45.0` |

---

## KEEP / NEVER (H · J · K · EX)

**KEEP:** `fer_onnx` + smile_boost; H limpa ao erguer; J/K = mão cobrindo → oclusão (não head_down); punho no peito ≠ oclusão; G intocado.

**NEVER:** VGAF no TRI; sticky head_down com usuário ereto; J/K virar sono; mexer `confirm_seconds` / holds de oclusão sem reteste J+K+L+H juntos.
