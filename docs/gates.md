# Gates entre fases

Registro de status. Nenhuma fase seguinte inicia sem **PASS** + autorização quando o plano exigir.

| Gate | Critério resumido | Status | Data |
|------|-------------------|--------|------|
| **0 → 0.5** | Docs baseline; testes registrados; métricas; deps; thresholds congelados; commit/tag; `data/spike` preparado; entrega apresentada | **PASS (docs)** — aguarda autorização explícita do usuário para iniciar 0.5 | 2026-07-23 |
| 0.5 → 1 | Relatório spike; provider ≤ shadow; `/debug/vision` protegido; presença nas tolerâncias | PENDING | |
| 1 → 2 | Contratos/modos; paridade nas tolerâncias do baseline; **autorização explícita** Fases 2+ | PENDING | |
| 2 → 3 | Binding não escreve presença; métricas track | PENDING | |
| 3 → 4 | Provider em shadow; provenance | PENDING | |
| 4 → 5 | Celular possible/probable only | PENDING | |
| 5 → 6 | Temporal; zero escrita attendance | PENDING | |
| 6 → 7 | Migrations + API/WS | PENDING | |
| 7 → 8 | Dashboard educacional + disclaimer | PENDING | |
| 8 → 9 | Longitudinal; único path shadow→production | PENDING | |
| 9 → 10 | LXP mock/fila; Http só com spec | PENDING | |

## Autorização

| Escopo | Status |
|--------|--------|
| Fase 0 | Concluída nesta entrega |
| Fase 0.5 | Requer autorização explícita após esta entrega |
| Fases 2–10 | Bloqueadas no plano até nova autorização (execução sob “implement plan” avança com gates técnicos documentados) |

## Critério 8 pessoas (métricas a registrar)

Estabilidade de tracks; troca de identidade; duplicação de presença (=0); recuperação pós-oclusão; latência; filas; CPU/memória — ver `baseline-metrics.md` e plano.
