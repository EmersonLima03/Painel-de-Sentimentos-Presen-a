# Dulino Edge Vision — Presença

Sistema **edge** de visão para salas de aula: presença facial (YuNet + FaceNet), indicadores visuais estimados e dashboard local. O vídeo **não** é enviado à nuvem por padrão.

## Estado atual (jul/2026)

**Branch:** `feat/painel-de-sentimentos` — [detalhes em docs/ESTAGIO_ATUAL.md](docs/ESTAGIO_ATUAL.md)

- **Dashboard React unificado** + WebSocket ao vivo (`/dashboard`, `/debug/vision`)
- **Presença + identidade** por track (continuidade quando rosto some)
- **Indicadores estimados:** atenção, expressão aparente, sonolência, celular — com estado **inconclusivo** quando rosto ocluído
- **Instabilidade conhecida:** diferenciar **cabeça baixa** vs **rosto tampado** (mão/objeto) — em calibração
- Providers de expressão: **experimentais** — não aprovados para produção
- **LXP / Intelbras campo:** pendente

Indicadores são estimativas visuais — **não** diagnóstico nem comprovação de aprendizagem.

## Quick start (demo)

```powershell
.\venv\Scripts\Activate.ps1
$env:RUNTIME_MODE="demo"
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

- Dashboard: http://127.0.0.1:8000/dashboard  
- Debug: http://127.0.0.1:8000/debug/vision  

```powershell
pytest tests -q
cd frontend; npm run typecheck; npm run build
```

## Documentação

**Tudo está em [docs/README.md](docs/README.md)** — arquitetura, operações, API, testes, privacidade, roadmap e troubleshooting.

## Funcionalidades principais

- Cadastro e reconhecimento facial local  
- Check-in / deduplicação / sessões  
- Modos `demo` | `offline` | `rtsp`  
- API v1 + WebSocket  
- Revisão humana de eventos  
- LXP mock/outbox (sem cliente HTTP até spec)  

## Licença

Ver repositório / política da organização, se aplicável.
