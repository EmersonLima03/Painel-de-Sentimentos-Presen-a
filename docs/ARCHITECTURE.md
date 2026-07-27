# Arquitetura — Dulino Edge Vision

## Arquitetura geral

```mermaid
flowchart TD
  FS[FrameSource\ndemo | offline | rtsp]
  DET[Person / Face Detection]
  TR[PersonTrack / FaceTrack]
  ID[IdentityBinding]
  FF[FacialFeatures / Landmarks]
  EX[ExpressionProvider]
  PH[PersonPhoneAssociator]
  PO[Pose mínima]
  OQ[ObservationQuality]
  TF[TemporalFusion / FusionEngine]
  PER[(SQLite prod ou demo)]
  API[API v1]
  WS[WebSocket /ws/live]
  UI[Dashboard / Debug]
  LXP[LXP Outbox Mock]

  FS --> DET --> TR --> ID
  ID --> FF --> EX
  ID --> PH
  ID --> PO
  FF --> OQ
  EX --> TF
  PH --> TF
  PO --> TF
  OQ --> TF
  TF --> PER
  TF --> API
  API --> WS
  API --> UI
  TF --> LXP
```

**Presença** (YuNet + FaceNet + check-in) corre em caminho **isolado** no `PresencePipeline` / orquestrador. Analytics **não** cria, remove ou invalida presença.

### Runtime RTSP conectado (person-first, 2026-07-23)

Motor oficial de analytics: `app.pipeline.analytics_track.RealtimeAnalyticsEngine`.

```text
PersonTrack = continuidade da pessoa (YOLO → ByteTrack bruto → StablePersonTrackManager)
FaceTrack = observação temporária do rosto (YuNet overlay)
IdentityBinding = vínculo pessoa ↔ identidade (TTL; nunca attendance)
PresencePipeline = check-in independente (INTOCADO)
RealtimeAnalyticsEngine = sinais / eventos analíticos
```

**Dois TTL distintos:** identity TTL (12s sem face → unknown) ≠ person track `max_time_lost` (8s sem corpo → expire). Durante `temporarily_lost`, o mesmo `person_track_id` continua e buffers são preservados. Reassociação espacial remapeia IDs brutos ByteTrack (`bt-N`) para o ID estável.

```text
frame completo
  → YOLO.track (bytetrack_person.yaml; track_buffer em FRAMES do ciclo ~0.5s)
  → raw tracks (bt-N podem mudar)
  → StablePersonTrackManager (IDs estáveis + temporarily_lost / reassociated)
  → FacePersonAssociator / IdentityBinding / Pose / Phone
  → RealtimeAnalyticsEngine (buffers por person_track_id)
```

| Conceito | Papel |
|----------|--------|
| `person_track_id` | Chave temporal estável do analytics (`tracking_state`: active\|temporarily_lost\|reassociated) |
| Face | Identifica / reconfirma; some → `cached_binding` até TTL |
| Margem | Só se runtime fornecer top2; senão `margin=null` + regras mais rígidas |
| Cabeça baixa | Descritivo (`head_down_*`); ≠ sonolência / desatenção automática |
| Mãos (punhos) | No máx. `hand_near_face` / `possible_face_occlusion_*` |
| Celular | `phone_visible` ≠ uso; nunca `confirmed_*` |
| Atenção / sonolência sem rosto | `inconclusive` |
| Aliases deprecated | `track_id`, `student_id`, `bbox` (= person_*) |

**Presença** (YuNet + FaceNet + check-in) permanece isolada. Analytics **não** cria/remove presença.

Intervalos: `analytics.quality_interval_seconds` / `landmarks_interval_seconds`. Overlay: pessoa ciano, face verde, celular magenta; textos descritivos (sem “dormindo/desatento” como fato).

**Nenhuma validação científica / longitudinal nesta conexão.**

**Motor temporal oficial:** regras no `RealtimeAnalyticsEngine` (+ `attention_drowsiness.py`).  
**Legado:** `temporal_aggregator` — não operar dois fluxos equivalentes.

## Modos de runtime (`RUNTIME_MODE` / `runtime.mode`)

| Modo | Fonte | Banco | Providers | Finalidade | Limitação |
|------|-------|-------|-----------|------------|-----------|
| **demo** | `DemoFrameSource` + `DemoEngine` | `data/demo/dulino_edge_demo.db` | Mock / cenário determinístico | Demonstrar fluxo completo sem câmera | Dados simulados; banner permanente |
| **offline** | `OfflineFrameSource` (vídeo/pasta) | prod (se usado) | Reais se habilitados | Spike / replay | Sem labels ≠ validação científica |
| **rtsp** | Webcam índice ou RTSP | `data/dulino_edge.db` | Configurados | Operação / teste real | Intelbras bloqueada sem credencial |

Regra: **nunca misturar** dados simulados com modo RTSP/offline.

## Pipeline de presença

1. Captura (webcam assíncrona ou RTSP)
2. Detecção **YuNet**
3. Embedding **FaceNet** (512D)
4. Matching (FAISS IP ou fallback linear) com margem e histerese
5. Tracker de bbox (TTL) + multi-template por aluno
6. Check-in → evento `attendance_checkin` na fila SQLite
7. Deduplicação por `dedup_mode` (default `day`)

### Thresholds congelados — perfil `presence-yaml-2026-07-23`

**Não alterar** sem regressão explícita + atualização desta tabela + `threshold_profile` na config.

| Chave | Valor |
|-------|-------|
| `sampling_seconds` | 2 |
| `threshold` | 0.70 |
| `match_margin` | 0.10 |
| `th_on` / `th_off` | 0.75 / 0.68 |
| `track_ttl_seconds` | 2.5 |
| `max_templates_per_student` | 7 |
| `min_face_size` | 22 |
| `yunet_score_threshold` | 0.45 |
| `max_faces` | 30 |

