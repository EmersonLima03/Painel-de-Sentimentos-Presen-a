# Thresholds congelados — baseline Fase 0

**NÃO alterar** sem regressão explícita e atualização deste arquivo + `threshold_profile`.

**Perfil:** `presence-yaml-2026-07-23`  
**Fonte:** `config.yaml` + defaults do agregador temporal

## Presença / matching (`vision.presence`)

| Chave | Valor congelado |
|-------|-----------------|
| `sampling_seconds` | 2 |
| `threshold` | 0.70 |
| `match_margin` | 0.10 |
| `th_on` | 0.75 |
| `th_off` | 0.68 |
| `track_ttl_seconds` | 2.5 |
| `max_templates_per_student` | 7 |
| `min_face_size` | 22 |
| `always_on` | true |
| `dedup_mode` | day |

## Detecção (`vision`)

| Chave | Valor |
|-------|-------|
| `detector` | yunet |
| `embedder` | facenet |
| `max_faces` | 30 |
| `yunet_score_threshold` | 0.45 |
| `min_face_area_ratio` | 0.0005 |
| `face_aspect_min` | 0.45 |
| `face_aspect_max` | 1.55 |
| `mediapipe_min_confidence` | 0.55 |

## Engajamento / clima / behavioral

| Chave | Valor |
|-------|-------|
| `engagement.backend` | head_pose |
| `engagement.sampling_seconds` | 3 |
| `engagement.window_seconds` | 10 |
| `engagement.model_version` | eng-v2-headpose |
| `climate.use_fer` | false |
| `climate.window_seconds` | 15 |
| `behavioral.enabled` | true |
| `phone_yolo.enabled` | false |

## Temporal aggregator (código — defaults)

| Chave | Valor |
|-------|-------|
| `out_of_field_seconds` | 45.0 |
| `eyes_closed_seconds` | 45.0 |
| `drowsiness_combo_seconds` | 60.0 |
| `min_confidence` | 0.55 |
| `track_ttl_seconds` | 8.0 |

## Orquestrador (constantes)

| Chave | Valor |
|-------|-------|
| `_CAPTURE_HZ` | 20.0 |
| `_DETECT_HZ` | 6.0 |
