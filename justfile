# Shortcuts for multi-step or hard-to-remember actions (https://just.systems).
# Anything that is a single docker-compose command is documented as that command
# instead (see README.md). `just` alone lists the recipes.

# Recipe arguments reach the shell as "$@", so quoting survives:
# `just test -k 'a or b'` hands pytest exactly two arguments.
set positional-arguments

compose := "docker compose"

[private]
default:
    @just --list --unsorted

# --- Setup ---

# First-time setup: .env from the example, broker password, start the stack
setup:
    #!/usr/bin/env bash
    set -euo pipefail
    if [ ! -f .env ]; then
        cp .env.example .env
        echo "✓ .env created from .env.example"
        echo "⚠️  Open .env and set real passwords, then run: just setup"
        exit 0
    fi
    {{ just_executable() }} mqtt-passwd
    {{ just_executable() }} start

# Start every service
start:
    {{ compose }} up -d
    @echo "API HTTP:  http://localhost:8000/docs"
    @echo "API HTTPS: https://localhost:8443/docs (requires 'just certs')"

# Generate mosquitto/config/passwd from MQTT_USER / MQTT_PASSWORD in .env
mqtt-passwd:
    #!/usr/bin/env bash
    set -euo pipefail
    if [ ! -f .env ]; then
        echo "❌ No .env found. Run 'just setup' first." >&2
        exit 1
    fi
    set -a; . ./.env; set +a
    mkdir -p mosquitto/config
    docker run --rm \
        -v "$PWD/mosquitto/config:/mosquitto/config" \
        eclipse-mosquitto:2.0 \
        mosquitto_passwd -b -c /mosquitto/config/passwd "$MQTT_USER" "$MQTT_PASSWORD"
    echo "✓ mosquitto/config/passwd generated"

# Generate the local HTTPS certificate for the Caddy proxy (requires mkcert)
certs:
    ./caddy/make-certs.sh

# --- Quality ---

# Run the test suite in the api container; extra arguments go to pytest
test *args:
    {{ compose }} exec api pytest "$@"

# Check lint and formatting with ruff in the api container
lint:
    {{ compose }} exec api ruff check .
    {{ compose }} exec api ruff format --check .

# Apply ruff's safe fixes and formatting in the api container
format:
    {{ compose }} exec api ruff check --fix .
    {{ compose }} exec api ruff format .

# What .github/workflows/ci.yml runs, locally. One-off containers (`run --rm
# --no-deps`), so the stack doesn't have to be up and the dev database isn't touched.

# Run the whole CI locally: image builds, compose check, ruff, tests, pip-audit
ci:
    {{ compose }} build api mqtt-handler
    MESHBEE_DOMAIN=ci.example.org ACME_EMAIL=ci@example.org \
        {{ compose }} -f docker-compose.yml -f docker-compose.prod.yml config -q
    {{ compose }} --profile test up -d --wait postgres-test
    {{ compose }} run --rm --no-deps -v ./.github:/app/.github:ro api sh -c \
        'ruff check . && ruff format --check . && pytest && sh .github/scripts/pip_audit.sh'

# Check the installed dependencies for known vulnerabilities (needs network)
audit:
    {{ compose }} run --rm --no-deps -v ./.github:/app/.github:ro api sh .github/scripts/pip_audit.sh

# Regenerate api/openapi.json and the MQTT payload schema (api container up)
contract:
    {{ compose }} exec api python -m scripts.export_openapi
    {{ compose }} exec api python -m scripts.export_mqtt_schema

# --- Database ---

# Dump the database to backups/backup_<timestamp>.sql
db-backup:
    mkdir -p backups
    {{ compose }} exec -T postgres pg_dump -U beehive_user beehive_iot > "backups/backup_$(date +%Y%m%d_%H%M%S).sql"
    @echo "✓ Backup written to backups/"

# Restore a plain SQL dump made by db-backup
db-restore file:
    {{ compose }} exec -T postgres psql -U beehive_user beehive_iot < "$1"
    @echo "✓ Database restored from $1"

# Remove containers AND volumes: destroys every reading
[confirm("This deletes ALL data (docker compose down -v). Continue? [y/N]")]
clean-all:
    {{ compose }} down -v
