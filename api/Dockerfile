# Build context is the repository root (see docker-compose.yml), not ./api:
# the image needs meshbee_core, which both entry points import.
FROM python:3.11-slim

WORKDIR /app

# Installa dipendenze di sistema
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev && \
    rm -rf /var/lib/apt/lists/*

# Copia requirements e installa dipendenze Python
COPY api/requirements.txt api/requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-dev.txt

# Shared library, editable so the bind-mounted source is what actually runs.
COPY pyproject.toml ./
COPY meshbee_core ./meshbee_core
RUN pip install --no-cache-dir -e .

# Copia il codice dell'applicazione
COPY api ./api
# The test suite covers both entry points from this container (see
# tests/integration/test_ingest_parity.py); the API itself never imports it.
COPY mqtt_handler ./mqtt_handler
# The `seed` service shares this image and runs `python -m scripts.seed`.
COPY scripts ./scripts
COPY tests ./tests
COPY pytest.ini ./

# Espone la porta 8000
EXPOSE 8000

# Comando di avvio
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
