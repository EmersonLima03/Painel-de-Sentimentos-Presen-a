# Migration 005 — experimental (observation windows)

## Status
Experimental. **Não** faz parte do caminho de produção obrigatório.

## Aplicação
- Automática no `init_database` **somente** se `EXPERIMENTAL_SQLITE_005=1` (ou `apply_experimental_005=True`).
- Default: **não aplica** em startup normal.

## Tabelas
- `raw_observation_windows`
- `engagement_windows_v2`
- `climate_windows_v2`
- `model_benchmarks`

## Rollback (manual, em cópia — nunca como rotina no DB real sem backup)

```powershell
# Em CÓPIA do banco apenas:
python migrations/sqlite/005_observation_windows.py rollback path\to\copia.db
```

Isso executa `DROP TABLE IF EXISTS` apenas nas 4 tabelas acima.

## Testes
Ver `tests/test_migration_005.py` — empty DB e cópia temporária; assert de mtime do DB real.

## Nota
O banco real pode já conter essas tabelas de uma aplicação anterior. Não remover dados sem decisão explícita. Backup pré-spike em `data/backups/`.
