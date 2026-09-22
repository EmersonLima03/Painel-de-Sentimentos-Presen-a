# Operação — Módulo 2 Enrollment Escalável (serviço isolado)

## 1. Arquitetura

```
Internet → HTTPS (proxy/Cloudflare) → m2-enrollment:8766
  ├── /gestor/          UI gestor
  ├── /a/<token>        UI aluno (QR)
  ├── /api/gestor/*     campanhas / QR / progresso / revogação
  ├── /api/aluno/*      claim / sessão / frames
  └── /healthz          healthcheck

Galeria TEMP: /m2/results/gallery_temp/enrollment_campaigns/
SQLite POC:   /m2/results/enrollment_escalavel/*.db

NÃO conecta: TRI | M1 | M3 | face_embeddings produção | reload_matcher
```

## 2. URL

- Lab local: `http://127.0.0.1:8766/gestor/`
- Produção: definir `M2_PUBLIC_BASE_URL` (HTTPS) e apontar DNS/proxy para a porta 8766.

**Bloqueio atual:** não há Cloudflare/DNS/credenciais configurados neste repositório.
Domínio LXP `sde.sistemadulino.com.br` é **produção LXP — não usar** para M2.

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
