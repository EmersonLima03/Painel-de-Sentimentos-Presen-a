# RUNBOOK — Testes físicos XWF-1080P (Módulo 2 POC)

**Câmera de laboratório:** XWF-1080P USB (não substitui VIP-5440-IA).  
**Tudo isolado em:** `experiments/smoke_e2e_sentimentos/modulo2_poc/`  
**Não altera** produto, TRI, DB/FAISS de produção.

Abra PowerShell na pasta do POC:

```powershell
cd "c:\Users\dulin\OneDrive\Documentos\Teste de monitoramento\Presenca\experiments\smoke_e2e_sentimentos\modulo2_poc"
```

Se o projeto usa venv:

```powershell
..\..\..\.venv\Scripts\Activate.ps1
# ou: ..\..\..\venv\Scripts\Activate.ps1
```

---

## 0. Preparar sala

1. Conecte a **XWF-1080P** na USB.
2. Feche outros apps que usem a webcam (Teams, Zoom, `/debug/vision` do Edge se estiver aberto na mesma câmera).
3. Marque no chão com fita: **1 m, 2 m, 3 m, 4 m, 5 m** a partir da câmera.
4. Iluminação estável (anote: dia/noite/artificial).
5. Descubra o índice da câmera:

```powershell
python scripts\list_webcams.py
```

Anote o `index` com frame ~1920×1080. No lab costuma ser **2** (`cam-web` no `config.yaml`). Se for outro, troque `--webcam N` em todos os comandos.

---

## 1. TESTE — Distância (bbox px)

Para cada distância (1→5 m e máximo útil), posicione **1 pessoa** frontal e rode:

```powershell
python scripts\capture_distance_probe.py --webcam 2 --distance-m 1 --zona frente
python scripts\capture_distance_probe.py --webcam 2 --distance-m 2 --zona frente
python scripts\capture_distance_probe.py --webcam 2 --distance-m 3 --zona frente
python scripts\capture_distance_probe.py --webcam 2 --distance-m 4 --zona frente
python scripts\capture_distance_probe.py --webcam 2 --distance-m 5 --zona frente
```

Resultados: `manifests/camera_vip5440_log.csv` (mesmo CSV genérico) e `results/capture_distance_probe_last.json`.  
Se `SEM_FACE` / `NAO_TESTADO`, anote a distância máxima utilizável.

---

## 2. TESTE — Enrollment Estratégia A

Cadastre **apenas** o aluno de lab (ex. você):

```powershell
python scripts\run_enroll_guided_a.py --student-id lab01 --student-name "Lab" --webcam 2 --preview
```

Siga as mensagens no terminal/janela:

1. Frente → captura automática quando qualidade OK  
2. Leve direita → captura automática  
3. (Opcional) `--third` para esquerda  

Saída:

- Embeddings TEMP: `results/gallery_temp/facenet/lab01/*.npy`
- Crops: `results/crops/lab01/*.jpg`
- Sessão: `results/enroll_lab01.json`

**Não** grava no SQLite de produção.

Se falhar qualidade: aproxime-se, melhore luz, rode de novo.

---

## 3. TESTE — Reconhecimento por distância

Com `lab01` na galeria TEMP, afaste-se:

```powershell
python scripts\run_recognize_probe.py --webcam 2 --distance-m 1 --expected lab01 --pose front
python scripts\run_recognize_probe.py --webcam 2 --distance-m 2 --expected lab01 --pose front
python scripts\run_recognize_probe.py --webcam 2 --distance-m 3 --expected lab01 --pose front
python scripts\run_recognize_probe.py --webcam 2 --distance-m 4 --expected lab01 --pose front
python scripts\run_recognize_probe.py --webcam 2 --distance-m 5 --expected lab01 --pose front
```

Log: `results/xwf_recognize_log.csv` + JSON por distância.

Thresholds `--threshold 0.70 --margin 0.10` são **experimentais do POC** (iguais aos de referência de produção, mas **não** alteram o YAML).

---

## 4. TESTE — Pessoa não cadastrada (obrigatório)

Outra pessoa na frente (ou você sem estar em `expected`):

```powershell
python scripts\run_recognize_probe.py --webcam 2 --distance-m 2 --expected UNKNOWN --pose front
```

Esperado: `decision=UNKNOWN`. Se vier `lab01` → **falso positivo** — anote score/margin.

---

## 5. TESTE — Óculos

```powershell
python scripts\run_recognize_probe.py --webcam 2 --distance-m 2 --expected lab01 --glasses no --pose front
python scripts\run_recognize_probe.py --webcam 2 --distance-m 2 --expected lab01 --glasses yes --pose front
```

Opcional: re-enroll com óculos usando uma segunda sessão (`--student-id lab01_glasses`) se quiser comparar galerias — ainda TEMP.

---

## 6. TESTE — Pose

```powershell
python scripts\run_recognize_probe.py --webcam 2 --distance-m 2 --expected lab01 --pose front
python scripts\run_recognize_probe.py --webcam 2 --distance-m 2 --expected lab01 --pose yaw_left
python scripts\run_recognize_probe.py --webcam 2 --distance-m 2 --expected lab01 --pose yaw_right
python scripts\run_recognize_probe.py --webcam 2 --distance-m 2 --expected lab01 --pose pitch_up
python scripts\run_recognize_probe.py --webcam 2 --distance-m 2 --expected lab01 --pose pitch_down
```

(Ajuste a cabeça antes de cada comando; o script captura um frame.)

---

## 7. TESTE — Multi-pessoa

1, 2, 3, 4 pessoas no quadro:

```powershell
python scripts\run_multiperson_probe.py --webcam 2 --n-expected 1 --preview
python scripts\run_multiperson_probe.py --webcam 2 --n-expected 2 --preview
python scripts\run_multiperson_probe.py --webcam 2 --n-expected 3 --preview
python scripts\run_multiperson_probe.py --webcam 2 --n-expected 4 --preview
```

`single_subject_mode` do **produto** não é alterado. Este script detecta todos os rostos só no POC.

---

## 8. TESTE — Falso positivo / margin

Duas pessoas parecidas (se possível): uma cadastrada, outra não.

```powershell
python scripts\run_recognize_probe.py --webcam 2 --distance-m 2 --expected UNKNOWN
```

Anote `top1_score` e `margin` mesmo quando UNKNOWN — útil para calibrar T/M no POC.

---

## Depois dos testes

Preencha mentalmente (ou anote) as perguntas A–F; resultados reais ficam nos JSON/CSV.  
Itens sem execução = **NÃO TESTADO**.

**VIP-5440-IA:** repetir o mesmo protocolo (`PROTOCOL_CAMERA_VIP5440.md`) quando o hardware chegar — FOV/sala/36 m² não são validados pela XWF.
