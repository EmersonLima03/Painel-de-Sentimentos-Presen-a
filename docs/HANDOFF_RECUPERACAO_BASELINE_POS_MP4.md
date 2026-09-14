# Handoff — Recuperar baseline TRI após rodada MP4→LIVE

**Para:** agente / chat que vai corrigir o produto  
**De:** validação manual + análise crítica (chat baseline + relatório 2026-09-11)  
**Data:** 2026-09-11  

**Baseline GitHub (NÃO perder de vista):**  
`tri/congelado-baseline-validado` @ **`ee2d2e1`** — *Congela baseline TRI validado…*

**Relatório da falha desta rodada:**  
`experiments/tri_live_monitor/output/RELATORIO_COMPLETO_MP4_ATE_LIVE_20260911.md`

**Contratos humanos:**  
`docs/BASELINE_MANUAL_APROVADO_TRI.md` · `docs/VALIDACAO_FINAL_CENARIOS_TRI.md` · `docs/TRI_CONGELADO.md`

---

## 0. Mensagem curta para colar no outro chat

```
Objetivo: recuperar a fluidez do baseline TRI validado (branch
tri/congelado-baseline-validado @ ee2d2e1 + validação MANUAL em /debug/vision).

Problema: a rodada MP4 offline + TRI Live Monitor + patches (phone_yolo,
analytics_track, emotion_async_worker, body_pose) PIOROU o LIVE vs o baseline:
- Celular na mão: longos trechos 100% not_detected (RAW YOLO ok → REJECT bottle_like)
- Cabeça baixa: sticky (UI mostra head_down + attn baixa com usuário ereto)
- MP4 enganou: person ROI = face expandida; LIVE = ByteTrack full-body

NÃO fazer: refatoração ampla; mais afrouxamento genérico calibrado só em MP4;
commit/merge no GitHub até smoke presencial dos ✅.

FAZER (mínimo):
1) Diff phone_yolo.py / analytics_track.py / body_pose.py vs ee2d2e1
2) Reverter a cadeia que causa FN de celular LIVE (bottle_like em person grande;
   large_hi_conf frouxo; face-ROI como caminho principal) — voltar ao eixo ee2d2e1
3) Manter APENAS anti-FP de headset ESTREITO (ear_region / área pequena) se 0 accept
   em fone continuar sem matar D/E3
4) Reverter sticky head_down: NÃO anular face_bbox só porque head_down_since ativo;
   NÃO tratar partially_observable como face_gone que reabre head_down
5) person_phone E3/E4 (peito ≠ uso; cara = uso) — MANTER se já estava no working
   tree deste chat; não misturar com phone_yolo geometry
6) Smoke PRESENCIAL obrigatório (não MP4): E4→E3→D/P→C→H erguer→I ou L
7) experiments/ pode ficar; produto app/ só merge depois do smoke

Ler: docs/HANDOFF_RECUPERACAO_BASELINE_POS_MP4.md (este arquivo)
e experiments/tri_live_monitor/output/RELATORIO_COMPLETO_MP4_ATE_LIVE_20260911.md
```

---

## 1. Diagnóstico em uma frase

O MP4 otimizou filtros/geometria para **person sintético a partir da face**.  
O LIVE usa **ByteTrack corpo grande**. Os patches reativos mataram o **recall de celular** que o baseline manual já tinha, e o hold de **head_down** ficou mentiroso. Anti-FP de **fone (0 accept)** foi o único ganho claro — preservar **sem** pagar com FN de D/E3.

---

## 2. O que estava bom no baseline (não negociar)

| ID | Contrato | Fonte |
|----|----------|--------|
| B | Garrafa ≠ celular | Manual 2026-08-03 |
| D | Celular real detectável / progressão | Manual 2026-08-03 |
| E4 | Peito + olhar câmera → near/visível, **não** uso | Manual 2026-09-03 |
| E3 | Frente do rosto / pegar → in_hand → possible/probable | Contrato + código person_phone |
| G | Olhos fechados 6s/30s | Manual — **não mexer para “salvar” F** |
| H | Cabeça baixa com duração ≈ real; limpa ao erguer | Manual 2026-08-03 |
| J/K | Oclusão estável; sem sono inventado | Manual |
| L | Mão perto sem cobrir ≠ oclusão persistente | 2026-09-09 |
| I | Perfil / rosto sumiu sem inventar head_down/sono | Validado |
| ATTN | Baixa atenção quando aplicável, sem virar sono | Manual |
| EX+/EX= | Sorriso→positiva; neutra coerente | Manual |
| C | Fone ≠ celular (anti-FP) | Melhorar sem quebrar D |

