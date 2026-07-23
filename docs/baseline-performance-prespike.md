# Baseline de desempenho pré-spike

**Status: BLOQUEADO — câmera inacessível**

## Tentativa

- Data: 2026-07-23
- Hardware: 11th Gen Intel Core i5-11300H @ 3.10GHz, ~15,8 GB RAM
- Config: `modules.*.mode = disabled`
- Câmera: `cam-vip-5440-01` (RTSP Intelbras `192.168.100.133`)
- Credencial no `config.yaml`: placeholder `PASSWORD` (`has_placeholder=True`)
- Probe OpenCV/FFMPEG ~8s (+ timeout interno ~30s): `reachable=False`, `frames=0`

## Métricas pedidas

| Métrica | Valor |
|---------|-------|
| capture FPS médio/mín/p95 | **não coletado** |
| latência presença p50/p95 | **não coletado** |
| CPU média/pico | **não coletado** |
| memória média/pico | **não coletado** |
| check-ins | **não coletado** |
| erros de câmera | stream timeout / unreachable |
| rostos observados | **não coletado** |
| duração | probe 8s (não 5 min) |

**Paridade: não afirmada.**

## Condição para desbloquear

1. RTSP com credenciais reais e rede alcançável
2. Reexecutar medição ≥5 min com módulos novos `disabled`
3. Registrar números neste arquivo
