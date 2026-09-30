# Congelamento EX+ / EX= — revalidação LIVE 2026-09-29

**Status:** ✅ **APROVADO E VALIDADO** (neutro + positivo)  
**Aprovado por:** Emerson Lima (teste humano na webcam)  
**Data:** 2026-09-29  
**Árvore produto:** `_facial_enroll_prod` · branch `feat/auth-saas-rbac`  
**Perfil obrigatório:** `PRESENCA_CONFIG_OVERLAY=config.tri.yaml` · `RUNTIME_MODE=rtsp`  
**UI:** `/debug/vision` · boot oficial `scripts/boot_edge_m2.ps1`

> Este documento **congela o caminho** que recuperou EX+/EX= após regressão.  
> **Não** altera os números YAML do LIVE 14/09 — eles continuam em [`VALORES_CONGELADOS_LIVE_20260914.md`](VALORES_CONGELADOS_LIVE_20260914.md).  
> **Não perder de novo.** Qualquer mudança em arquivos sensíveis exige reteste EX+ e EX=.

Contrato histórico (primeira aprovação): [`BASELINE_MANUAL_APROVADO_TRI.md`](BASELINE_MANUAL_APROVADO_TRI.md) · [`CONGELAMENTO_LIVE_20260914.md`](CONGELAMENTO_LIVE_20260914.md) · commit `0764cd1`.

---

## Contrato observado nesta sessão (não regressar)

| ID | Gesto | Esperado | Obtido 29/09 |
|----|-------|----------|--------------|
| **EX=** | Cara séria / neutra, boca fechada | `predominantly_neutral` | ✅ Aprovado (humano) |
| **EX+** | Sorriso sustentado (com dentes) | `predominantly_positive` via `fer_onnx` + `smile_boost` | ✅ Aprovado (humano) |

**Proibido que volte:**

- Sorriso longo/visível sempre neutro (`smile_boost` off, VGAF no overlay TRI, ou landmarks corrompidos).
- Cara séria virando positiva por “melhoria” experimental de limiares.
- Desligar o **lock** do `FaceLandmarker.detect` sem reteste EX+.

---

## Como reproduzir o resultado (checklist operacional)

```powershell
cd "_facial_enroll_prod"   # árvore produto
.\venv\Scripts\Activate.ps1
.\scripts\boot_edge_m2.ps1 -SkipFrontendBuild
# Confirmar no log: PRESENCA_CONFIG_OVERLAY=config.tri.yaml
```

1. Abrir http://127.0.0.1:8000/debug/vision  
2. Confirmar identidade (ex.: `p01` / Emerson) e qualidade de observação adequada.  
3. **EX=:** cara séria ~10–15 s → card **expressão predominantemente neutra**.  
4. **EX+:** sorriso com dentes sustentado (contrato histórico ~8 s) → **predominantemente positiva** (`smile_boost` landmarks / landmarks_mouth / pixels_teeth).  
5. Voltar ao sério → neutra de novo.

Ferramenta de auditoria (opcional): `python scripts/_guided_ex_pw.py`  
(Playwright headed + API + prints em `results/ex_plus_pw_guided/` — **sempre** tirar frames no meio do sorriso e conferir visualmente).

---

## Números YAML TRAVADOS (não “melhorar” sem reteste)

Fonte: `config.tri.yaml` = [`VALORES_CONGELADOS_LIVE_20260914.md`](VALORES_CONGELADOS_LIVE_20260914.md)

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

**Proibido no overlay TRI:** `emotion_backend: hsemotion_vgaf` (já quebrou sorriso→negativa).

### Limiares geométricos do `smile_boost` (código — commit congelado `0764cd1` / HEAD produto)

Em `app/pipeline/analytics_track.py` → `_compute_expression`:

| Path | Condição (resumo) |
|------|-------------------|
| `landmarks` | `ear ≥ 0.15` · `smile_lm ≥ 0.50` · `frown < smile_lm * 0.85` |
| `landmarks_mouth` | `smile_lm ≥ 0.48` · `0.12 ≤ mouth ≤ 0.55` · `frown < 0.30` |
| `pixels_teeth` | `smile_px ≥ 0.55` · `mouth ≥ 0.14` · `smile_lm ≥ 0.28` · `frown < 0.35` |

Com boost ativo: forçar `smoothed = predominantly_positive` (ver `docs/TROUBLESHOOTING.md` — “Sorriso pisca inconclusivo”).

