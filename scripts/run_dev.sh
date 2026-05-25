#!/bin/bash

# Script para rodar em desenvolvimento (Linux/Mac)

set -e

echo "=== Dulino Edge Vision - Dev Mode ==="

# Verificar se .env existe
if [ ! -f .env ]; then
    echo "Criando .env a partir de .env.example..."
    cp .env.example .env
    echo "Por favor, edite .env com suas configurações"
fi

# Criar diretório de dados
mkdir -p data

# Instalar dependências se necessário
if [ ! -d "venv" ]; then
    echo "Criando ambiente virtual..."
    python3 -m venv venv
fi

source venv/bin/activate

echo "Instalando dependências..."
pip install -r requirements.txt

echo "Iniciando aplicação..."
export PYTHONUNBUFFERED=1
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