**Proibido:** “melhorar” um ✅ só com MP4 PASS.

---

## 3. O que a rodada MP4+LIVE quebrou (evidência)

| Sintoma | Cadeia | Arquivos |
|---------|--------|----------|
| Celular na mão = `not_detected` | YOLO RAW conf alta → `REJECT bottle_like_relative_height` → assoc não roda → sem magenta | `phone_yolo.py` |
| Overlay sem roxo | Overlay desenha só pós-filtro | `main.py` + filtro |
| Head_down sticky + attn baixa | `pose_face_bbox=None` com head_down_since; partial = face_gone; regrava head_down | `analytics_track.py`, `body_pose.py` |
| PASS MP4 ≠ LIVE | Person face-anchored vs ByteTrack full-frame | offline scripts vs orchestrator |

Evidências:  
`PHONE_HAND_NOW_SEQUENCE.json`, `PHONE_HAND_POST_PATCH_SEQUENCE.json`,  
`P_CELULAR_20260911T113026Z_summary.md`, `EVIDENCIA_HEADDOWN_STUCK_*.md`,  
`DIAGNOSTICO_LIVE_VS_MP4_20260910.md`.

---

## 4. Plano de recuperação (ordem fixa)

### Passo A — Inventário (30–60 min, sem “melhorar”)

```powershell
git fetch
git show ee2d2e1:app/vision/phone_yolo.py > /tmp/phone_yolo_ee2d2e1.py   # ou equivalente Windows
git diff ee2d2e1 -- app/vision/phone_yolo.py app/pipeline/analytics_track.py app/vision/body_pose.py app/vision/person_phone.py
```

Listar cada hunk: **KEEP** (E3/E4 person_phone, ear_region estreito) vs **REVERT** (bottle_like agressivo, large_hi_conf, face ROI principal, sticky).

### Passo B — Phone: eixo baseline + anti-FP estreito

1. Restaurar lógica de filtro/associação **próxima de `ee2d2e1`** para person LIVE (ByteTrack).
2. Remover ou desligar por default:
   - geometria efetiva / encolher person só para ratios (se causar recall instável)
   - `large_hi_conf` frouxo
   - face-anchored ROI como caminho **principal** de `detect_phones`
3. Manter rejeição de headset **estreita**:
   - `ear_region` / área pequena relativa ao person
   - **não** usar “altura relativa ao person full-frame” como proxy de garrafa se isso mata celular vertical real
4. **Manter** `person_phone.py` E3/E4 (peito vs frente do rosto) — é contrato deste chat; não confundir com `phone_yolo` geometry.
5. Testes automáticos mínimos:
   ```powershell
   pytest tests/test_phone_filters.py tests/test_phone_false_positive_regression.py tests/test_phone_positive_controls.py tests/test_phone_table_interaction.py -q
   ```
6. Smoke LIVE **antes** de qualquer novo afrouxamento.

### Passo C — Head_down: matar sticky

1. Não forçar `pose_face_bbox = None` só porque `head_down_since` está setado.
2. Não tratar `partially_observable` como `face_gone` que **reabre** head_down.
3. Ao erguer (nariz/pitch/pose claros), limpar `head_down_since` / accum.
4. Gate “nariz elevado ≠ look-down” só se smoke H passar; senão reverter hunk.
5. Se `analytics_person_bbox_for_pose` piorar I/H, **desligar** e voltar person ByteTrack puro.

### Passo D — Emotion

- Smoothing VGAF async: **flag / não bloquear recuperação**.
- Smoke EX+/EX=; EX− só depois do celular/H estáveis.
- Não trocar provider TRI (`fer_onnx` + smile_boost no overlay).

