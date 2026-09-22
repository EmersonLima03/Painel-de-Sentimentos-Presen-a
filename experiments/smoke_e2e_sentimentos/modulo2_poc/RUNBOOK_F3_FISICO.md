# Runbook — teste físico F3 (Enrollment Escalável A)

## O que o Playwright NÃO valida
- Câmera real do celular (`getUserMedia` com rosto humano)
- YuNet / quality / pose / alignment em condições reais de luz
- Reconhecimento pós-cadastro (UNKNOWN / multi-pessoa) com identidades reais

## Procedimento sugerido (você + mãe)

1. No PC:
   ```bash
   cd experiments/smoke_e2e_sentimentos/modulo2_poc
   python scripts/enrollment_gestor_server.py --host 0.0.0.0 --port 8766
   ```
   Abrir `http://<IP-da-LAN>:8766/gestor/` → Escola Demo → 8º Ano A → Iniciar campanha → anotar códigos.

2. Celular (mesmo Wi‑Fi / HTTPS via ngrok se o browser exigir):
   - Escanear QR → digitar **código do Dulin** → enrollment **sem óculos** até “Cadastro concluído”.
   - No gestor, conferir Dulin = concluído.

3. Segundo celular ou mesmo aparelho:
   - Mesmo QR → código da **Mae** → enrollment; se usar óculos nas aulas, escolher **Sim** e capturar 1 extra.

4. Depois (ainda POC / TEMP):
   - Verificar pastas `results/gallery_temp/enrollment_campaigns/<campaign_id>/`
   - Rodar probes recognize / UNKNOWN / multiperson **sobre a galeria da campanha** (não produção).

## Critérios de aceite físico
- [ ] Dois cadastros completed no painel do gestor
- [ ] Templates `.npy` só em `enrollment_campaigns/`
- [ ] `product_db_written: false` e sem `reload_matcher`
- [ ] Sem alterações em `app/vision/**` / `config.tri.yaml`

## F4 — lab USB interativo (mesmo pipeline F3)

```powershell
cd experiments\smoke_e2e_sentimentos\modulo2_poc
python scripts\f4_e2e_lab_physical.py --webcam 2 --timeout 180
# Opcional: --glasses-mae  /  --glasses-dulin
```

Seguir os prompts no terminal (uma pessoa por vez nas poses; depois recognize / UNKNOWN / multi).
Saída: `results/enrollment_escalavel/f4/F4_E2E_SUMMARY.json`
