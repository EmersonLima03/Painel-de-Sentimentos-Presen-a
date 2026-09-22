# Relatório pré-commit — produto `_facial_enroll_prod`

**Data:** 2026-09-22  
**Branch:** `feat/auth-saas-rbac`  
**Base:** `1bd701c`  
**Objetivo:** separar o que entra no commit de estabilização do que fica fora.

---

## Estado

Working tree **dirty** com alterações de Auth SaaS, RBAC, facial, aula formal, sync LXP e docs operacionais. Sem commit ainda.

---

## Entram no produto (commit)

### Código Edge / sync

- `app/m2_proxy.py`
- `app/main.py` (se alterado)
- `app/services/lesson_context.py` — supersede sessão auto / aula formal
- `app/sync/worker.py` — lanes LXP vs produto isoladas

### Frontend (Dashboard / Auth / RBAC / Facial / Aula)

- `frontend/src/App.tsx`
- `frontend/src/cloud/*` (AuthContext, CloudAuthPanel, adminApi, supabaseClient)
- `frontend/src/components/layout/*`
- `frontend/src/components/ui/LessonHeader.tsx`
- `frontend/src/components/views/FacialEnrollmentView.tsx`
- `frontend/src/components/views/admin/AdminShellView.tsx`
- `frontend/src/components/views/LoginView.tsx` (novo)
- `frontend/src/components/views/RootPlatformView.tsx` (novo)
- `frontend/src/styles.css`, `frontend/src/types.ts`

### M2 enrollment (homologação produto)

- scripts/UI em `experiments/smoke_e2e_sentimentos/modulo2_poc/`
- `tests/test_enrollment_identity.py` (novo)

### Supabase

- `supabase/functions/admin-invite-user/index.ts`
- `supabase/functions/platform-admin/` (novo)
- `supabase/migrations/20260922120000_auth_saas_rbac_foundation.sql`
- `supabase/migrations/20260922153000_auto_edge_student_key.sql`

### Testes / boot / scripts E2E

- `tests/test_fase6_lesson_context.py`
- `tests/test_sync_worker_product_lane.py`
- `tests/test_m2_gestor_gate_rbac.py`
- `scripts/boot_edge_m2.ps1`
- scripts E2E/diagnóstico: `e2e_escola_formal_pw.py`, `prove_identity_contract_e2e.py`, `_audit_*`, `_diag_*`, `_e2e_*`, `_live_*`

### Documentação operacional / mapa

- `docs/OPERATIONS.md` (se alterado)
- `docs/MAPA_REAL_DO_PRODUTO_PRESENCA.md`
- `docs/PLANO_VALIDACAO_AULA_REAL_E2E.md`
- `docs/RELATORIO_FECHAMENTO_FLUXO_ESCOLAR_E2E_20260922.md`
- `docs/RELATORIO_AUDITORIA_GIT_COMPLETA.md`
- este relatório + relatórios das fases seguintes desta missão

### Gitignore

- `.gitignore` (labs pesados, `.wrangler/`, `results/`, etc.)

---

## NÃO entram

| Item | Motivo |
|------|--------|
| `frontend/tsconfig.tsbuildinfo` | artefato de build |
| `*.log`, `logs/` | temporário |
| `results/`, `.pytest_cache/`, `.wrangler/` | temporário / já gitignored |
| `venv/`, `node_modules/`, `dist/` | recriável |
| `.env`, secrets | nunca versionar |
| `_archive/` (~12 GB labs) | archive externo (ver relatório archive) |
| vídeos / datasets / modelos de lab | fora do Git |

---

## Riscos se não commitarmos

- Perda do tip operacional (Auth/RBAC/aula/facial/LXP) se o worktree for apagado.
- Branch ainda sem remoto.

**Próximo:** tag `backup-produto-auth-rbac-20260922` em `1bd701c`, depois commit, depois push.
