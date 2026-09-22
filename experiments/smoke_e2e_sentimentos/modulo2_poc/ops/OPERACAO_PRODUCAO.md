# Operação — Módulo 2 Enrollment Escalável (serviço isolado)

## 1. Arquitetura (produção escola)

```
Internet → Cloudflare Named Tunnel → Edge :8000
  ├── Dashboard / M1 / M3 / TRI / Debug Vision
  └── proxy seletivo → M2 :8766 (loopback)
        ├── /gestor/ /gestor-static/*
        ├── /a/<token> /aluno-static/*
        ├── /api/gestor/* /api/aluno/*
        └── /healthz (também via Edge /m2/healthz)

Galeria TEMP: modulo2_poc/results/... (sem face_embeddings / reload_matcher)
Ops (campanha/roster/status): dual-write → Supabase A (presença)
Supabase B = somente LXP homologação — não usar no M2

Ver também: docs/INTEGRACAO_M2_DASHBOARD.md
```

## 2. URL

- Lab local via Edge: `http://127.0.0.1:8000/gestor/` (Dashboard → Cadastro facial)
- Aluno QR: `https://<HOST_DO_DASHBOARD>/a/<campaign_token>`
- **Nunca** expor `:8766` na internet; Tunnel só para `:8000`
- Definir `M2_PUBLIC_BASE_URL=https://<HOST_DO_DASHBOARD>`

## 3. Subir local / container

```powershell
cd experiments\smoke_e2e_sentimentos\modulo2_poc
copy .env.example .env
# editar .env: M2_PUBLIC_BASE_URL + M2_ENROLL_HMAC_SECRET

# Opção A — processo
python scripts\enrollment_gestor_server.py --host 0.0.0.0 --port 8766

# Opção B — Docker isolado
docker compose -f ops\docker-compose.m2.yml up -d --build
curl http://127.0.0.1:8766/healthz
```

## 4. Operar campanha

1. Abrir `/gestor/`
2. Escola Demo → turma → Iniciar campanha
3. Compartilhar QR (só `campaign_token`)
4. Entregar claim codes (fora do QR)
5. Acompanhar progresso (poll 2s)

## 5. Cadastro aluno

QR → claim → confirmar nome → câmera celular → frente/direita/esquerda/validação → óculos opcional → completed

## 6. Onde ficam os dados

| Dado | Local |
|------|--------|
| Campanhas / claim / sessão | SQLite volume `m2_enrollment_data` |
| Templates FaceNet | `results/gallery_temp/enrollment_campaigns/` |
| Crops | `results/crops_enrollment/` |

Tudo **TEMP isolado**. Sem gravação em `face_embeddings` de produção.

## 7. Segurança

- QR: apenas path `/a/<campaign_token>`
- Claim code separado
- HMAC via `M2_ENROLL_HMAC_SECRET`
- Hooks de teste desligados (`M2_POC_TEST_HOOKS=0`)
- HTTPS obrigatório em produção (`M2_PUBLIC_BASE_URL=https://...`)

## 8. Rollback / desligar M2

```powershell
docker compose -f ops\docker-compose.m2.yml down
# ou Ctrl+C no processo python
```

Opcional: remover volume `m2_enrollment_data` (apaga galeria TEMP do M2 — irreversível).

Rollback do M2 **não** exige rollback de M1/M3/TRI.

## 9. Atualizar

```powershell
git checkout feat/m2-enrollment-production
git pull
docker compose -f ops\docker-compose.m2.yml up -d --build
```

## 10. Saúde

`GET /healthz` → `{"ok": true, "service": "m2-enrollment", ...}`

## 11. Checklist pré-DNS Cloudflare

- [ ] Conta Cloudflare / API token
- [ ] Subdomínio isolado (ex. `enrollment.<domínio>`) — **não** o domínio LXP
- [ ] Tunnel ou VPS com porta 8766
- [ ] `M2_PUBLIC_BASE_URL=https://enrollment.<domínio>`
- [ ] Certificado HTTPS (Cloudflare proxy ou Let's Encrypt)
- [ ] Smoke celular com QR real
