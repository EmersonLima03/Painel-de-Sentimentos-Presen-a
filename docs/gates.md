# Gates entre fases (sanitizado pré-spike)

| Gate | Status | Nota |
|------|--------|------|
| Fase 0 baseline docs + tag `baseline-fase-0` | **funcional** | `f4173a9` |
| Isolamento de testes + DB real protegido | **funcional** | `pytest` 45 passed; hash DB estável |
| Migration 005 | **experimental** | gated; testes em temp/cópia |
| Baseline perf 5 min | **não validado** | câmera bloqueada (PASSWORD / unreachable) |
| API v1 / WS / debug vision | **parcialmente funcional** | montados; não calibrados |
| Providers / binding / fusion / phone assoc | **não integrado** | unitários apenas |
| Frontend React | **scaffold** | build OK; não substitui `/dashboard` |
| LXP | **experimental** (mock) | sem HttpClient / retry / DLQ |
| Fase 0.5 spike | **bloqueado** até gate abaixo | |

## Gate objetivo para iniciar Fase 0.5

PASS somente se:

1. Tag `pre-spike-sanitized` existir
2. `pytest tests -q` verde
3. `data/dulino_edge.db` com backup hash documentado
4. Working tree limpo no commit da tag
5. RTSP Intelbras alcançável **ou** autorização explícita para spike offline com corpus pré-capturado
6. Autorização explícita do usuário para 0.5

**Não** declarar Fases 0.5–9 como concluídas.
