# Relatório — Benchmark de robustez a óculos / aparência (Módulo 2 POC)

**Data:** 2026-09-21  
**Escopo:** exclusivamente `experiments/smoke_e2e_sentimentos/modulo2_poc/`  
**Threshold experimental:** T=0.70 · M=0.10  
**Alignment:** `product_crop_aligned_face` (112×112) — sem fallback crop+resize  

---

## 1. Objetivo

Responder com evidência:

> Qual estratégia mantém melhor o reconhecimento correto quando a aparência muda (especialmente óculos), sem aumentar falsos positivos?

Comparar FaceNet × ArcFace ONNX × (AdaFace se viável) e a estratégia de **múltiplos templates**.

---

## 2. Baseline (já validado antes deste benchmark)

| Condição | FaceNet aligned_v2 | Resultado |
|----------|-------------------|-----------|
| Sem óculos (recognize) | scores ~0.96 | PASS |
| Óculos escuros ~2 m | streak 5/5 com oscilação | PASS |
| Óculos grau ~2 m (retry completo) | 28/30 UNKNOWN | FAIL |
| UNKNOWN (outra pessoa) | scores ~0.36–0.41 | PASS |
| Multi-pessoa lab01+lab02 ~2 m | ambos ID, margem ~0.41–0.55 | PASS |
| 1–3 m sem óculos | PASS | — |
| 4 m | PASS com oscilação | — |

Galerias legadas **preservadas**: `gallery_temp/facenet/`, `gallery_temp/facenet_aligned_v2/`.

---

## 3. Modelos testados

| Modelo | Status | Onde |
|--------|--------|------|
| **FaceNet** (vggface2, 512D) | TESTADO | já no POC |
| **ArcFace ONNX** w600k_r50 | TESTADO (somente pesquisa POC) | `modulo2_poc/models/w600k_r50.onnx` |
| **AdaFace** | **NÃO TESTADO** | não baixado |

---

## 4. Licenças

| Artefato | Licença / restrição |
|----------|---------------------|
| InsightFace **código** | MIT |
| Pesos **buffalo_l / w600k_r50** | **Non-commercial research only**; comercial exige contato `recognition-oss-pack@insightface.ai` |
| AdaFace **código** | MIT |
| AdaFace **pesos** (WebFace4M/12M) | Seguir licença do dataset de treino; HF CVLFace: *“follow the license of the training dataset”* — **código ≠ pesos ≠ uso comercial** |

**Decisão AdaFace:** sem segurança comercial suficiente → **não baixar, não instalar, NÃO TESTADO**.

**Decisão ArcFace neste POC:** permitido apenas como experimento de pesquisa isolado; **não** candidato a produção sem licença comercial.

---

## 5. Metodologia

1. Mesmos crops alinhados (`crops_aligned_v2`) → embeddings separados por modelo em `gallery_temp/benchmark_occlusion/{facenet,arcface}/`.
2. Offline: leave-one-out + cross-ID (esperado UNKNOWN).
3. Multi-pessoa simulado: fronts lab01+lab02 na galeria completa.
4. Importação das medições físicas FaceNet já feitas (óculos/dist/unknown/multi).
5. Novos probes com óculos de grau capturados via `benchmark_occlusion_capture_probes.py` (alignment produto).
6. Multi-template **justo**: template = captura `_01`; probes = `_02` e `_03` (sem self-match).

Scripts:

- `scripts/benchmark_occlusion_common.py`
- `scripts/benchmark_occlusion_build_gallery.py`
- `scripts/benchmark_occlusion.py`
- `scripts/benchmark_occlusion_capture_probes.py`

Evidência: `results/benchmark_occlusion/SUMMARY_latest.json`, `MULTI_TEMPLATE_FAIR.json`.

---

## 6. Condições

