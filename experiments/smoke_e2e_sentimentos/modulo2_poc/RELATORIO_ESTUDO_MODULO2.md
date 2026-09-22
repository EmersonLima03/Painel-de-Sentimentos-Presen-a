# RELATÓRIO — Estudo técnico Módulo 2 (Enrollment escalável)

**Data:** 2026-09-21  
**Escopo:** auditoria + pesquisa + POC isolado  
**Pasta:** `experiments/smoke_e2e_sentimentos/modulo2_poc/`  
**Prioridade de produto:** Estratégia **A** (enrollment guiado e automatizado)  
**Não é:** cadastro definitivo, integração ao produto, commit  

Legenda: **FATO** | **TESTADO** | **NÃO TESTADO** | **NÃO CONFIRMADO** | **HIPÓTESE** | **RECOMENDAÇÃO**

---

## 1. Estado atual do enrollment

**FATO (código):**

| Item | Valor | Fonte |
|------|-------|--------|
| Serviço | `EnrollmentService` | `app/enroll/service.py` |
| API | `POST /enroll`, `/enroll/webcam`, `/enroll/webcam/preview` | `app/main.py` |
| UI | `GET /debug/enroll` (HTML; `ENABLE_DEBUG_UI`) | `app/main.py` |
| Fluxo webcam | N frames (~20) em ~5 s → top qualidade (~12) → média → 1 template | `config.yaml` `enrollment.*` |
| Multi-amostra | `append_template=true` (manual, sequencial) | service |
| Max templates | 7 | `vision.presence.max_templates_per_student` |
| Quality gate | `min_quality_score=0.45`, `min_good_frames=3` | service/API |
| React | `enrollStudent` = matrícula escolar, **não** biometria | frontend |

**FATO:** Não há orientação automática de pose (“vire à direita”) no produto hoje.

**NÃO TESTADO:** tempo médio por aluno em turma real; taxa de rejeição do quality gate em VIP-5440.

---

## 2. Arquitetura atual de reconhecimento

```
frame → YuNet (+landmarks) → crop_aligned_face 112 → embedder → FAISS IndexFlatIP
     → score + margin → student_id | UNKNOWN
```

| Camada | Implementação | Fonte |
|--------|---------------|--------|
| Detector | `yunet` | `config.yaml` |
| Align | ArcFace refs 112, 5pts | `app/vision/face_alignment.py` |
| Quality | size/blur/brightness/contrast | `app/vision/quality.py` |
| Embedder produto | `facenet` 512D | `config.yaml` |
| Alternativa código | ONNX ArcFace `w600k_r50` | `app/vision/onnx_embedder.py` |
| Storage | SQLite `face_embeddings` | `app/db/models.py` |
| Índice | FAISS em memória (não disco) | `app/vision/matcher.py` |
| Check-in | threshold **0.70**, margin **0.10** | `config.yaml` |
| Display | th_on **0.75**, th_off **0.68** | `config.yaml` |
| Binding | IdentityBinding (não grava presença) | `app/vision/identity_binding.py` |

**FATO:** Matching é **1:N open-set**, não 1:1 com ID informado.

**FATO:** Cloud sync **não** sobe embeddings (`SYNC_CONTRACT`).

---

## 3. Problemas do modelo atual para escala

| Problema | Tipo | Nota |
|----------|------|------|
| Cadastro 1-a-1 manual multi-sessão | operacional | Não escala turma |
| Sem guiamento automático de pose | produto | Operador decide “quando” capturar |
| `single_subject_mode: true` no lab | config lab | Desenho TRI 1 pessoa; sala real precisa multi |
| FaceNet × N faces (CPU/torch) | desempenho | **HIPÓTESE** de custo; latência sala **NÃO TESTADA** |
| VIP-5440 sem validação de campo | hardware | RTSP placeholder no config |
| Misturar FaceNet e ArcFace na mesma galeria | risco técnico | Espaços de embedding diferentes |

---

## 4. Tecnologias candidatas (resumo)

| Candidato | Papel no estudo |
|-----------|-----------------|
| YuNet | Detector já em uso |
| FaceNet | Baseline produto |
| ArcFace / InsightFace ONNX `w600k_r50` | Challenger 1 (isolado) |
| OpenCV SFace | Challenger 2 (licença Apache-2.0 no Zoo) |
| ONNX Runtime | Runtime de inferência |
| DeepFace | Wrapper multi-modelo (doc) |
| CompreFace | Serviço Docker separado (doc) |

---

## 5. Comparação técnica

