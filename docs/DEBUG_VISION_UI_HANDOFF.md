# Handoff técnico — `/debug/vision` (UI redesign)

Gerado a partir do repo em 2026-07-27. Sem sugestões de design — apenas dados brutos.

| Item | Valor |
|------|--------|
| HTML fonte | `app/static/debug_vision.html` (521 linhas) |
| SHA256 | `81D7B64ACA1EBCF9BC7F4B827B91B36B8721DAD589B57DFA966289144694A0D3` |
| Snapshot | `GET /api/v1/live/debug-snapshot` |
| Preview | `GET /debug/mjpeg?camera_id=cam-web&overlay=1&fps=15` |
| Poll | **1500 ms**; sem WebSocket/SSE nesta página |

**O HTML completo está em** `app/static/debug_vision.html` — copiar esse arquivo integralmente para a outra IA (não duplicar aqui para evitar drift).

---

## 2. Schema do payload `GET /api/v1/live/debug-snapshot`

### 2.1 Notas de endpoint (código real)

- Handler: `app/api/v1.py` → `debug_snapshot`
- **Não declara** query param `camera_id`. A query `?camera_id=cam-web` enviada pelo HTML **é ignorada**.
- Corpo = singleton `_live_state`, atualizado por `orchestrator.publish_live_debug(camera_id)`.
- Auth: `require_api_token` (`X-API-Token` se token em localStorage/`?api_token=`).
- Localhost-only salvo `debug_vision_allow_remote`.
- Remove: `embeddings`, `rtsp_url`, `frame`, `credentials`.
- `_enrich` adiciona: `runtime_mode`, `is_simulated`, `disclaimer`, `banner` (demo).
- Sem modelo Pydantic dedicado — contrato efetivo abaixo.

### 2.2 TypeScript (contrato efetivo)

