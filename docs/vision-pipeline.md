# Vision pipeline — baseline e evolução prevista

## Pipeline atual (Fase 0)

```mermaid
flowchart TD
  rtsp[RTSP_latest_frame_20Hz]
  overlay[Detect_Recognize_6Hz]
  presence[Presence_2s]
  engTick[Engagement_tick_3s]
  yunet[YuNet]
  facenet[FaceNet_FAISS]
  bbox[BboxTracker]
  mesh[FaceMesh_signals]
  eng[Engagement_window]
  climate[Climate_window]
  temporal[TemporalAggregator]
  events[(events_SQLite)]
  rtsp --> overlay --> yunet --> facenet --> bbox
  rtsp --> presence --> yunet
  presence --> facenet --> events
  rtsp --> engTick --> mesh
  mesh --> eng --> events
  mesh --> climate --> events
  mesh --> temporal --> events
```

### Detalhes

| Etapa | Implementação | Intervalo |
|-------|---------------|-----------|
| Captura | `AsyncRTSPCapture` / webcam | ~20 Hz consume |
| Overlay | YuNet + embedding + match | ~6 Hz |
| Presença | `PresencePipeline` + dedup | 2 s |
| Engajamento | `EngagementAnalytics` + head pose | amostragem 3 s; janela 10 s |
| Clima | `ClimateAnalytics` (sem FER default) | flush 15 s |
| Behavioral | `BehavioralSignalsPipeline` | mesmo tick engajamento |
| Phone | `phone_yolo` | off |

### Tracking atual

- Apenas `BboxTracker` (IoU) na presença.
- Behavioral usa índices `t0, t1…` (instável).
- **Roadmap:** PersonTrack + FaceTrack + IdentityBinding (não só IoU).

## Pipeline alvo (pós fases autorizadas)

Ver plano: FrameScheduler → Person/Face detect → tracks → IdentityBinding → landmarks → expression (shadow) → phone → pose mínima → temporal → fusion → debug UI → (depois) SQLite tipado / React / LXP mock.

## Modos de módulo (Fase 1+)

`disabled | debug | shadow | production` — nunca promover provider direto a `production` após spike (máx. `shadow`).
