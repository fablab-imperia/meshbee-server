# Build context is the repository root (see docker-compose.yml), not
# ./mqtt_handler: the image needs meshbee_core, which both entry points import.
FROM python:3.14-slim

WORKDIR /app

# No system packages: every dependency ships a prebuilt wheel, and
# psycopg[binary] bundles its own libpq. A pin that falls back to a source
# build fails here instead of compiling silently.

# Copia requirements e installa dipendenze Python
COPY mqtt_handler/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Shared library, editable so the bind-mounted source is what actually runs.
COPY pyproject.toml ./
COPY meshbee_core ./meshbee_core
RUN pip install --no-cache-dir -e .

# Copia il codice dell'applicazione
COPY mqtt_handler ./mqtt_handler

# Comando di avvio
CMD ["python", "-m", "mqtt_handler"]
