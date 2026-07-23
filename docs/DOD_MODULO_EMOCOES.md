# Módulo de Emoções e Dashboard (40%) — Definition of Done

## Entregue neste código

| Item DoD | Status | Evidência |
|----------|--------|-----------|
| Inferência local de sinais observáveis | OK | `app/vision/facial_signals.py`, `app/pipeline/behavioral.py`, `temporal_aggregator.py` |
| Canal clima/humor aparente agregado | OK | `app/pipeline/climate.py` + evento `climate_window` |
| Sem frames persistidos por padrão | OK | Apenas eventos JSON / embeddings |
| Dashboard unificado | OK | `/dashboard` → `app/static/dashboard.html` |
| Relatórios engajamento + humor | OK | `/dashboard/api/engagement`, `/dashboard/api/climate` |
| Timeline da aula | OK | `/dashboard/api/timeline` |
| Revisão humana | OK | `/dashboard/api/events` + POST review |
| Presença periódica por sessão | OK | `class_sessions` + chave `session:{id}` |
| Auth mínima | OK | `API_AUTH_TOKEN` + `X-API-Token` |
| Consentimento / exclusão LGPD mínima | OK | `/privacy/consent`, `DELETE /privacy/students/{id}` |
| Nomenclatura ética | OK | taxonomia sem “Distraido”/diagnóstico |
| Phone YOLO opcional | OK | `phone_yolo_enabled: false` por padrão |
| Endpoint status DoD | OK | `GET /module/dod` |

## Como validar (smoke)

```powershell
cd Presenca
.\venv\Scripts\Activate.ps1   # se houver
pytest tests/test_behavioral_module.py -q
uvicorn app.main:app --host 127.0.0.1 --port 8000
# Abrir http://127.0.0.1:8000/dashboard
```

## Disclaimer obrigatório

Estimativa visual observável. Não constitui diagnóstico emocional, psicológico, médico ou comportamental definitivo.
