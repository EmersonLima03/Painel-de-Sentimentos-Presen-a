# Blindagem TRI LIVE — 2026-09-15

Objetivo: **não perder** o baseline validado e **não regredir** ao fechar o cenário A (PET transparente).

## Estado no Git

| Item | Valor |
|------|--------|
| Branch | `tri/congelado-baseline-validado` |
| Commit de catálogo LIVE 14–15/09 | `0a213cf` — *Congela LIVE 14–15/09: E1/E2/P1–P3/P5, F/G anti-sticky e catálogo consultável.* |
| Commits anteriores de congelamento | `0764cd1` (H/J/K/EX+), `eb6590e` (E3/E4/D/C), `ee2d2e1` (baseline TRI) |
| Perfil obrigatório | `PRESENCA_CONFIG_OVERLAY=config.tri.yaml` · `RUNTIME_MODE=rtsp` · `ENABLE_DEBUG_SNAPSHOT=1` |
| Emoção TRI | `fer_onnx` + `smile_boost` — **nunca VGAF** neste perfil |

## O que está no Git (seguro versionar)

- Catálogo: [`LIVE_E1_E2_P_20260915.md`](LIVE_E1_E2_P_20260915.md)
- Números: [`VALORES_CONGELADOS_LIVE_20260914.md`](VALORES_CONGELADOS_LIVE_20260914.md)
- Congelamento / matriz: [`CONGELAMENTO_LIVE_20260914.md`](CONGELAMENTO_LIVE_20260914.md), [`VALIDACAO_FINAL_CENARIOS_TRI.md`](VALIDACAO_FINAL_CENARIOS_TRI.md)
- Baseline humano: [`BASELINE_MANUAL_APROVADO_TRI.md`](BASELINE_MANUAL_APROVADO_TRI.md)
- Código + `config.tri.yaml` + testes de contrato ligados aos ✅
- Inventário de nomes da evidência bruta (sem imagens): [`manifests/TRI_OBSERVE_MANIFEST_20260915.txt`](manifests/TRI_OBSERVE_MANIFEST_20260915.txt)

## Evidência bruta (NÃO versionar — rosto do testador)

| Local | Conteúdo |
|-------|----------|
| Trabalho diário | `experiments/tri_live_monitor/output/_observe/` (gitignored) |
| Cópia de blindagem | `data/validation/tri_observe_backup_20260915_0a213cf/` (`data/**` já ignorado) |
| Zip de backup | `data/validation/backups/tri_observe_20260915_0a213cf.zip` (~17 MB, 130 ficheiros no momento da blindagem) |

Se a pasta `_observe` for apagada, restaurar a partir do zip/cópia acima **no mesmo PC/OneDrive**.

## Matriz — fechado vs aberto

**✅ Fechados (obrigatórios):** B, C (1 take), D, E1, E2, E3, E4, F, G, H, I, J, K, L, ATTN, EX+/EX=, P1–P5.

**Pendente obrigatório:** **A** (garrafa PET transparente).

**Opcional:** C ×3. Multicâmera fundida = backlog P3 (fora do TRI mono-cam).

**EX−:** fechado em sessão com VGAF — **não** misturar com regressão do perfil TRI `fer_onnx`.

## Regra anti-regressão (pós qualquer patch, sobretudo A)

Patch **mínimo**. Não alterar expected/baseline só para passar teste.

**Sentinelas LIVE** (obrigatórias se o patch tocar phone/bottle/hold/association):

1. A — PET transparente  
2. B — garrafa escura/térmico  
3. D — celular na mão  
4. E3 — uso na frente do rosto  
5. E4 — peito ≠ uso  
6. P5 — mesa → pegar  
7. F — digitar ≠ sono  
8. G — olhos fechados / anti-sticky  

Se o patch tocar oclusão: incluir **L**. Não reabrir EX−/VGAF no perfil TRI.

**Gates de estabilidade (temporais, não zero absoluto):**

- Phone sticky: após retirar objeto, limpar dentro do hold documentado (~2–2,5 s) + folga medida — não episódio “provável” interminável.  
- Verde drift: 1 frame ruim não falha; drift **sustentado** = FAIL.  
- Contaminação: fim de take → esperar clear / não herdar estado no take seguinte.

**Encerramento TRI:** A LIVE ✅ + sentinelas ✅ + pytest contratos ✅ + confirmação humana final → só então tag estável.

**Guarda phone YOLO (2026-09-17):** qualquer edição em `app/vision/phone_yolo.py` deve passar `tests/test_phone_yolo_module_guard.py` (import/AST). Ver [`FIX_PHONE_YOLO_INDENT_20260917.md`](FIX_PHONE_YOLO_INDENT_20260917.md). IndentationError no módulo = celular morto com resto do pipeline “ok”.

## KEEP / NEVER (resumo)

Ver também [`LIVE_E1_E2_P_20260915.md`](LIVE_E1_E2_P_20260915.md).

**KEEP:** limiares phone 5s/12s; drowsiness 6s/30s; `look_down_soft_pitch=0.14`; E4 resting ≠ P5; clear sono ~2 s com EAR aberto.

**NEVER:** VGAF no TRI; baixar soft pitch sem reteste F+G; regressar E4 ao “salvar” P5; `continue` desalinhado em `phone_yolo`.
