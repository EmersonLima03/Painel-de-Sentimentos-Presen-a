# Congelamento LIVE — 13–14/09/2026

**Aprovado por:** Emerson Lima (webcam `/debug/vision`, USB XWF-1080P)  
**Branch:** `tri/congelado-baseline-validado`  
**Perfil:** `PRESENCA_CONFIG_OVERLAY=config.tri.yaml`, `RUNTIME_MODE=rtsp`  
**Não é TRI 100%.** É o resultado LIVE de celular/fone/oclusão-falsa que **não pode se perder de novo**.

Observação desta sessão: JPEG overlay + `GET /api/v1/live/debug-snapshot` (sem Chromium extra).  
**MP4 / Live Monitor / VGAF não são prova de fechamento.**

---

## Aprovado nesta sessão (não regressar)

| ID | Pose | Contrato observado |
|----|------|-------------------|
| **E4** | Celular no peito, olhar câmera | `phone_near_person`, `in_hand=false`, `phone_resting_on_torso_looking_forward`; sem possible/probable; attn Alta |
| **E3** | Celular na cara / uso | magenta + `in_hand` → possible (≥5s) / probable (≥12s). Recorte YOLO só nas câmeras **ainda é uso** se colado no rosto |
| **D** | Celular na mão 15s+ | caixa contínua ≠ `not_detected`; alerta `probable` verdadeiro |
| **C** | Só fone, celular fora do quadro | `not_detected`, zero evento de phone (1 take; ×3 formais ainda na matriz) |
| **E-lat** | Celular ao lado, olhar câmera | visível/`near`, **não uso** (`phone_lateral_visible_not_use`); sem oclusão inventada |

**E4 e E3 sempre retestados juntos.** Ajuste de peito ou “ao lado” sem reteste na cara = regressão.

---

## Ainda não revalidado nesta sessão

H (cabeça baixa), I/L, J facepalm, EX+ sorriso — contratos antigos do baseline de agosto **continuam válidos no papel**; não foram o take de 13–14/09.

---

## KEEP (não desfazer)

- ROI `raised_roi` (cara) depois `chest_roi` (peito); sem `hand_roi` enorme como caminho principal.
- Close-up: handset inteiro **não** é `bottle_like_relative_height` (`closeup_handset`).
- Ao lado + olhar câmera + **não** colado no rosto → não uso.
- Colado/sobre o rosto (mesmo bbox parcial) → E3 uso.
- Fone over-ear (`_phone_in_ear_zone`) ≠ `phone_raised_to_face`.
- Punho abaixo do queixo com face visível ≠ oclusão J.
- `_frame_signal` via `cv2.meanStdDev` (nunca `np.std` em 1080p float64).
- Overlay TRI: `fer_onnx` + `smile_boost`.
- Hold de detecção/associação curto (~2s); clear rápido ao soltar.

---

## NEVER (veneno que já quebrou o LIVE)

- Person ROI derivado da **face** / calibrar filtro **só em MP4**.
- PASS MP4 ou bateria Live Monitor como merge.
- `large_handheld_upper` tratar “ao lado, olhar câmera” como uso.
- Rejeitar handset close-up alto (`h > 0.42·pessoa`) como garrafa (magenta só no topo).
- Fechar D porque “travou no fim” depois de FN no começo.
- Mexer em G (olhos fechados) para “salvar” outro cenário.
- VGAF/HSEmotion no path de fechamento TRI (sorriso virava negativa).
- Versionar JPEGs de `/debug/snapshot` (rosto do testador).

---

## Testes de regressão obrigatórios após editar phone/pose

```powershell
$env:PRESENCA_CONFIG_OVERLAY = "config.tri.yaml"
pytest tests/test_phone_filters.py tests/test_phone_positive_controls.py tests/test_phone_false_positive_regression.py tests/test_frame_usable_black.py tests/test_l_occlusion_contract.py -q
```

Depois, na webcam, no mínimo: **E4 peito → E3 cara → C fone**.