| Critério | FaceNet (atual) | ArcFace ONNX | SFace | InsightFace full | DeepFace | CompreFace |
|----------|-----------------|--------------|-------|------------------|----------|------------|
| Embedding | 512D | 512D | ~128D típ. | 512D | dependee | API |
| Detector | YuNet (sep.) | YuNet (sep.) | YuNet típ. | Retina/SCRFD | vários | embutido |
| CPU Edge | usado hoje | ORT CPU | leve | mais pesado | variável | servidor |
| GPU | possível torch | ORT CUDA | OpenCV | sim | sim | docker GPU |
| Integração nossa | já ligada | caminho código existe | nova | médio | fácil wrap | HTTP extra |
| Maturidade | alta em lab | alta FR literature | boa Zoo | alta | alta wrap | produto OSS |
| Servidor extra | não | não | não | não | não | **sim** |
| Métricas neste POC | **NÃO TESTADO** | **NÃO TESTADO** | **NÃO TESTADO** | doc | doc | doc |

Não se declara vencedor de acurácia sem corpus.

---

## 6. Questões de licença

**Regra:** licença do código ≠ licença do modelo/pesos ≠ permissão comercial.

| Item | Código | Pesos / modelo | Uso comercial | Fonte |
|------|--------|----------------|---------------|--------|
| **InsightFace** | MIT (comercial OK) | Pretrained **research non-commercial**; buffalo_l exige contato `recognition-oss-pack@insightface.ai` | Pesos: **não livres** sem licença | [README InsightFace](https://github.com/deepinsight/insightface/blob/master/README.md), [insightface.ai](https://www.insightface.ai/) |
| **w600k_r50 / buffalo_l** | (via InsightFace) | Mesma política pretrained | **Licença comercial necessária** para empresa | idem; download usado em `onnx_embedder.py` |
| **YuNet** (OpenCV Zoo) | MIT no diretório do modelo | MIT | **OK** com atribuição MIT | [opencv_zoo face_detection_yunet](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet) |
| **SFace** (OpenCV Zoo) | Apache-2.0 | Apache-2.0 | **OK** com termos Apache (aviso/atribuição) | [face_recognition_sface LICENSE](https://github.com/opencv/opencv_zoo/blob/master/models/face_recognition_sface/LICENSE) |
| **ONNX Runtime** | MIT (Microsoft) | n/a (runtime) | **OK** | [microsoft/onnxruntime LICENSE](https://github.com/microsoft/onnxruntime/blob/main/LICENSE) |
| **DeepFace** | MIT | **Herda** licenças dos modelos wrapped | **Depende do modelo** escolhido | [serengil/deepface](https://github.com/serengil/deepface/) |
| **CompreFace** | Apache-2.0 | Pode incluir/baixar modelos InsightFace | Código OK; **pesos InsightFace: risco** | [CompreFace LICENSE](https://github.com/exadel-inc/CompreFace/blob/master/LICENSE); issue #1233 sem resposta definitiva |
| **FaceNet / facenet-pytorch / VGGFace2** | código tipicamente MIT/BSD nos wrappers | Dados VGGFace2 / pesos | **NÃO CONFIRMADO** neste estudo (revisar dataset + pesos antes de escalar comercial) | Requer due diligence jurídica |

**Implicação crítica:** Challenger ArcFace ONNX **não** pode ser promovido a produção comercial só porque o código MIT existe. POC técnico ≠ liberação jurídica.

---

## 7. Proposta de benchmark

Condições A–K em `manifests/conditions_A_K.csv`.

Scripts:

1. `bench_gallery_offline.py` — 1:N em galeria TEMP  
2. `bench_candidates_isolated.py` — disponibilidade FaceNet / ArcFace / SFace  
3. `capture_distance_probe.py` — px × distância  

Separar sempre galerias por embedder.

---

## 8. Proposta de POC

Pasta isolada (este diretório). Fluxo:

```
CAPTURA → detect → quality → align → embedding(candidatos) → galeria TEMP → 1:N → ID|UNKNOWN
```

Enrollment estudado: **Estratégia A** (ver §9).

Não chama `reload_matcher`; não escreve DB produção.

---

## 9. Estratégias de enrollment avaliadas

### A — Guiado e automatizado (**PRIORIDADE**)

| Dimensão | Avaliação |
|----------|-----------|
| Fluxo | Operador escolhe aluno → orientações → detect/quality → captura auto → 2ª pose → 3ª se necessário → validação → confirma → próximo |
| Tempo/aluno | **HIPÓTESE** 30–90 s; **NÃO TESTADO** |
| Embeddings | Poucos, alta qualidade (N definido por dados, não presumido) |
| Intervenção | Operador + sistema; baixa carga de “clicar captura” |
| Qualidade esperada | Alta (gates obrigatórios) — a validar |
| Riscos | Rejeições frequentes se posicionado mal; frustração se UX ruim |
| Turma | Sequencial por aluno (escala operacional boa) |
| Óculos | Pedir amostra com óculos se uso diário |
| Multi-câmera | Cadastro preferencialmente numa câmera “enroll”; runtime multi = fase posterior |
| Revisão | Confirmação explícita antes de gravar |
| Complexidade | Média (UI estado + quality + pose hints) |

### B — Lote

Risco alto de associação identidade↔rosto. Documentar apenas; **não priorizar**.

### C — Híbrido (enriquecimento posterior)

Alternativa **futura**: poucas amostras + enriquecimento controlado em aula.  
**Não** é a estratégia principal agora (qualidade de vínculo no dia 1 primeiro).

---

## 10. Estratégia recomendada para teste

**RECOMENDAÇÃO:** implementar e testar primeiro a **Estratégia A** no POC/UX experimental (ainda fora do produto), com:

- quality gate obrigatório;
- 2 capturas mínimas + 3ª condicional (critério a calibrar);
- confirmação humana por aluno;
- galeria TEMP.

**Não** declarar ainda o embedder definitivo de produção.

**RECOMENDAÇÃO técnica paralela:**

1. Manter FaceNet como baseline mensurável.  
2. Preparar SFace (Apache-2.0) como challenger comercialmente mais limpo.  
3. ArcFace `w600k_r50` só em bancada **após** alinhamento jurídico InsightFace (ou pesos com licença clara).

---

## 11. Arquitetura proposta (próxima etapa — não implementada agora)

```
UI Enrollment A (nova; fora de vision)
  → EnrollmentService (evolução) OU serviço POC
  → FacePipeline atual (read-only) para baseline
  → (futuro) embedder escolhido pós-benchmark + legal
  → face_embeddings + reload_matcher (só quando aprovado integrar)
```

TRI / emoções / LXP / M1 / M3: intocados.

---

## 12. Dados que precisamos coletar

- Corpus consentido: ≥10 identidades, front/lateral/óculos/distâncias.  
- Logs VIP-5440 (`camera_vip5440_log.csv`).  
- Pares genuínos/impostores para T/M.  
- UNKNOWN forçado (fora da galeria).  
- Medidas de px vs metros na sala ~36 m².

---

## 13. Critérios objetivos de aprovação (definição)

Ver `PROTOCOL_THRESHOLD.md` e `PROTOCOL_CAMERA_VIP5440.md`.

Números finais de T/M e px mínimo: **após** dados (não inventados aqui).

Referência de partida (produção, só leitura): 0.70 / 0.10.

---

## 14. O que será FAIL

- FP de identidade em conjunto de teste acordado.  
- Aceitar amostra abaixo do quality gate.  
- Associar rosto ao aluno errado na Estratégia A.  
- Declarar VIP-5440 OK sem medição.  
- Promover buffalo_l a produção sem licença comercial.

---

## 15. O que será PASS

- Enrollment A: capturas válidas, associação correta, rejeição de inválidas, fluxo repetível.  
- Recognition: TP com score+margin; UNKNOWN correto fora da galeria; FP≈0 no conjunto.  
- Câmera: px e detecção nas zonas relevantes dentro dos limiares acordados pós-medição.

---

## 16. O que ainda depende de teste físico

- VIP-5440-IA + RTSP real + sala ~36 m²  
- FOV, zonas cegas, multi-pessoa, iluminação  
- Calibração de N capturas da Estratégia A  
- Benchmark FaceNet vs SFace vs (ArcFace se licença OK)  
- Due diligence FaceNet/VGGFace2 comercial  

---

## Respostas finais A–F

### A) O que já temos
Pipeline completo de enroll/match; UI debug; multi-template; quality/align; FAISS; thresholds; caminho ONNX ArcFace no código; YuNet MIT; SFace Apache no Zoo.

### B) O que podemos reaproveitar
`app/enroll/service.py` (fluxo/API), quality gates, alinhamento 112, matcher 1:N+margin, UI `/debug/enroll` como referência UX — **sem editar `app/vision/**` nesta etapa**.

### C) O que precisamos testar
Condições A–K; VIP-5440; T/M; N de capturas da Estratégia A; SFace vs FaceNet; latência multi-rosto.

### D) Arquitetura a testar primeiro
**Estratégia A** + baseline FaceNet (read-only) + challenger SFace (licença clara) + ArcFace só com gate jurídico.

### E) POC a executar primeiro
1) Scaffold (este pacote)  
2) `bench_candidates_isolated` / `bench_gallery_offline` com corpus TEMP  
3) Protocolo VIP-5440 quando hardware disponível  

### F) Equipamentos / dados necessários
VIP-5440 + credencial RTSP; marcações de distância; participantes consentidos; mini-PC/notebook; opcional 2ª câmera; venv POC; decisão jurídica sobre buffalo_l / FaceNet weights.

---

## Execução desta entrega (2026-09-21)

| Ação | Resultado |
|------|-----------|
| Scaffold `modulo2_poc/` | Criado |
| Scripts rodados sem corpus | Ver `results/*.json` — status **NÃO TESTADO** onde aplicável |
| VIP-5440 probe | **NÃO TESTADO** (sem captura física nesta execução) |
| TRI / M1 / M3 / visão | Intocados (sem edits em `app/vision/**` nem `config.tri.yaml`) |

**Conclusão:** não escolhemos modelo definitivo de produção. A próxima etapa aprovável é: coletar corpus + medir VIP-5440 + comparar FaceNet×SFace (e ArcFace se licença OK) sob Estratégia A.

---

## Adendo 2026-09-21 — Lab XWF-1080P

Camada de execução física preparada **sem** alterar o produto:

- `RUNBOOK_TESTES_XWF.md` — passo a passo operador
- `PROTOCOL_XWF_1080P.md` — escopo lab vs VIP
- `scripts/run_enroll_guided_a.py` — Estratégia A automatizada → galeria TEMP
- `scripts/run_recognize_probe.py` — distância/pose/óculos/UNKNOWN
- `scripts/run_multiperson_probe.py` — multi-rosto só no POC
- `scripts/list_webcams.py` — índice USB

Respostas A–F (quantas capturas, distância máxima, etc.): **NÃO TESTADO** até você executar o runbook com a XWF.

---

## UI de Enrollment Guiado — POC (2026-09-21)

### Implementado

| Item | Path |
|------|------|
| Servidor isolado | `scripts/ui_server.py` (FastAPI, porta **8765**) |
| UI | `ui/index.html`, `ui/styles.css`, `ui/app.js` |
| URL | http://127.0.0.1:8765/ |
| Playwright | `run_playwright_m2_ui.cjs` → `playwright_m2_ui.json` |
| Screenshots | `results/ui/01_initial.png` … `04_final.png` |

Fluxo visual Estratégia A: instruções humanas, quality pill, progresso, captura automática quando qualidade OK, galeria TEMP, reconhecimento / UNKNOWN / distância, painel técnico recolhido.

### Validado (Playwright)

- **UI = PASS** (11/11 no runner; shell exit 0)
- Título, área de câmera, progresso, instrução, badge TEMP, tech recolhido, tabela distância, botão UNKNOWN
- Start câmera: se indisponível → tratado; se disponível → phase front

### NÃO TESTADO / depende de físico

- Enrollment completo com 2 capturas automáticas (pessoa na XWF)
- Reconhecimento ID/UNKNOWN com evidência real de score/margin
- Tabela de distância preenchida com medições
- VIP-5440 (ainda fora)

### Separação explícita

| Camada | Status |
|--------|--------|
| UI | **PASS** |
| Fluxo técnico completo | **NÃO TESTADO** até sessão física |
| Reconhecimento | **NÃO TESTADO** sem evidência |
| XWF | lab ready; validação empírica pendente |
| VIP-5440 | **AINDA NÃO VALIDADA** |

### Como iniciar

```powershell
cd experiments\smoke_e2e_sentimentos\modulo2_poc
..\..\..\venv\Scripts\python.exe scripts\ui_server.py --port 8765
# Abrir http://127.0.0.1:8765/
```

Produto / M1 / M3 / TRI: **intocados**.

---

## VALIDAÇÃO F4 — E2E (2026-09-21)

### Escopo desta execução

Fechamento do **Enrollment Escalável A** (POC): campanha → QR → claim → sessão → captura → óculos opcional → completed → reconhecimento TEMP.

**Não** é homologação da VIP-5440 nem promoção a produção.

### Regressão automatizada (esta execução)

| Suite | Resultado |
|-------|-----------|
| F0 pytest | **15/15 PASS** |
| F1 pytest | **5/5 PASS** |
| F2 pytest | **13/13 PASS** |
| F3 pytest | **7/7 PASS** |
| F4 pytest (hooks: 2 IDs + óculos + UNKNOWN + gestor completed) | **1/1 PASS** |
| Playwright F1 / F2 / F3 | **ok: true** (sem regressão) |
| Total pytest F0–F4 | **41/41 PASS** |

### Já validado anteriormente (lab XWF / aligned_v2 — não reexecutado na F4)

| Evidência | Path | Resultado registrado |
|-----------|------|----------------------|
| Enrollment + recognize lab | `results/aligned_v2/SUMMARY.json` | PASS (lab01/lab02, product align) |
| Distância ~3 m | `results/aligned_v2/distance_3m/SUMMARY_3m.json` | conforme artefato |
| Distância ~4 m | `results/aligned_v2/distance_4m/SUMMARY_4m.json` | oscilante / conforme artefato |
| UNKNOWN | `results/aligned_v2/unknown_probe/SUMMARY_unknown.json` | **PASS** |
| Multi-pessoa | `results/aligned_v2/multiperson/SUMMARY_multiperson.json` | **PASS** (lab01+lab02) |
| Óculos / templates | `results/aligned_v2/glasses*` + `RELATORIO_BENCHMARK_OCULUSAO.md` | template habitual recupera; ArcFace pior |

### Validado nesta F4 (automatizado / harness)

| Item | Status |
|------|--------|
| Campanha + claim + sessão + CaptureSession | PASS (F0–F3 + F4 hooks) |
| Dois alunos completed no gestor (hooks) | PASS |
| Template `glasses_habitual` quando Sim | PASS (hooks) |
| Self-match FaceNet TEMP campanha + UNKNOWN sintético | PASS (`test_enrollment_f4.py`) |
| `product_db_written: false` / sem `reload_matcher` | PASS |
| Isolamento `app/vision` / `config.tri.yaml` | PASS (F4 não alterou; `phone_yolo.py` diff pré-existente) |

### Tentativa física USB nesta F4 (obrigatória — resultado observado)

Script: `scripts/f4_e2e_lab_physical.py --webcam 2 --auto --timeout 25`

| Pessoa | Status observado | Detalhe |
|--------|------------------|---------|
| Dulin | **FAIL** | `timeout_sem_completed`; ficou em `front`; 0 templates |
| Mae | **FAIL** | idem |
| Óculos | **NÃO TESTADO** | enrollment não chegou à pergunta |
| Recognize Dulin/Mae pós-campanha | **NÃO TESTADO** | galeria vazia |
| UNKNOWN físico | **NÃO TESTADO** | — |
| Multi-pessoa físico | **NÃO TESTADO** | — |

Artefato: `results/enrollment_escalavel/f4/F4_E2E_SUMMARY.json` — `verdict_poc: NÃO CONCLUÍDO`.

**Não** houve alteração silenciosa de pipeline/threshold para forçar PASS.

### Mobile celular (runbook)

Fluxo celular (`getUserMedia` + QR LAN) permanece descrito em `RUNBOOK_F3_FISICO.md` / comando F4 interativo:

```powershell
python scripts/f4_e2e_lab_physical.py --webcam 2
# ou servidor: python scripts/enrollment_gestor_server.py --host 0.0.0.0 --port 8766
```

**NÃO TESTADO** com celular real nesta sessão de agente (sem operador nas poses).

### Vereditos separados

| Camada | Veredito |
|--------|----------|
| **Enrollment escalável — POC (software + regressão)** | Stack F0–F4 automatizado **PASS**; E2E físico Dulin/Mae **pendente** → fechamento físico: **NÃO CONCLUÍDO** |
| **VIP-5440 / sala ~36 m²** | **VALIDAÇÃO PENDENTE** |
| **Produção** | **FORA DO ESCOPO** |

### Limitações restantes

1. Completar enrollment físico (USB lab interativo ou celular) com Dulin e Mae seguindo poses.
2. Repetir recognize / UNKNOWN / multi sobre a **galeria da campanha** após esses cadastros.
3. VIP-5440 em sala real — fora deste POC de enrollment escalável.
4. HTTPS/LAN para `getUserMedia` em alguns browsers móveis.

### Como retomar o físico (sem mudar arquitetura)

```powershell
cd experiments\smoke_e2e_sentimentos\modulo2_poc
python scripts/f4_e2e_lab_physical.py --webcam 2 --timeout 180
# Seguir prompts: Dulin, depois Mae; opcional --glasses-mae
```
