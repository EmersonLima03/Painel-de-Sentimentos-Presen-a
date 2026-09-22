# Integração M2 ↔ Dashboard (Edge :8000)

## Arquitetura

```
PC Edge
├── :8000  Edge (M1/M3/TRI/Dashboard/Debug Vision/SyncWorker + proxy M2)
└── :8766  M2 enrollment (não exposo na internet)

Cloudflare Named Tunnel → http://127.0.0.1:8000 somente
```

## Named Tunnel (HTTPS estável)

| Campo | Valor |
|-------|-------|
| Tunnel | `presenca-edge` (`cf4c5452-a01c-4d32-a9ee-f6afae5c4f87`) |
| Hostname | `https://presenca.sistemadulino.com.br` |
| Origem | `http://127.0.0.1:8000` **somente** (nunca `:8766`) |
| Config local | `%USERPROFILE%\.cloudflared\config.yml` |

Subir o tunnel (manter Edge+M2 já no ar):

```powershell
cloudflared tunnel --config "$env:USERPROFILE\.cloudflared\config.yml" --no-autoupdate run presenca-edge
```

Boot Edge+M2 com base pública:

```powershell
.\scripts\boot_edge_m2.ps1 -PublicBaseUrl "https://presenca.sistemadulino.com.br"
```

`M2_PUBLIC_BASE_URL` deve ser esse hostname (QR/share_link). Secrets ficam só no `.env` local (gitignored).

## Paths proxy (sem catch-all)

| Path | Destino | Auth |
|------|---------|------|
| `/gestor`, `/gestor/*`, `/gestor-static/*` | :8766 | cookie gate / API token |
| `/api/gestor/*` | :8766 | cookie gate / API token |
| `/a/*`, `/aluno-static/*`, `/api/aluno/*` | :8766 | público (QR) |
| `/m2/healthz` | :8766/healthz | público |

## Modelo YuNet (obrigatório no Edge)

O ONNX está no `.gitignore` (`*.onnx`) e **não** vem no worktree git.

Copiar uma vez a partir do checkout que já tenha o arquivo:

```powershell
New-Item -ItemType Directory -Force -Path data\opencv_models | Out-Null
Copy-Item "..\Presenca\data\opencv_models\face_detection_yunet_2023mar.onnx" `
  "data\opencv_models\face_detection_yunet_2023mar.onnx"
```

Sem esse arquivo, `/api/aluno/session/frame` responde 200 com `ui_code=adjust` e a mensagem
"Não foi possível analisar a imagem…" (FileNotFoundError do YuNet).

`GET /m2/healthz` → `yunet_model_present: true|false`

Fonte de escolas: `public.schools`  
Fonte de turmas: `public.class_groups`  
Fonte de alunos: `public.students` via `public.enrollments` (status=`active`)  
ID oficial do aluno: `students.id` (uuid) — gravado em `facial_enrollment_roster.student_id`  
Autenticação gestor: Supabase Auth + `memberships` (Dashboard); M2 gestor via cookie gate no Edge  

`M2_ROSTER_SOURCE=auto` (default): usa Supabase A se `SUPABASE_URL` + `SERVICE_ROLE` existirem; senão fixtures (só testes/lab).

Smoke dados reais:

```powershell
python experiments\smoke_e2e_sentimentos\modulo2_poc\scripts\smoke_real_roster_supabase_a.py
```

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
