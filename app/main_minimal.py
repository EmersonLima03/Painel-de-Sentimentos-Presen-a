"""Versão mínima do FastAPI para teste - SEM orchestrator."""

from fastapi import FastAPI
from app import __version__
import time

# Criar app simples
app = FastAPI(
    title="Dulino Edge Vision - Minimal",
    version=__version__
)

start_time = time.time()

@app.get("/")
async def root():
    return {
        "status": "ok",
        "message": "Servidor funcionando!",
        "version": __version__
    }

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "version": __version__,
        "uptime_seconds": int(time.time() - start_time),
        "message": "Servidor está funcionando!"
    }

@app.get("/test")
async def test():
    return {"message": "Teste OK!", "timestamp": time.time()}
