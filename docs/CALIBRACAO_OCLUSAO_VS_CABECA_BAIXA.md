"""
Calibração oclusão vs cabeça baixa (jul/2026)

## Problema observado

Com mão na frente do rosto, o painel emitia **“Cabeça baixa prolongada”** em ~1 s
enquanto atenção/expressão corretamente caíam para **inconclusivo**.

## Pesquisa (não tuning aleatório)

| Fonte | Achado aplicado |
|-------|-----------------|
| MediaPipe issues #3972, #4484, #5450 | Face Landmarker **não** dá visibility/presence confiável → oclusão precisa de proxy (punho) + gates |
| DashSentinel / DMS literature | **Visibility gates**: sem olhos/landmarks OK, não afirmar drowsiness/head-down |
| ACAMF / occlusion-resilient DMS | Modalidade pouco confiável é *downweighted*; oclusão tem prioridade |
| Head-pose papers (solvePnP / pitch) | Pitch ~20–40° = look-down; nosso pitch normalizado 0.45 ≈ 40° |

## Regras implementadas

Prioridade:

1. **Oclusão por punho** (mão perto do rosto) → `face_occlusion`; **suprime** head_down
2. **Face não observável** sem punho e sem geometria corporal → `pose_inconclusive` (não inventar head_down)
3. **Cabeça baixa** com:
   - pitch facial **e** `landmarks_quality ≥ 0.45`, ou
   - geometria corporal `nose_shoulder_ratio` (nariz+ombros), ou
   - **ângulo extremo** `shoulders_without_face_look_down` (ombros + face ausente + coroa/ears, **sem** punho) — jul/ago 2026

Hold: `inconclusive_hold_seconds` (12s) evita fragmentar episódio quando o pose pisca `inconclusive`.  
Evento: `started_at` = `head_down_since` (duração ≈ tempo real).  

**Aprovado manual 2026-08-03 (H ✅):** prints ~37s e ~14s contínuos — ver `docs/BASELINE_MANUAL_APROVADO_TRI.md`.

## Config (`config.yaml` → `head_down`)

- `allow_face_missing_proxy: false` — desliga o proxy legado “rosto sumiu = cabeça baixa”
- `short_to_persistent_seconds: 8.0` — alinha “prolongada” ao evento (antes 2.5s hardcoded)
- `suppress_when_occlusion: true`
- `require_landmarks_quality: 0.45`

Código: `app/pipeline/occlusion_head_arbitration.py` + integração em `analytics_track.py` / `body_pose.py`.

## Como validar manualmente

1. Rosto frontal → atenção alta, sem evento head_down
2. Olhar para baixo 8s+ (rosto ainda visível) → `head_down_short` → `persistent` + evento
3. Mão tampando o rosto → oclusão / métricas inconclusivas; **sem** “Cabeça baixa prolongada”
4. Cabeça baixa + leitura (sem mão) → head_down, não oclusão
