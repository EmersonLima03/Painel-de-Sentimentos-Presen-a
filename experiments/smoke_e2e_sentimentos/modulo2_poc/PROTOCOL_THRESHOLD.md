# PROTOCOL — Threshold / UNKNOWN (POC)

**Objetivo:** calibrar `score` e `margin` para decisão open-set **sem** alterar thresholds de produção (`config.yaml` / TRI).

## Regra obrigatória

```
top1_candidate
  if score >= T AND margin >= M:
      → IDENTIDADE
  else:
      → UNKNOWN
```

Nunca aceitar “o mais parecido” sem T e M.

## Métricas

| Métrica | Definição |
|---------|-----------|
| TP | pessoa cadastrada → ID correta |
| FP | pessoa A → ID de B (ou desconhecido → algum ID) |
| FN | pessoa cadastrada → UNKNOWN indevido |
| UNKNOWN correto | não cadastrado → UNKNOWN |
| top1 | maior score |
| margin | top1 − melhor competidor de **outro** student_id |

## Eixos de teste

Distância, pose, óculos, iluminação, N pessoas no frame, tamanho do rosto (px), tamanho da galeria (N alunos × templates).

Preencher `manifests/threshold_runs.csv`.

## Como obter T e M (sem inventar)

1. Coletar embeddings de teste em galeria TEMP (mesmo embedder em todo o run).
2. Pares genuínos (mesma pessoa) → distribuição de scores.
3. Pares impostores (pessoas diferentes) → distribuição.
4. Escolher T no crossover conservador (priorizar baixo FP).
5. Escolher M para separar irmãos/ângulos próximos.
6. Validar hold-out (UNKNOWN forçado com identidades fora da galeria).

## Referência de produção (somente leitura — NÃO alterar)

| Uso | Valor atual no produto |
|-----|------------------------|
| check-in threshold | 0.70 |
| match_margin | 0.10 |
| th_on / th_off | 0.75 / 0.68 |

O POC pode propor T'/M' **diferentes** para um embedder challenger; promoção ao produto exige aprovação separada.

## PASS / FAIL (POC)

**PASS:** FP ≈ 0 no conjunto de teste acordado; UNKNOWN correto para fora-galeria; TP documentado por condição.

**FAIL:** FP recorrente; ou UNKNOWN excessivo que inviabiliza presença sem evidência de causa (px baixos, pose, etc.).

## Estado atual

Calibração empírica neste repositório: **NÃO TESTADO** (corpus de benchmark ainda vazio).