### Passo E — Smoke presencial obrigatório (não MP4)

Perfil:

```powershell
$env:PRESENCA_CONFIG_OVERLAY = "config.tri.yaml"
$env:RUNTIME_MODE = "rtsp"
$env:ENABLE_DEBUG_SNAPSHOT = "1"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

| # | Teste | Passa se |
|---|--------|----------|
| 1 | E4 peito 20s olhar câmera | near/visível; **sem** possible/probable; attn não baixa por phone |
| 2 | E3 celular na cara 15s+ | in_hand → possible (≥5s) / probable (≥12s); **não** “não indica uso” |
| 3 | D/P celular na mão 15s | magenta + estado ≠ not_detected contínuo |
| 4 | C fone 20s | **sem** phone_in_hand / interação |
| 5 | H: baixo 10s → erguer 10s | duração para; card não fica 23s/11min ereto; attn limpa derived_from_head_down |
| 6 | I perfil **ou** L mão no queixo | sem head_down inventado / sem oclusão persistente |

**Só depois:** voltar a pendentes (EX−, E1/E2, A, P1–P5 formais) — um de cada vez, com reteste dos ✅ acima.

---

## 5. O que NÃO fazer

| Não | Por quê |
|-----|---------|
| Calibrar filtro phone só com PASS MP4 | Person ROI diferente do LIVE |
| Mais exceções `large_hi_conf` / face ROI sem smoke D+E3+C | Empilhar remendo; FN volta |
| Mexer em G/drowsiness para “salvar” F | G já ✅ |
| Commit/merge “fecha TRI” com working tree suja | Baseline GitHub é ee2d2e1 |
| Refatorar orchestrator / ByteTrack “para ficar igual MP4” | Fora do escopo mínimo |
| Tratar experiments/ como produto | Monitor OK; não substitui webcam |

---

## 6. O que pode permanecer

| Item | Condição |
|------|----------|
| `experiments/tri_live_monitor/` + relatórios | Só diagnóstico |
| `experiments/tri_manual_videos/` | Regressão **secundária**; nunca gate de merge |
| Anti-FP headset 0 accept | Se smoke C + D + E3 passam juntos |
| Docs baseline / handoff | Sempre |
| person_phone E3/E4 | Contrato; smoke em par |

---

## 7. Critério de sucesso (mínimo “estar como antes”)

- [ ] Smoke #1–#6 PASS presencial no `/debug/vision`
- [ ] pytest phone + head_down/oclusão relevantes PASS
- [ ] Diff vs `ee2d2e1` em phone/pose **explicável em 1 parágrafo** (o que ficou e por quê)
- [ ] Nenhum commit no GitHub até o usuário marcar smoke ✅

**Melhorar o que faltava** só depois: EX−, E1, E2, A, C×3 formais, P1–P5 — **sem** reabrir patches que quebraram D/H.

---

## 8. Checklist para o agente responder no final

1. Diff `ee2d2e1` → HEAD nos 4 arquivos (lista KEEP/REVERT).  
2. O que foi revertido / o que ficou (anti-FP fone).  
3. Resultado pytest.  
4. Resultado smoke #1–#6 (ou “aguardando usuário”).  
5. Confirmação: **nada pushado** sem OK do usuário.

---

## 9. Referência rápida de arquivos

| Sensível | Ação tipica |
|----------|-------------|
| `app/vision/phone_yolo.py` | Reverter eixo FN; keep ear_region estreito |
| `app/vision/person_phone.py` | Keep E3/E4 |
| `app/pipeline/analytics_track.py` | Reverter sticky head_down / face_gone |
| `app/vision/body_pose.py` | Revisar gate nariz; não forçar look-down errado |
| `app/pipeline/emotion_async_worker.py` | Flag / depois |
| `config.tri.yaml` | Overlay TRI; não “consertar” LIVE mudando sem smoke |

---

> **Regra de ouro desta recuperação:**  
> Primeiro **igualar o baseline manual validado**.  
> Depois **melhorar pendentes**.  
> MP4 e Live Monitor são **ferramentas**; a prova de fechamento continua sendo **webcam + matriz ✅**.
