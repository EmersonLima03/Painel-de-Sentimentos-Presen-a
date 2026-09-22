# Relatório — Fechamento fluxo escolar E2E

**Data:** 2026-09-22  
**Worktree:** `_facial_enroll_prod` · `feat/auth-saas-rbac`  
**URL:** https://presenca.sistemadulino.com.br  

## Resultado

| Critério | Status |
|----------|--------|
| Aula formal inicia pela UI (gestor) | ✅ |
| Não depende de sessão automática | ✅ (auto é supersedida) |
| Ao vivo com lesson_context | ✅ Turma Teste 1 · lesson-8b-math-50 |
| Emerson reconhecido (p01) | ✅ present=1 |
| TRI / KPIs | ✅ attention_index ~0.85–0.87 |
| Relatórios abertos | ✅ |
| LXP B attendance + receipt | ✅ sent + receipt inserted |
| Playwright E2E | ✅ `ok: true` |

## Arquivos alterados

| Arquivo | Motivo |
|---------|--------|
| `frontend/.../AdminShellView.tsx` | Gestor: botões **Iniciar aula** e **Encerrar aula ativa** |
| `frontend/.../LessonHeader.tsx` | Texto aponta Admin → Aulas (gestor) |
| `app/services/lesson_context.py` | Sessão sem contexto (automática) é encerrada ao iniciar aula formal |
| `app/sync/worker.py` | Lanes LXP e PRODUCT isoladas — 401 no A não bloqueia B |
| `tests/test_fase6_lesson_context.py` | Teste supersede sessão automática |
| `tests/test_sync_worker_product_lane.py` | Teste LXP não bloqueado por product |
| `scripts/e2e_escola_formal_pw.py` | Playwright gestor → Ao vivo → LXP |

## Evidências

- Session: `b17497bb-5a54-43b9-afd0-d340ad6f6673`
- Occurrence: `cb86837c-bfd7-4d14-9535-462f54b07fec` → status `in_progress` (A)
- LXP event: `lxp-att:881e02ff-14be-4eb1-b730-2f883e4e21b3` → outbox **sent**
- Receipt B: `result_status=inserted` · `http_status=200` · `2026-09-22T20:16:38Z`
- Artefatos: `results/e2e_escola_formal/` (screenshots + `report.json`)

## Testes

```
pytest tests/test_fase6_lesson_context.py  → 7 passed
pytest tests/test_lxp_attendance_integration.py + test_sync_worker_product_lane.py → passed (incl. lane isolada)
python scripts/e2e_escola_formal_pw.py → ok: true, lxp_ok: true
```

## Pendências restantes

1. **Ingest Supabase A** ainda retorna `401 invalid_or_revoked_token` (`DEVICE_TOKEN` / `edge_devices=0`) — sync cloud de sessões/snapshots quebrado; **não afeta** presença local nem LXP B após o fix de lanes.
2. Mirror `facial_student_enrollments` pode permanecer desatualizado vs Edge.
3. Nome da disciplina no cadastro: “Metematica” (typo de dados, não de código).
4. UI LXP Homologação às vezes ainda “Carregando…” no screenshot (API já OK).
