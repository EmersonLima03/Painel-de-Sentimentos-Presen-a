# syntax=docker/dockerfile:1
# M2 Enrollment Escalável — imagem ISOLADA.
# NÃO inclui app/vision, TRI, M1, M3, face_embeddings de produção.

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    M2_POC_TEST_HOOKS=0

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /m2

COPY requirements-poc.txt .
RUN pip install --no-cache-dir -r requirements-poc.txt \
    && pip install --no-cache-dir facenet-pytorch onnxruntime 2>/dev/null || true

COPY scripts/ ./scripts/
COPY ui_gestor/ ./ui_gestor/
COPY ui_aluno/ ./ui_aluno/
COPY ui/ ./ui/
COPY data/ ./data/
COPY manifests/ ./manifests/
# models/ is gitignored globally; create empty runtime dir (no weights in image).
RUN mkdir -p /m2/models

RUN mkdir -p /m2/results/enrollment_escalavel /m2/results/gallery_temp /m2/results/crops_enrollment \
    && useradd --create-home --uid 10001 m2user \
    && chown -R m2user:m2user /m2

USER m2user

EXPOSE 8766

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8766/healthz', timeout=3)"

# Persistência isolada: SQLite em volume (não face_embeddings de produção).
CMD ["python", "scripts/enrollment_gestor_server.py", "--host", "0.0.0.0", "--port", "8766"]
