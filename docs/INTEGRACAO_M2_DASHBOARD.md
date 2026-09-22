# Integração M2 ↔ Dashboard (Edge :8000)

## Arquitetura

```
PC Edge
├── :8000  Edge (M1/M3/TRI/Dashboard/Debug Vision/SyncWorker + proxy M2)
└── :8766  M2 enrollment (não exposo na internet)

Cloudflare Named Tunnel → http://127.0.0.1:8000 somente
```

## Paths proxy (sem catch-all)

| Path | Destino | Auth |
|------|---------|------|
| `/gestor`, `/gestor/*`, `/gestor-static/*` | :8766 | cookie gate / API token |
| `/api/gestor/*` | :8766 | cookie gate / API token |
| `/a/*`, `/aluno-static/*`, `/api/aluno/*` | :8766 | público (QR) |
| `/m2/healthz` | :8766/healthz | público |

## Variáveis

```env
# Edge
M2_UPSTREAM_URL=http://127.0.0.1:8766
M2_GESTOR_GATE_SECRET=<random>
API_AUTH_TOKEN=           # opcional; se setado, também libera gestor
M2_GESTOR_OPEN=0          # 1 só em lab sem auth

# M2 (mesmo processo/env do enrollment)
M2_PUBLIC_BASE_URL=https://<HOST_DO_DASHBOARD>
M2_ENROLL_HMAC_SECRET=<secret>

# Persistência operacional → Supabase A (presença)
SUPABASE_URL=https://rmiaadljzxyehwyuhhgd.supabase.co
SUPABASE_SERVICE_ROLE_KEY=<service_role>
# ou
M2_OPS_SUPABASE_URL=...
M2_OPS_SUPABASE_SERVICE_KEY=...
```

Supabase B (LXP simulador) **não** é usado pelo M2.

Biometria: continua TEMP/local no M2. **Não** grava `face_embeddings`, **não** chama `reload_matcher`.

## Boot

```powershell
.\scripts\boot_edge_m2.ps1 -PublicBaseUrl "https://seu-host.trycloudflare.com"
```

Ou manual:

1. `python experiments/.../enrollment_gestor_server.py --host 127.0.0.1 --port 8766`
2. `python -m uvicorn app.main:app --host 0.0.0.0 --port 8000`

## Named Tunnel (manual)

Se o hostname/credenciais Cloudflare não estiverem neste ambiente:

1. Instalar `cloudflared`
2. `cloudflared tunnel login`
3. Criar Named Tunnel apontando **somente** para `http://127.0.0.1:8000`
4. Definir DNS do hostname do Dashboard
5. Exportar `M2_PUBLIC_BASE_URL=https://<mesmo-hostname>`
6. Reiniciar M2 (e Edge) para o QR usar HTTPS same-host

**Não** criar Workers/Containers/R2 para esta etapa.

## Smoke

1. Edge health: `GET /health`
2. M2 via Edge: `GET /m2/healthz`
3. Dashboard → **Cadastro facial** → criar campanha → QR = `https://<host>/a/<token>`
4. Celular: claim → cadastro → completed
5. Gestor: progresso no iframe
6. Supabase A: linhas em `facial_enrollment_*` com status
7. Supabase B: sem alteração de schema LXP
8. Debug Vision: `/debug/vision` (API token se configurado)

## Rollback

1. Parar M2 (`:8766`) — Dashboard/M1/M3/TRI seguem no Edge
2. Remover `app.include_router(m2_proxy_router)` **ou** não iniciar M2 (proxy devolve 503 só nos paths M2)
3. Reverter branch / checkout `057bc99`
4. Tabelas `facial_enrollment_*` no Supabase A podem permanecer (não afetam TRI); drop opcional só com autorização

## Critérios

- [ ] Dashboard único + aba Cadastro facial
- [ ] QR same-host (nunca localhost/:8766 em produção)
- [ ] Ops M2 no Supabase A; B preservado; biometria TEMP
- [ ] Sem `reload_matcher` / `face_embeddings` de produção
