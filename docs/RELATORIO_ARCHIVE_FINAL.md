# Relatório — Archive final (`presenca-20260922`)

**Data:** 2026-09-22  
**Local:** `c:\Users\dulin\OneDrive\Documentos\Teste de monitoramento\_archive\presenca-20260922\`  
**Nota:** `D:\archive\...` indisponível no host; archive no mesmo volume OneDrive.

---

## Tamanho

| Item | Valor |
|------|-------|
| Total | **~12,12 GB** |
| Arquivos | ~96.627 |
| `experiments/` | ~12,11 GB |
| `facial_enroll_prod_results/` | ~6 MB |
| Manifestos | ~10 KB |

---

## Conteúdo (finalidade)

| Path | Finalidade |
|------|------------|
| `experiments/scenario_i_ai/` | Lab IA cenário I (~8,4 GB) |
| `experiments/ex_emotion_model_benchmark/` | Benchmark emoção (~2,5 GB) |
| `experiments/tri_manual_videos/input/` | Vídeos TRI manuais (~1,4 GB) |
| `experiments/tri_live_monitor/output/` | Saídas TRI live (~70 MB) |
| `facial_enroll_prod_results/` | Evidências E2E/boot antigas |
| `MANIFEST_MOVE.txt` | Registro de movimentos |
| `MANIFEST_REMOVED.txt` | Registro de remoções |

---

## Deve entrar no Git

- Documentação / relatórios desta organização
- Cópias leves dos **manifestos** (em `docs/archive_presenca_20260922/`)
- README apontando o caminho externo do archive

## Deve ficar fora do Git

- Vídeos (`.mp4` e correlatos)
- Datasets / frames
- Modelos / `.venv` de labs
- Benchmarks pesados
- Qualquer arquivo gigante sob `_archive/`

**Decisão:** manter archive **externo** (não Git LFS). Branch `archive/labs-20260922` versiona apenas metadados/manifestos.

---

## Recuperação

Para restaurar um lab:

1. Copiar de `_archive/presenca-20260922/experiments/<nome>` de volta para `Presenca/experiments/`.
2. Não é necessário `git checkout` do blob pesado.