| Condição | FaceNet live | FaceNet offline/probes | ArcFace | AdaFace |
|----------|--------------|------------------------|---------|---------|
| Sem óculos (crops enroll) | — | TESTADO | TESTADO | NÃO |
| Óculos escuros ~2 m | TESTADO (PASS oscilante) | — | NÃO TESTADO (sem probes ArcFace na sessão live) | NÃO |
| Óculos grau ~2 m live | TESTADO (FAIL) | — | NÃO TESTADO live | NÃO |
| Óculos grau (probes capturados, bbox~220 px ≈ mais perto) | TESTADO | TESTADO | TESTADO | NÃO |
| 1 / 2 / 3 m sem óculos | TESTADO (live FaceNet) | — | NÃO TESTADO live | NÃO |
| UNKNOWN | TESTADO FaceNet | offline cross-ID | offline cross-ID | NÃO |
| Multi-pessoa | TESTADO FaceNet live | sim enroll | sim enroll | NÃO |

**Nota:** probes novos de óculos grau tiveram bbox ~224×310 (mais próximos que o live ~2 m com bbox ~100). Não confundir com o FAIL live a 2 m.

---

## 7. Resultados FaceNet

### 7.1 Offline (LOO + cross-ID) — sem óculos

- n=10 · correct_rate=**1.0** · FP=0 · FN=0  
- UNKNOWN=2 (são os 2 casos cross-ID esperados)  
- score mean≈0.79 · margin mean≈0.58  

### 7.2 Live (importado)

| Condição | Resultado | Observação |
|----------|-----------|------------|
| Recognize | PASS | ~0.96 |
| Óculos escuros 2 m | PASS | oscilação |
| Óculos grau 2 m retry | FAIL | score tipicamente 0.54–0.69 |
| UNKNOWN | PASS | ~0.38 |
| Multi lab01+lab02 | PASS | margem alta |

### 7.3 Probes óculos grau (captura nova)

Galeria default (só sem óculos): correct_rate≈0.75 (1 FN).  
Com template de óculos (fair): ver §10.

---

## 8. Resultados ArcFace

### 8.1 Offline (mesmos crops) — sem óculos

- n=10 · correct_rate=**1.0** · FP=0  
- margin mean≈**0.69** (maior que FaceNet nestes crops)  
- Scores absolutos **não** são comparáveis 1:1 com FaceNet  

### 8.2 Probes óculos grau × galeria sem óculos

- **4/4 UNKNOWN** (FN) · scores ~0.63–0.68 (abaixo de 0.70)  
- Pior que FaceNet nestes probes  

### 8.3 Live distância/óculos escuros com ArcFace

**NÃO TESTADO** nesta etapa (não houve sessão live dedicada ArcFace).

---

## 9. Resultados AdaFace

**NÃO TESTADO** — bloqueio de licença/pesos (ver §4).

---

## 10. Múltiplos templates (evidência principal)

Arquivo: `results/benchmark_occlusion/MULTI_TEMPLATE_FAIR.json`  
Template óculos = captura `_01`; avaliação = `_02` e `_03`.

| Modelo | Galeria só sem óculos | Galeria + 1 template com óculos |
|--------|----------------------|----------------------------------|
| FaceNet | 1/2 correto (0.50) · 1 UNKNOWN | **2/2 correto (1.0)** · scores 0.79–0.93 |
| ArcFace | 0/2 correto · 2 UNKNOWN | **2/2 correto (1.0)** · scores 0.74–0.90 |

**Interpretação (factual):**

- Sem baixar threshold, **um template adicional com óculos de uso** recuperou os FNs nestes probes.  
- Não prova que todo aluno precise de template com óculos; prova que **a variação de aparência pode ser atenuada por template**, para FaceNet e ArcFace.  
- Self-match (mesmo crop na galeria) foi **excluído** deste teste justo.

---

## 11. UNKNOWN

| Fonte | FaceNet | ArcFace |
|-------|---------|---------|
| Live (outra pessoa) | PASS · score≪0.70 | NÃO TESTADO live |
| Offline cross-ID | PASS (esperado UNKNOWN) | PASS |

Nenhuma evidência de FP de identidade no offline deste harness.

---

## 12. Multi-pessoa

| Fonte | FaceNet | ArcFace |
|-------|---------|---------|
| Live ~2 m | PASS lab01+lab02 | NÃO TESTADO live |
| Sim fronts enroll | both_correct=true · margem ~0.62 | both_correct=true · margem ~0.85 |