```typescript
/** Resposta JSON de GET /api/v1/live/debug-snapshot (após _enrich) */
interface DebugSnapshotResponse {
  updated_at: number; // unix seconds (float)
  camera_id?: string;
  tracks: AnalyticsTrack[];
  bindings: unknown[]; // hoje []
  live_event_buffer?: LiveEventBufferItem[]; // root; página NÃO renderiza na UI principal
  data_freshness_meta?: { poll_hint_ms?: number; storage?: string };
  signals?: unknown[];
  phones?: Array<{ bbox: number[]; conf: number | null }>;
  visible_people?: number;
  recognized_people?: number;
  observable_people?: number | null;
  inconclusive_people?: number | null;
  attention_index?: number | null;
  apparent_climate?: unknown;
  observation_quality?: {
    note?: string;
    aggregate_observable?: number | null;
    aggregate_inconclusive?: number | null;
  };
  latencies_ms?: Record<string, number | null>;
  module_modes?: {
    expression?: string;
    face_landmarks?: string;
    phone?: string;
    pose?: string;
    temporal_fusion?: string;
    person_tracking?: string;
  };
  camera_status?: string;
  classroom_counts?: Record<string, unknown>;
  security?: {
    localhost_only: boolean;
    stores_frames: boolean;
    exposes_embeddings: boolean;
    exposes_rtsp: boolean;
  };
  runtime_mode: string;
  is_simulated: boolean;
  disclaimer: string;
  banner?: string;
  frame_source?: string;
}

interface AnalyticsTrack {
  person_track_id: string;
  track_id: string; // alias = person_track_id
  student_id: string | null;
  full_name: string | null;
  track_age_seconds: number;
  track_confidence: number;
  tracking_state: TrackingState;
  seconds_since_person_detection: number;
  last_person_bbox: [number, number, number, number];
  person_bbox: [number, number, number, number];
  bbox: [number, number, number, number];
  face_bbox: [number, number, number, number] | null;
  reassociation_score: number | null;
  raw_tracker_id: string | number | null;
  missed_detections: number;
  expire_reason: string | null;
  identity: IdentityPayload;
  observability: ObservabilityPayload;
  face_person_association?: Record<string, unknown>;
  pose?: Record<string, unknown>;
  hands?: Record<string, unknown>;
  observation_quality: ObservationQualityPayload;
  head_state: HeadStatePayload;
  face_occlusion?: { state?: string; [k: string]: unknown };
  phone: PhonePayload;
  expression: ExpressionPayload;
  facial_features: FacialFeaturesPayload;
  visual_attention: VisualAttentionPayload;
  drowsiness: DrowsinessPayload;
  latencies_ms?: Record<string, number>;
  active_events?: ActiveEvent[];
  phone_detector?: Record<string, unknown>;
  person_detector?: Record<string, unknown>;
  identity_confidence?: number | null;
  confidence?: number | null;
}

interface IdentityPayload {
  student_id: string | null;
  full_name: string | null;
  confidence: number | null;
  identity_confidence: number | null;
  face_confirmation_confidence: number;
  source: string;
  identity_source: string;
  identity_state: IdentityStateEnum;
  face_visible: boolean;
  last_face_seen_at: number | null;
  last_face_confirmation_at: number | null;
  seconds_since_face_seen: number;
  seconds_since_face_confirmation: number;
  margin: number | null;
  pending_switch: string | null;
  confirmation_count: number;
  cooldown_until: number | null;
  body_continuity_confidence: number; // UI: "body_cont_conf"
  revalidation_required: boolean;
  ambiguity_reasons: string[];
  spatial_reassociation: boolean;
  face_confirmation_stale: boolean;
  reconfirmation_recommended: boolean;
}

/** NÃO existe campo booleano top-level `face_confirmed` — é valor de identity_state */
type IdentityStateEnum = "face_confirmed" | "body_continuity" | "uncertain" | "unknown";

interface ObservabilityPayload {
  face_observable: boolean;
  eyes_observable: boolean;
  head_pose_observable: boolean;
  body_detected: boolean;
  body_observable: boolean;
  body_track_active: boolean;
  body_continuity_available: boolean;
  seconds_since_body_detection: number;
  tracking_state: TrackingState;
  phone_observable: boolean;
  expression_observable: boolean;
  identity_observable: boolean;
  ui_body_label: UiBodyLabel;
}

type UiBodyLabel =
  | "body_observable"
  | "body_continuity_temporarily_interrupted"
  | "body_not_observable";

type TrackingState = "active" | "temporarily_lost" | "reassociated" | "expired";

interface ObservationQualityPayload {
  face_size_score?: number;
  sharpness_score?: number;
  illumination_score?: number;
  pose_score?: number | null;
  occlusion_score?: number | null;
  visibility_score?: number;
  landmarks_quality?: number | null;
  overall_score?: number;
  overall_observability?: number;
  status: string;
  reasons?: string[];
  phone_visibility?: number;
}

interface HeadStatePayload {
  state?: HeadStateEnum | string;
  confidence?: number;
  reasons?: string[];
  status?: string;
}

type HeadStateEnum =
  | "head_forward"
  | "head_down_short"
  | "head_down_persistent"
  | "head_supported"
  | "pose_inconclusive";

interface PhonePayload {
  status: string;
  state: PhoneStateEnum | string;
  provider?: string;
  confidence?: number | null;
  duration_seconds?: number | null;
  phone_in_hand?: boolean;
  ambiguous?: boolean;
  reasons?: string[];
  reason?: string | null;
}

type PhoneStateEnum =
  | "not_detected"
  | "phone_visible"
  | "phone_near_person"
  | "phone_in_hand"
  | "possible_phone_interaction"
  | "probable_phone_interaction";

interface ExpressionPayload {
  provider?: string;
  model_name?: string;
  raw_label?: string | null;
  normalized_state?: string;
  confidence?: number | null;
  smoothed_state?: string | null;
  smoothed_display_pt?: string | null;
  is_conclusive?: boolean;
  status: string;
  inference_ms?: number;
  sample_count?: number;
  [k: string]: unknown;
}

interface FacialFeaturesPayload {
  left_eye_openness: number | null;
  right_eye_openness: number | null;
  average_eye_openness: number | null;
  blink_score: number | null;
  mouth_open_score: number | null;
  possible_yawn_score: number | null;
  smile_score: number | null;
  yaw: number | null;
  pitch: number | null;
  roll: number | null;
  gaze_horizontal: number | null;
  gaze_vertical: number | null;
  landmarks_quality: number | null;
  provider: string;
  status: string;
  reason?: string | null;
}

interface VisualAttentionPayload {
  status?: string;
  state: AttentionStateEnum | string;
  confidence?: number;
  duration_seconds?: number;
  sample_count?: number;
  contributing_signals?: Record<string, number | string | null>;
  reasons?: string[]; // inclui "gaze_used" — NÃO é campo booleano top-level
}

type AttentionStateEnum = "high" | "moderate" | "low" | "inconclusive";

interface DrowsinessPayload {
  status?: string;
  state: DrowsinessStateEnum | string;
  confidence?: number;
  duration_seconds?: number;
  sample_count?: number;
  reasons?: string[];
  contributing_signals?: Record<string, unknown>;
  descriptive_label?: string | null;
  perclos?: Record<string, unknown>;
}

type DrowsinessStateEnum = "none" | "possible" | "probable" | "inconclusive";

interface ActiveEvent {
  event_id: string;
  event_type: string;
  status: string;
  duration_seconds: number;
  attribution_status?: string;
  candidate_student_id?: string | null;
  confirmed_student_id?: string | null;
  identity_state?: string;
  reasons?: string[];
  severity?: string;
}

interface LiveEventBufferItem {
  event_id?: string;
  event_type?: string;
  person_track_id?: string;
  attribution_status?: string;
  identity_state?: string;
  storage?: string;
  [k: string]: unknown;
}
```

