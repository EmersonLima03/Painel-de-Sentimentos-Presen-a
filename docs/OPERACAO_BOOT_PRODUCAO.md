# Operação de produção — Presença (Edge + M2 + Dashboard React)

## Iniciar o sistema

A partir da raiz do worktree de produção (`feat/facial-enrollment-production`):

```powershell
.\scripts\boot_edge_m2.ps1
```

Opcional (explícito):

```powershell
.\scripts\boot_edge_m2.ps1 -PublicBaseUrl "https://presenca.sistemadulino.com.br"
```

**O script garante o build do Dashboard React antes de iniciar o Edge.**

Não é necessário rodar manualmente `cd frontend; npm run build` antes de cada restart.

### O que o boot faz

1. Resolve a raiz via `$PSScriptRoot` (não depende do cwd do terminal)
2. Carrega `.env` (sem imprimir secrets)
3. Verifica `frontend/dist/index.html` (+ assets)
4. Se ausente/desatualizado → `npm run build` automático
5. **Falha o boot** se o React não estiver válido (não declara sistema OK)
6. Encerra processos antigos em `:8000` / `:8766` (salvo `-KeepExisting`)
7. Sobe M2 em `127.0.0.1:8766`
8. Sobe Edge em `127.0.0.1:8000`
9. Valida `/health`, `/dashboard` (React `#root` /assets, sem “Painel unificado”), `/m2/healthz`, assets
10. Tenta confirmar HTTPS no host público (se o Named Tunnel já estiver no ar)

Resumo esperado:

```
BUILD OK
EDGE OK
M2 OK
DASHBOARD REACT OK
CADASTRO FACIAL OK
SUPABASE A OK
SUPABASE B ISOLADO
TUNNEL HTTPS OK
```

## Arquitetura

```
Cloudflare Named Tunnel (presenca.sistemadulino.com.br)
        ↓
http://127.0.0.1:8000   ← Edge (M1 + M3 + TRI + Dashboard React + proxy M2)
        ↓
http://127.0.0.1:8766   ← M2 (somente loopback; NUNCA no Tunnel)
```

| Componente | Porta | Notas |
|------------|-------|--------|
| Edge | `127.0.0.1:8000` | Único alvo do Tunnel |
| M2 | `127.0.0.1:8766` | Interno; `M2_POC_TEST_HOOKS=0` |
| Dashboard | `/dashboard` | React (`frontend/dist`); legado só em `/dashboard-legacy` |
| Cadastro facial | `/gestor/` via proxy | Aba no Dashboard moderno |
| Supabase A | presença/ops | roster + facial_* |
| Supabase B | LXP homolog | isolado — M2 não escreve |

## Health checks

| URL | Esperado |
|-----|----------|
| `http://127.0.0.1:8000/health` | 200 |
| `http://127.0.0.1:8000/dashboard` | 200 + `#root` + `/assets/` · **sem** “Painel unificado” |
| `http://127.0.0.1:8000/m2/healthz` | `test_hooks=false`, `yunet_model_present=true`, `roster_source=supabase` |
| `https://presenca.sistemadulino.com.br/dashboard` | mesmo critério React |

Se `frontend/dist` estiver ausente, `/dashboard` retorna **503** (não cai no legado).

## Cloudflare Tunnel

Confirmar config do Named Tunnel:

- hostname → `http://127.0.0.1:8000`
- **nunca** `127.0.0.1:8766`

O boot **não** gerencia o `cloudflared` (processo externo). Deve permanecer rodando.

## Rollback

1. Parar Edge/M2 (CTRL+C no boot, ou matar PIDs nas portas)
2. `git checkout` do tip estável anterior na mesma branch/worktree
3. `.\scripts\boot_edge_m2.ps1` novamente
4. Legado HTML (`app/static/dashboard.html`) permanece em `/dashboard-legacy` apenas — **não** usar como produção

## Flags úteis

| Flag | Uso |
|------|-----|
| `-ForceFrontendBuild` | Rebuild mesmo com dist válido |
| `-SkipFrontendBuild` | Pula npm; **ainda exige** dist React válido |
| `-SkipM2` | Sobe só Edge |
| `-KeepExisting` | Não mata processos nas portas |

## Logs

- `results/boot_edge_uvicorn.log` / `.err.log`
- `results/boot_m2.log` / `.err.log`
