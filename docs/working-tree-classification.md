# Classificação do working tree pós-baseline (`f4173a9`)

Legenda: **runtime?** / **teste?** / **altera presença?** / **altera banco?** / **commit pré-spike?**

## Commit 1 — `fix/test-isolation-and-baseline`

| Arquivo | Classe | runtime | teste | presença | banco | commit |
|---------|--------|---------|-------|----------|-------|--------|
| `tests/conftest.py` | manter | não | sim | não | temp only | sim |
| `tests/test_dedup_presence.py` | manter | não | sim | não | temp | sim |
| `tests/test_queue.py` | manter | não | sim | não | temp | sim |
| `tests/test_migration_005.py` | manter | não | sim | não | temp/cópia | sim |
| `app/db/init_db.py` | manter | sim (gate 005) | sim | não | só se flag | sim |
| `migrations/sqlite/005_observation_windows.py` | experimental isolado | não (default) | sim | não | experimental | sim |
| `docs/migration-005-experimental.md` | manter | não | — | não | — | sim |
| `docs/baseline-performance-prespike.md` | manter | não | — | não | — | sim |
| `docs/db-backup-prespike.md` | manter | não | — | não | — | sim |

## Commit 2 — `chore/experimental-multimodal-scaffolds`

### Experimental isolado (não integrado ao orchestrator de visão nova)

| Arquivo | runtime | teste | presença | banco | commit |
|---------|---------|-------|----------|-------|--------|
| `app/module_modes.py` | config only | sim | não | não | sim |
| `app/vision/domain.py` | não | indireto | não | não | sim |
| `app/vision/tracking_types.py` | não | sim | não | não | sim |
| `app/vision/identity_binding.py` | **não** | sim | não | não | sim |
| `app/vision/person_phone.py` | **não** | sim | não | não | sim |
| `app/vision/person_tracker.py` | **não** | não | não | não | sim |
| `app/vision/landmarks_adapter.py` | **não** | não | não | não | sim |
| `app/vision/observation_quality.py` | **não** | sim | não | não | sim |
| `app/vision/pose_minimal.py` | **não** | não | não | não | sim |
| `app/vision/expressions/*` | **não** (scripts) | sim/mock | não | não | sim |
| `app/analytics/fusion.py` | **não** | sim | não | não | sim |
| `app/integrations/lxp.py` | **não** | sim | não | não | sim |
| `app/api/v1.py` | parcial (montado) | manual | não | leitura review | sim |
| `app/static/debug_vision.html` | parcial | não | não | não | sim |
| `scripts/spike_*.py` | CLI only | não | não | não | sim |
| `frontend/*` | scaffold | build | não | não | sim |
| `tests/test_multimodal_contracts.py` | não | sim | não | não | sim |
| `validation_dataset/README.md` | não | — | não | não | sim |
| `requirements-spike-*.txt` | não | — | não | não | já no baseline |

### WIP anterior (emocões/dashboard — já no tree antes do excesso multimodal)

| Arquivo | runtime | teste | presença | banco | commit |
|---------|---------|-------|----------|-------|--------|
| `app/pipeline/behavioral.py` | sim | sim | não | behavioral_events | sim |
| `app/pipeline/climate.py` | sim | sim | não | events | sim |
| `app/pipeline/temporal_aggregator.py` | sim | sim | não | via behavioral | sim |
| `app/vision/facial_signals.py` | sim | sim | não | não | sim |
| `app/vision/behavioral_taxonomy.py` | sim | sim | não | não | sim |
| `app/vision/phone_yolo.py` | se flag | não | não | via behavioral | sim |
| `app/auth.py` | sim | não | não | não | sim |
| `app/services/dashboard_reports.py` | sim | não | não | leitura | sim |
| `app/static/dashboard.html` | sim | não | não | não | sim |
| `migrations/sqlite/004_behavioral_session.py` | via init | não | schema | sim | sim |
| `tests/test_behavioral_module.py` | não | sim | não | não | sim |
| `docs/DECISIONS_MODULO_EMOCOES.md` / `DOD_*` | docs | — | — | — | sim |
| modified: `orchestrator.py`, `presence.py`, `config.py`, `models.py`, `repo.py`, `main.py`, `config.yaml`, `index.html` | sim (WIP) | parcial | presença intacta nas regras | sim | sim |

### Docs de claims

| Arquivo | Ação |
|---------|------|
| `docs/FINAL_REPORT_MODULO_VISUAL.md` | manter como auditoria honesta |
| `docs/gates.md` | corrigir claims |
| `docs/working-tree-classification.md` | este arquivo |

### Remover / não versionar

| Item | Motivo |
|------|--------|
| `scripts/_count_005.py` | helper temporário de auditoria |
| `frontend/node_modules`, `frontend/dist` | build artifacts |
| `data/backups/*` | local only (gitignore) |
| frames em `data/spike/` | nunca no git |

**Regra:** nenhum módulo novo conectado ao orchestrator nesta fase.