---

## 13. Comparação (sem “score maior = melhor”)

| Critério | FaceNet | ArcFace (POC pesquisa) | AdaFace |
|----------|---------|------------------------|---------|
| ID correta sem óculos | Excelente | Excelente | — |
| Óculos grau live ~2 m | FAIL estável | NÃO TESTADO | — |
| Óculos grau probes (mais perto) | Melhor sem template | Pior sem template | — |
| Com +1 template óculos | Recupera | Recupera | — |
| UNKNOWN | OK (live+offline) | OK offline | — |
| Multi-ID margem | OK | OK (maior no sim) | — |
| Licença comercial pesos | Já no produto | **Não** (buffalo_l) | Insegura |
| Custo | Já validado CPU | ONNX CPU ~174 MB | — |

---

## 14. Limitações

1. ArcFace **não** repetiu a bateria live 1/2/3 m e óculos escuros.  
2. Probes novos de óculos grau não são a mesma distância do FAIL live (~2 m / bbox~100).  
3. Amostra de multi-template justa: **n=2 probes** (lab01).  
4. lab02 sem template de óculos.  
5. Score FaceNet ≠ score ArcFace (escalas diferentes).  
6. Pesos ArcFace **não comerciais** sem acordo InsightFace.

---

## 15. Conclusão

### Cenário indicado: **A (parcial) + cautela**

- **FaceNet + estratégia de templates** mostrou recuperação clara nos probes de óculos grau **sem** reduzir threshold e **sem** FP nas provas offline.  
- **Trocar para ArcFace agora não se justifica** para produção:  
  - pior nos probes de óculos sem template;  
  - pesos buffalo_l não comerciais;  
  - sem evidência live superior sob óculos/distância.  
- **AdaFace:** permanece fora até haver pesos com licença comercial clara.  
- O FAIL live a ~2 m com óculos grau **continua real** para galeria só sem óculos; o próximo passo operacional do enrollment deve considerar **opcionalmente** um template com óculos de uso, não troca de embedder.

Isto **não** fecha VIP-5440 física; fecha a pergunta tecnológica deste POC com evidência suficiente para **não migrar embedder** neste momento.

---

## 16. Recomendação — próximo passo do Módulo 2

1. **Manter FaceNet** no caminho do Enrollment Escalável.  
2. Documentar UX/processo: *se o aluno usa óculos no dia a dia, capturar 1 template adicional com óculos* (opcional, baseado em evidência).  
3. **Não** integrar ArcFace/AdaFace no produto nesta etapa.  
4. Opcional (ainda no POC): sessão live ArcFace só para óculos grau a 2 m / 3 m — se quiser fechar o gap “NÃO TESTADO”.  
5. Depois: validação física VIP-5440, sem alterar M1/M3/TRI.

---

## 17. Proteção dos módulos fechados

```
git diff -- app/vision config.tri.yaml
```

- `config.tri.yaml`: **sem diff** nesta etapa.  
- `app/vision/phone_yolo.py`: diff **pré-existente** (não tocado por este benchmark).  
- Modelo ONNX baixado **somente** em `modulo2_poc/models/` (não em `data/onnx_models`).  
- Sem escrita em `face_embeddings`, sem `reload_matcher`, sem commit.  
- M1 / M3 / LXP / SyncWorker / TRI: não alterados.

---

## Entrega resumida (checklist do pedido)

1. **Modelos testados:** FaceNet, ArcFace ONNX (POC); AdaFace NÃO TESTADO.  
2. **Resultados:** ver §§7–12 e JSONs.  
3. **Condições:** ver §6.  
4. **FaceNet × ArcFace × AdaFace:** §13.  
5. **Multi-templates:** §10 — recupera FNs.  
6. **UNKNOWN:** OK FaceNet live + offline ambos.  
7. **Multi-pessoa:** FaceNet live PASS; sim ambos OK.  
8. **Licenças:** §4.  
9. **Limitações:** §14.  
10. **Recomendação:** Cenário A (FaceNet + templates opcionais); não migrar produção.