Geometria `app/vision/facial_signals.py` → `_smile_from_landmarks` (lift/width/mouth_aspect) — **não** alterar cliffs sem reteste.

---

## Patch obrigatório desta recuperação (além do YAML 14/09)

### Problema

- Playwright + prints provaram sorriso **com dentes** na câmera.  
- API live reportava `smile_score ≈ 0`, `mouth_open ≈ 0.01`, `smile_boost=none`, card neutro.  
- O **mesmo frame** analisado offline com `analyze_face_roi` dava `smile_score ≈ 0.88`, `mouth ≈ 0.25`.  
- Conclusão: fórmula/YAML ok; **landmarks live corrompidos**.

### Causa

`mediapipe` `FaceLandmarker.detect` **não é thread-safe**. O Edge chama `analyze_face_roi` a partir de `ThreadPoolExecutor` (orchestrator / analytics). Detect concorrente → scores de boca/sorriso zerados intermitentemente.

### Correção (manter)

Arquivo: `app/vision/facial_signals.py` · função `analyze_face_roi`

```python
# FaceLandmarker.detect NÃO é thread-safe; Edge usa ThreadPoolExecutor.
# Sem lock: landmarks corrompidos → smile/mouth ~0 com sorriso real na câmera.
with _landmarker_lock:
    result = landmarker.detect(mp_img)
```

`_landmarker_lock` já existia para create; o detect **também** deve usá-lo.

### O que NÃO fazer de novo

Experimentos que **saíram** do congelamento e quebraram EX+ nesta sessão (revertidos antes da aprovação):

- Baixar limiares de enter / histerese mouth-closed custom  
- `expression.interval_seconds: 0.5`  
- Dwell artificial 2.5 s antes de forçar positiva  
- Alterar cliffs de `_smile_from_landmarks` (lift 0.18 etc.)

Esses caminhos causaram oscilação neutro↔positivo e mascararam o bug real (race do landmarker).

---

## Arquivos sensíveis (não editar sem reteste EX+/EX=)

| Arquivo | Papel |
|---------|--------|
| `config.tri.yaml` | Overlay TRI — smile_boost + fer_onnx + intervalos |
| `app/pipeline/analytics_track.py` | `_compute_expression` / smile_boost / smooth |
| `app/vision/facial_signals.py` | landmarks, smile/mouth, **lock do detect** |
| `app/vision/landmarks_adapter.py` | bridge ROI → FacialFeatures |
| `app/vision/emotion_engagement.py` | heurística pixel smile |
| `app/vision/expressions/*` | provider `fer_onnx` |
| `app/static/debug_vision.html` | card expressão (poll) |
| `docs/VALORES_CONGELADOS_LIVE_20260914.md` | números oficiais |

---

## Evidências desta sessão

| Tipo | Onde / o quê |
|------|----------------|
| Aprovação humana | Emerson — neutro e positivo OK após fix do lock + restore do baseline |
| Diagnóstico | Prints `results/ex_plus_pw_guided/mid_smile_*.png` (sorriso visual vs card neutro) |
| Offline vs live | crop do print → `smile≈0.88`; API no mesmo instante → `smile=0` |
| Tooling | `scripts/_guided_ex_pw.py` (Playwright + API + mid-frames) |
| Marco Git histórico | `0764cd1` *Congela H/J/K/EX+ LIVE 2026-09-14* |
| Branch marco TRI | `tri/congelado-baseline-validado` |

---

## KEEP / ROLLBACK

**KEEP**

- `fer_onnx` + `smile_boost_enabled: true` no `config.tri.yaml`  
- Limiares smile_boost do commit `0764cd1`  
- Lock em `FaceLandmarker.detect`  
- Boot com `PRESENCA_CONFIG_OVERLAY=config.tri.yaml`

**ROLLBACK se alguém “melhorar” expressão**

1. Restaurar `config.tri.yaml` pelos valores da tabela acima.  
2. Restaurar bloco smile_boost / `_smile_from_landmarks` do commit `0764cd1` (ou tag desta revalidação).  
3. Garantir o `with _landmarker_lock` no `detect`.  
4. Retestar EX= e EX+ na webcam com `/debug/vision`.

---

## Relação com outros cenários TRI

Esta sessão **só** refechou **EX+ / EX=**.  
H, J, K, celular, etc. continuam no contrato LIVE 14/09 — não foram o alvo do take 29/09.
