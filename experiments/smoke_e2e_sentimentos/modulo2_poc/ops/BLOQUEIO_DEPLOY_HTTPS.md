# BLOQUEIO — Deploy HTTPS / Cloudflare (missão M2)

**Status:** PARADO aqui — sem gambiarra.

## O que já está pronto

- Branch `feat/m2-enrollment-production` commitada e pushada no `origin`
- Código M2 versionado (60 arquivos), biometria fora do Git
- Testes F0–F4: **41 passed**
- Empacotamento Docker isolado em `ops/`
- `M2_PUBLIC_BASE_URL` + `/healthz` no servidor
- Documentação `ops/OPERACAO_PRODUCAO.md`

## O que falta (bloqueio real)

| Item | Situação |
|------|----------|
| Cloudflare / Wrangler | **Não instalado** neste ambiente |
| `cloudflared` | **Não instalado** / sem `~/.cloudflared` |
| Config Cloudflare no repo | **Inexistente** |
| API token / conta CF | **Não disponível** ao agente |
| Domínio isolado para M2 | **Não definido** (não inventar) |
| `sde.sistemadulino.com.br` | Domínio **LXP produção — PROIBIDO** para M2 |

Sem esses itens **não é possível** publicar HTTPS público nem smoke test pelo celular com URL real.

## O que NÃO será feito

- Não alterar DNS do LXP
- Não inventar domínio
- Não login Cloudflare sem credencial
- Não merge em `main`
- Não tocar M1/M3/TRI

## Próximo passo humano (desbloqueio)

1. Criar subdomínio isolado (ex. `enrollment.<seu-dominio>`) na Cloudflare **ou** VPS + TLS.
2. Instalar Tunnel (`cloudflared`) **ou** apontar A/CNAME para host com porta 8766.
3. Preencher `.env`:
   - `M2_PUBLIC_BASE_URL=https://enrollment.<dominio>`
   - `M2_ENROLL_HMAC_SECRET=<aleatório>`
4. `docker compose -f ops/docker-compose.m2.yml up -d --build`
5. Smoke celular: QR → claim → enrollment → completed.

Até lá, o serviço permanece operacional **localmente** em `http://127.0.0.1:8766`.