### 2.3 IdentityState.as_dict (Python — fonte)

`app/vision/identity_binding.py`:

```python
{
  "student_id", "full_name", "confidence", "identity_confidence",
  "face_confirmation_confidence", "source", "identity_source", "identity_state",
  "face_visible", "last_face_seen_at", "last_face_confirmation_at",
  "seconds_since_face_seen", "seconds_since_face_confirmation", "margin",
  "pending_switch", "confirmation_count", "cooldown_until",
  "body_continuity_confidence", "revalidation_required", "ambiguity_reasons",
  "spatial_reassociation", "face_confirmation_stale", "reconfirmation_recommended",
}
```

### 2.4 Campos que a página USA

| UI | Fonte JSON |
|----|------------|
| Estado operacional | **Client** `computeFreshness()` |
| age / poll | `updated_at`, `POLL_MS` |
| Eventos importantes agora | **Client** `renderImportant` |
| Título identidade | `full_name` / `identity.*` + `identity_state` + `seconds_since_face_confirmation` |
| Sonolência | `drowsiness.state`, `duration_seconds`, `descriptive_label` |
| Atenção | `visual_attention.state`, `reasons[]` |
| Celular | `phone.status`, `state`, `duration_seconds` |
| Expressão | `expression.smoothed_display_pt`, `confidence`, `sample_count` |
| Cabeça / Corpo | `head_state.state`, `observability.ui_body_label` / `body_observable` |
| Módulos | `facial_features.status`, `observation_quality.status`, `phone.status` |
| Tech: EAR, yaw/pitch/roll | `facial_features.*` |
| Tech: identity_state, source | `identity.identity_state`, `identity_source\|\|source` |
| Tech: body_cont_conf | `identity.body_continuity_confidence` |
| Tech: seconds_since_face | `identity.seconds_since_face_confirmation` |
| Tech: observability | `observability` objeto |
| Tech: eventos | `active_events` |
| Tech: raw attn/drow/phone | **Client-only** `` `${attn.state}/${drow.state}/${phone.state}` `` |
| JSON bruto | snapshot inteiro |

### 2.5 Eventos importantes (client)

1. freshness ∈ {stale, unavailable} → "Dados desatualizados"
2. drowsiness.state ∈ {possible, probable}
3. phone.state ∈ {possible_phone_interaction, probable_phone_interaction}
4. identity.identity_state === "uncertain"

Não usa `live_event_buffer`.

### 2.6 Estado operacional (client)

`live | delayed | stale | unavailable | recovering | no_tracks`

---

## 3. Renomeações / remoções / mudanças

