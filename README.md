# Dulino Edge Vision — Presença

Sistema **edge** de visão para salas de aula: presença facial (YuNet + FaceNet), indicadores visuais estimados e dashboard local. O vídeo **não** é enviado à nuvem por padrão.

## Estado atual

- **Demo completo e testado** (8 alunos fictícios, API, WebSocket, dashboard React)
- **Presença** funcional no runtime
- **Câmera Intelbras / validação de campo:** pendente (credencial ou corpus)
- Providers reais de expressão: **experimentais** — não aprovados para produção

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
