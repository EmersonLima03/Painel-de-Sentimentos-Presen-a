# Plano de limpeza de branches — Presença

**Data:** 2026-09-22  
**Status:** plano (execução controlada só após tags/push do produto)

Pré-condição: `feat/auth-saas-rbac` commitado + push + tag `backup-produto-auth-rbac-20260922`.

---

## Manter (nunca apagar sem confirmação explícita)

| Branch | Motivo |
|--------|--------|
| `feat/auth-saas-rbac` | Produto operacional |
| `main` | Produção baseline remoto |
| `develop` | Linha de desenvolvimento |
| `tri/congelado-baseline-validado` | Baseline TRI validado (remoto) |
| `feat/m2-enrollment-production` | Histórico M2 + checkout `Presenca` (remoto) |
| `feat/painel-de-sentimentos` | Histórico remoto |

---

## Arquivar (tag + depois remover branch/worktree local)

Todas têm `not_in_auth=0` (conteúdo já ancestral de auth). Tags propostas:

| Branch | Tip | Tag de arquivo |
|--------|-----|----------------|
| `feat/integrate-m2-dashboard-ux` | `065de8f` | `archive/integrate-m2-ux-20260922` |
| `fix/rc-build-packaging` | `057bc99` | `archive/rc-build-packaging-20260922` |
| `feat/facial-enrollment-production` | `1bd701c` | coberto por `backup-produto-auth-rbac-20260922` |

Worktrees a remover após tag:

- `_integrate_m2_ux`
- `_rc_fix_e2a0dad`

---

## Remover futuramente (local, após arquivo)

| Branch | Motivo |
|--------|--------|
| `feat/facial-enrollment-production` | Duplicata do tip pré-commit |
| `feat/integrate-m2-dashboard-ux` | Ancestral; worktree histórico |
| `fix/rc-build-packaging` | Ancestral; worktree histórico |

### Avaliar depois (preservar por enquanto)

| Branch | Motivo de cautela |
|--------|-------------------|
| `feat/sentimentos-v1` | Nome histórico LXP; sem remoto; ancestral — pode arquivar em segunda onda |

### Remoto

- **Não** apagar remotes nesta onda.
- `origin/feat/m2-enrollment-production`, `origin/tri/...`, `origin/feat/painel-de-sentimentos` permanecem.

---

## Ordem segura de execução

1. Push `feat/auth-saas-rbac` + tags de backup/arquivo  
2. `git worktree remove` dos históricos  
3. `git branch -d` das branches arquivadas (fast-forward / ancestral)  
4. Validar produto no `_facial_enroll_prod`
