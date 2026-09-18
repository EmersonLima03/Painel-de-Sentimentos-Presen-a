# Fase 6 — Validação operacional (fechamento)

**Branch:** `feat/sentimentos-v1`  
**HEAD base:** `a4964a6` (Fase 5B)  
**TRI:** `git diff -- app/vision config.tri.yaml` → **vazio**  
**LXP produção:** intocado  
**Simulator:** único destino de chamada (quando `modules.lxp=simulator`)

## Evidências

- API/cloud: `FASE6_VALIDATION.json`
- Playwright: `fase6_playwright.json` + `ui/*.png`
- Pytest: `tests/test_fase6_lesson_context.py` (+ suite LXP/sync/persistência/restart)

## Resultados API (`fase6_validate.py`)

| Área | Resultado |
|------|-----------|
| start-with-context | PASS |
| resume mesma ocorrência | PASS |
| conflito outra ocorrência (409) | PASS |
| reopen → nova session_id | PASS |
| start a partir do cache | PASS |
| live/status lesson_context | PASS |
| gestor cria lesson_occurrence | PASS |
| professor lista aulas | PASS |
| RLS professor não cria (403) | PASS |
| LXP produção | PASS (não acessado) |
| Câmera USB / check-in→Simulator | **NÃO OBSERVADO** (`cameras_online=0`, `modules.lxp=disabled`) |

## Playwright UI

Todos **PASS**: login gestor → aba Aulas; login professor → Minhas aulas → Iniciar → Ao vivo com contexto pedagógico (turma/disciplina/sala/horário).

## Pytest

38 passed (fase6 + lxp + phone guard + persistence + sync + session resume).

## Build

`npm run build` → **PASS**

## Não observados (sem inventar PASS)

1. Check-in físico → outbox LXP → Simulator (câmera offline + LXP disabled no default; sem alterar TRI/config para forçar).
2. Offline NIC físico (cache Edge validado via API start thin payload).

## Commit

**Não realizado** — aguardando autorização explícita.