| Antigo | Atual | Mudança |
|--------|-------|---------|
| Identidade só por student_id | `identity.identity_state` + labels PT | 4 estados |
| TTL 12s expirava ID | 12s = stale facial only | body_continuity mantém student_id |
| — | `body_continuity_confidence` (UI: body_cont_conf) | novo |
| — | `face_confirmation_confidence` | novo |
| source único | `identity_source` (+ `source`) | preferir identity_source |
| — | `seconds_since_face_confirmation` | novo |
| — | `observability` + `ui_body_label` | novo |
| — | `tracking_state` | active/temporarily_lost/reassociated |
| spatial via reassociation_score residual | só `tracking_state==reassociated` | fix P0 |
| — | `active_events` + attribution | novo |
| — | root `live_event_buffer` | não destacado na UI live |
| gaze como campo | `gaze_used` ∈ `visual_attention.reasons` | string em array |
| — | Estado operacional / Eventos importantes | client FSM |
| — | raw attn/drow/phone | client concat |
| detalhes no card | `#tech-panel` em `.live-below` | layout atual |
| booleano `face_confirmed` | **não existe** | usar identity_state |
| campo API `body_cont_conf` | **não existe** | usar body_continuity_confidence |

---

## 4. Transporte

- `GET /api/v1/live/debug-snapshot?camera_id=cam-web` — **camera_id ignorado**
- Poll **1500 ms**, HTTP JSON, **sem WS/SSE** nesta página
- Auth: `X-API-Token` opcional
- Preview: `/debug/mjpeg?camera_id=cam-web&overlay=1&fps=15`

---

## 5. Enums

- **identity_state:** `face_confirmed` | `body_continuity` | `uncertain` | `unknown`
- **identity source:** `face_recognition` | `body_continuity` | `spatial_reassociation` | `unknown`
- **tracking_state:** `active` | `temporarily_lost` | `reassociated` | `expired`
- **ui_body_label:** `body_observable` | `body_continuity_temporarily_interrupted` | `body_not_observable`
- **visual_attention.state:** `high` | `moderate` | `low` | `inconclusive`
- **visual_attention.reasons (amostra):** `head_away` | `gaze_used` | `low_coverage` | `probable_phone` | `apparent_drowsiness` | `recurrent_low` | `short_look_down` | `head_down_persistent_descriptive` | `insufficient_observation_quality` | `face_not_observable`
- **drowsiness.state:** `none` | `possible` | `probable` | `inconclusive`
- **drowsiness.descriptive_label:** `prolonged_eye_closure_observed` | null
- **phone.state:** `not_detected` | `phone_visible` | `phone_near_person` | `phone_in_hand` | `possible_phone_interaction` | `probable_phone_interaction`
- **module status:** `available` | `unavailable` | `disabled` | `error` | `inconclusive` | `not_implemented` | `sem_dado`
- **observation_quality.status:** `observable` | `partially_observable` | `inconclusive` | `not_visible` (+ `low_quality` em validação)
- **head_state.state:** `head_forward` | `head_down_short` | `head_down_persistent` | `head_supported` | `pose_inconclusive`
- **face_occlusion.state (amostra):** `none` | `possible_face_occlusion_by_hand` | `persistent_possible_face_occlusion`
- **attribution_status:** `confirmed` | `pending` | `track_only`
- **Estado operacional (client):** `live` | `delayed` | `stale` | `unavailable` | `recovering` | `no_tracks`
- **module_modes:** `disabled` | `debug` | `shadow` | `production`

---

## 6. `/debug/mjpeg`

Params inalterados:

- `camera_id: str = "cam-web"`
- `overlay: int = 1`
- `fps: float = 20.0` (ge=2, le=30); página usa **15**

Requer `ENABLE_DEBUG_SNAPSHOT=1`. multipart `x-mixed-replace; boundary=frame`.

---

## 7. Validação controlada (mesma página)

- `POST /api/v1/validation/sessions`
- `POST .../steps/start` | `.../sample` (500ms) | `.../finish`
- `GET .../sessions/{id}` | `.../report` | `.../report.csv`

---

## 8. Fontes

- `app/static/debug_vision.html`
- `app/api/v1.py`
- `app/pipeline/orchestrator.py` `publish_live_debug`
- `app/pipeline/analytics_track.py`
- `app/vision/identity_binding.py`
- `app/analytics/attention_drowsiness.py`
- `app/main.py` `debug_mjpeg`