Orquestrador: captura ~20 Hz, detecção ~6 Hz.

**Regra explícita:** nenhum módulo analítico pode criar, remover ou invalidar presença. Perda de track, oclusão ou baixa observabilidade **não** removem check-in.

## Tracking e identidade

- `PersonTrack` / `FaceTrack` — estruturas tipadas (`app/vision/tracking_types.py`)
- `IdentityBindingEngine` — vínculo pessoa↔rosto↔identidade com confiança e razões (não só IoU)
- Cache com expiração / revalidação
- Restrições: uma identidade ↔ no máximo um track ativo; um track ↔ no máximo uma identidade
- Swaps devem ser logados; binding **nunca** grava presença
- Fallback: `BboxTracker`
- **ByteTrack:** opcional; carregar só se dependência disponível — **não aprovado para produção**

No demo: tracker determinístico com 8 pessoas (entrada/saída, oclusão, reassociação).

## Expressões aparentes

Abstração `FacialExpressionProvider` + factory `create_expression_provider`.

| Provider | Status |
|----------|--------|
| Mock | Funcional (demo) |
| FER legado (Mini-XCEPTION) | Experimental; lazy; modelo em `data/models/` |
| HSEmotion | Experimental; venv isolado; **não** no core |
| DeepFace | Experimental; só `actions=["emotion"]`; **não** no core |

Normalização: `positive | neutral | negative | surprise | inconclusive`.  
UI: “expressão predominantemente …”. Classe bruta só em metadata técnica.

**Proibido:** raça, gênero, idade, etnia, diagnóstico clínico.  
**Nenhum** provider real aprovado para `production` sem benchmark + aprovação longitudinal (`longitudinal_approval_recorded`).

## Atenção visual estimada

Sinais: orientação da cabeça, gaze aproximado (se confiável), cobertura, celular provável, sonolência aparente, duração/recorrência, qualidade de observação.

Estados: `high | moderate | low | inconclusive`.  
**Expressão negativa ≠ baixa atenção.**  
Baixa qualidade → `inconclusive` (não “baixo engajamento”).

## Clima da turma

Agregação coletiva de expressões/sinais aparentes em janela (~15s).  
Não é estado psicológico comprovado; UI: “clima visual aparente”.

## Sinais comportamentais / celular / sonolência

**Celular (automático):** `phone_visible` · `phone_near_person` · `possible_phone_interaction` · `probable_phone_interaction`.  
**Nunca** emitir `confirmed_phone_interaction` no motor — confirmação só via `review_status`.

**Sonolência aparente:** olhos fechados + pitch + apoio + baixa movimentação + duração + amostras + qualidade.  
Estados: `none | possible | probable | inconclusive`.  
Dois segundos de olhos fechados **não** geram evento persistente; cooldown; registrar sinais contribuintes.

## Qualidade de observação

Face size, sharpness, illumination, pose, occlusion, visibility, track stability, landmarks, overall, reasons.  
**Baixa observabilidade ≠ baixo engajamento.** Dashboard: presentes / visíveis / observáveis / inconclusivos.

## Motor temporal e provenance

Buffers por sessão/câmera/track; EMA/média; hysteresis; duração mínima; cooldown; gaps; open/update/close; dedup; confidence; observation quality.

Todo evento analítico deve carregar provenance: `provider`, `model_name`, `model_version`, `rule_engine_version`, `threshold_profile`, `camera_calibration_version`, `runtime_mode`, `is_simulated`.

Demo: `runtime_mode=demo`, `is_simulated=true`.

## Persistência

| Banco | Path | Uso |
|-------|------|-----|
| Real | `data/dulino_edge.db` | Presença, fila, cadastros |
| Demo | `data/demo/dulino_edge_demo.db` | Somente simulação |

**Migration 005** (experimental): tabelas `raw_observation_windows`, `engagement_windows_v2`, `climate_windows_v2`, `model_benchmarks`.  
Só com `EXPERIMENTAL_SQLITE_005=1` ou `experimental.sqlite_005_enabled`. Default **off**.  
Rollback em cópia: `python migrations/sqlite/005_observation_windows.py rollback path\to\copia.db`.

Testes usam SQLite temporário (`tests/conftest.py`) e **não** tocam o banco real.

## API, WebSocket, dashboard

Ver [API.md](API.md). Resumo: `/api/v1/*` + `WS /api/v1/ws/live`; auth opcional `API_AUTH_TOKEN`.

| URL | Papel |
|-----|-------|
| `/dashboard` | React educacional (`frontend/dist`) |
| `/dashboard-legacy` | HTML legado |
| `/debug/vision` | Técnico; localhost por padrão; sem embeddings/RTSP completo/frames persistidos |

Disclaimer + banner demo quando `is_simulated`.

## LXP

Clientes: `DisabledLXPClient`, `MockLXPClient`. Outbox com idempotência por `event_id`, retry exponencial, dead-letter.  
Eventos: `attendance_checkin`, `student_observation_window`, `classroom_summary_window`.  
**Não existe** `HttpLXPClient` até haver especificação.

## Estrutura do repositório (resumida)

```text
app/                 Backend FastAPI, pipeline, visão, API, demo
frontend/            Dashboard React (Vite)
migrations/sqlite/   Migrações (005 experimental)
tests/               Pytest isolado
scripts/             Utilitários operacionais
data/                DB, modelos, backups, spike (gitignored em parte)
docs/                Esta documentação oficial
config.yaml          Câmeras e visão
```
