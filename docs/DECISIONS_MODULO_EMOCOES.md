# Decisões fechadas — Módulo de Emoções e Dashboard (40%)

Defaults do plano §20 aplicados para implementação (sem esperar nova aprovação):

| # | Decisão | Valor adotado |
|---|---------|---------------|
| 2 | Presença | Amostragem periódica na `class_session` + check-in inicial; dedup por sessão |
| 3 | Identidade nos sinais | Agregados por sala/zona no MVP; `anonymous_track_id` nos eventos |
| 4 | Durações | Fora de campo ≥ 45s; sonolência ≥ 60s combinada; janela clima 15s |
| 5 | FER | Opcional por flag `climate_use_fer`; clima base = pose + energia |
| 8 | Naming UI | “Clima aparente” / “Engajamento aparente” (nunca diagnóstico) |
| 10 | UI | Web unificada no edge (`/dashboard`) |

**Disclaimer obrigatório em UI e payloads:** estimativa visual observável; não é diagnóstico emocional, psicológico ou médico.
