# Backup e auditoria do banco — pré-spike

## Backup

| Campo | Valor |
|-------|-------|
| Origem | `data/dulino_edge.db` |
| Cópia | `data/backups/dulino_edge_pre_spike_20260723_100747.db` |
| Tamanho | 1945600 bytes |
| SHA256 (pré-saneamento) | `1802616AB351CC1755E141458BFA2F830DAEDBA96311C831A39D958E3E306833` |
| SHA256 (pós-saneamento / atual) | ver backup `dulino_edge_post_sanitize_*.db` — pode diferir por WAL/checkpoint externo; **pytest isolado não altera** o arquivo (hash estável antes/depois da suite) |
| Hash cópia pré = origem pré | sim |

(Backups sob `data/` permanecem locais / gitignored.)

## Tabelas no banco real (snapshot auditoria)

Inclui core + tabelas experimentais 005 já presentes de aplicação anterior:

- attendance_cache, behavioral_events, class_sessions, device_state, events, face_embeddings, privacy_audits, student_consents, students
- **005:** raw_observation_windows, engagement_windows_v2, climate_windows_v2, model_benchmarks

Contagens 005 (2026-07-23):

| Tabela | COUNT(*) |
|--------|----------|
| raw_observation_windows | 0 |
| engagement_windows_v2 | 0 |
| climate_windows_v2 | 0 |
| model_benchmarks | 0 |

## Proteções

- Testes usam SQLite temporário (`tests/conftest.py`)
- `init_database` **não** reaplica 005 por default (`EXPERIMENTAL_SQLITE_005` necessário)
- Rollback documentado em `docs/migration-005-experimental.md`
