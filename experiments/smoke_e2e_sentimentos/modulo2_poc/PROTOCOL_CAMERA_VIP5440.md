# PROTOCOL — Intelbras VIP-5440-IA (sala ~36 m²)

**Objetivo:** medir empiricamente se a câmera + instalação + modelo + distância + galeria formam um conjunto adequado.  
**Não assumir** adequação só porque o equipamento tem “IA”.

## Pré-requisitos

- VIP-5440-IA energizada e acessível via RTSP (credencial real, não `PASSWORD` do lab).
- Fita métrica / marcações no chão (0,5 m / 1 m / 2 m / 3 m / 4 m / canto).
- Iluminação natural + artificial tipicamente usadas na sala.
- Notebook/mini-PC com Edge **ou** apenas este POC (`capture_distance_probe.py`).
- Consentimento LGPD dos participantes do teste.

## Variáveis a registrar

| Campo | Unidade / nota |
|-------|----------------|
| altura_camera_m | metros |
| inclinacao_aprox_graus | estimativa |
| distancia_aluno_m | metros |
| zona | frente / centro / fundo / canto_esq / canto_dir |
| iluminacao | dia / noite / mista / contraluz |
| n_pessoas | 1, 2, 4, 8… |
| pose | frontal / lateral_esq / lateral_dir |
| oculos | sim / nao |
| resolucao_stream | ex. 1920×1080 subtype |
| bbox_w_px, bbox_h_px | do detector |
| face_area_px | w×h |
| detectou | sim / nao |
| reconheceu | ID / UNKNOWN / N/A |
| score, margin | se matching rodou |
| observacao | texto livre |

Usar `manifests/camera_vip5440_log.csv`.

## Procedimento

1. Fixar câmera (altura/ângulo) e fotografar instalação.
2. Marcar distâncias no chão.
3. Para cada distância e zona: 1 pessoa frontal → anotar px do rosto.
4. Repetir com lateral e óculos nas distâncias 1 m, 2 m, 3 m.
5. Multi-pessoa no centro (N crescente) — anotar quantos rostos detectados.
6. Contraluz / janela — anotar falhas.
7. Se houver 2ª câmera: mapa de sobreposição / zona cega.

## Critérios (a calibrar com dados)

**PASS (proposta inicial, sujeita a revisão com dados):**

- Nas zonas “frente + centro” (distâncias típicas de carteira), face detectada com altura ≥ **80 px** (hipótese; validar).
- Em reconhecimento com galeria de teste, ID correta ≥ critério do `PROTOCOL_THRESHOLD.md`.
- Multi-pessoa: degradação documentada, não surpresa.

**FAIL:**

- Na maioria das carteiras, face < limiar px e matching inconsistente.
- Zonas cegas grandes sem plano de 2ª câmera.

## Estado atual

| Item | Status |
|------|--------|
| Medições VIP-5440 neste POC | **NÃO TESTADO** |
| FOV / px / multi-pessoa / 36 m² | **NÃO TESTADO** |
| RTSP com credencial real | **NÃO TESTADO** (config lab ainda placeholder) |
