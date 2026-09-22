# Relatório — Auditoria Git completa (Presença)

**Data:** 2026-09-22  
**Escopo:** somente leitura  
**Produto operacional:** `_facial_enroll_prod` · `feat/auth-saas-rbac` @ `1bd701c` (+ working tree dirty)

---

## Remotes

| Nome | URL |
|------|-----|
| `origin` | `https://github.com/EmersonLima03/Painel-de-Sentimentos-Presen-a.git` |
| `presenca` | `https://github.com/EmersonLima03/Presenca.git` |

Remotos em `origin`: `main`, `develop`, `feat/m2-enrollment-production`, `feat/painel-de-sentimentos`, `tri/congelado-baseline-validado`.

---

## Branches

| Branch | Tip | Data | Commits | vs main | Exclusivos vs auth | Remoto |
|--------|-----|------|---------|---------|--------------------|--------|
| `main` | `0c66bfe` | 2026-07-22 | 5 | — | n/a | `origin/main` |
| `develop` | `0c66bfe` | 2026-07-22 | 5 | 0/0 | n/a | `origin/develop` |
| **`feat/auth-saas-rbac`** | `1bd701c` | 2026-09-22 | 53 | +48/0 | — (produto) | **ausente** |
| `feat/facial-enrollment-production` | `1bd701c` | 2026-09-22 | 53 | +48/0 | 0 (mesmo tip) | ausente |
| `feat/m2-enrollment-production` | `e2a0dad` | 2026-09-21 | 46 | +41/0 | 0 (ancestral) | `origin/...` |
| `feat/integrate-m2-dashboard-ux` | `065de8f` | 2026-09-22 | 49 | +44/0 | 0 (ancestral) | ausente |
| `fix/rc-build-packaging` | `057bc99` | 2026-09-21 | 47 | +42/0 | 0 (ancestral) | ausente |
| `feat/painel-de-sentimentos` | `98a9daa` | 2026-07-29 | 15 | +10/0 | 0 | `origin/...` (ahead 2 local) |
| `feat/sentimentos-v1` | `3b46d5a` | 2026-09-18 | 44 | +39/0 | 0 | ausente |
| `tri/congelado-baseline-validado` | `28a191f` | 2026-09-17 | 21 | +16/0 | 0 | `origin/...` |

**Achado:** nenhuma branch listada possui commits exclusivos fora de `feat/auth-saas-rbac` (`not_in_auth=0`). O produto atual contém o histórico delas.

### Tags existentes

- `baseline-fase-0`
- `pre-final-analytics-enable`
- `pre-spike-sanitized`

---

## Worktrees

| Caminho | Branch | HEAD | ~Tamanho | Finalidade | Risco |
|---------|--------|------|----------|------------|-------|
| `_facial_enroll_prod` | `feat/auth-saas-rbac` | `1bd701c` | 0,13 GB | **Produto operacional** | Alto se perdido sem push (dirty + só local) |
| `Presenca` | `feat/m2-enrollment-production` | `e2a0dad` | 1,12 GB | Checkout Cursor / labs residual | Médio (não é tip do produto) |
| `_integrate_m2_ux` | `feat/integrate-m2-dashboard-ux` | `065de8f` | 0,09 GB | Worktree histórico M2 UX | Baixo (ancestral de auth) |
| `_rc_fix_e2a0dad` | `fix/rc-build-packaging` | `057bc99` | 0,02 GB | Worktree RC packaging | Baixo (ancestral de auth) |

---

## Classificação

### Produto atual

- Branch: `feat/auth-saas-rbac`
- Worktree: `_facial_enroll_prod`
- Working tree: **dirty** (código Auth/RBAC/aula/facial/LXP ainda não commitado)

### Histórico importante (manter tags / remoto)

- `main`, `develop`
- `tri/congelado-baseline-validado`
- `feat/m2-enrollment-production` (remoto + checkout)
- `feat/painel-de-sentimentos` (remoto)

### Experimentos / intermediários

- `feat/integrate-m2-dashboard-ux`
- `fix/rc-build-packaging`
- `feat/sentimentos-v1`
- `feat/facial-enrollment-production` (duplicata de tip pré-commit)

### Candidatos a remoção (após backup/tag)

- Worktrees: `_integrate_m2_ux`, `_rc_fix_e2a0dad`
- Branches locais duplicadas/ancestrais após tag de arquivo

---

## Riscos imediatos

1. Produto dirty **não está no GitHub**.
2. Branch `feat/auth-saas-rbac` **só local**.
3. Confusão Cursor (`Presenca` @ `e2a0dad`) vs produto (`_facial_enroll_prod`).

**Nenhuma remoção nesta fase.**
