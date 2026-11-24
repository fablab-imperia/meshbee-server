# Shortcuts for multi-step or hard-to-remember actions. Anything that is a single
# docker-compose command is documented as that command instead (see README.md).

.PHONY: help setup start mqtt-passwd certs test lint format ci contract \
        db-backup db-restore clean-all

COMPOSE = docker compose

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

# Setup
setup: ## First-time setup: .env from the example, broker password, start the stack
	@if [ ! -f .env ]; then \
		cp .env.example .env; \
		echo "✓ File .env creato da .env.example"; \
		echo ""; \
		echo "⚠️  IMPORTANTE: Apri .env e imposta password sicure prima di continuare!"; \
		echo "   Poi riesegui: make setup"; \
		exit 0; \
	fi
	$(MAKE) mqtt-passwd
	$(MAKE) start

start: ## Start every service
	$(COMPOSE) up -d
	@echo "API HTTP:  http://localhost:8000/docs"
	@echo "API HTTPS: https://localhost:8443/docs (requires 'make certs')"

mqtt-passwd: ## Generate mosquitto/config/passwd from MQTT_USER / MQTT_PASSWORD in .env
	@if [ ! -f .env ]; then \
		echo "❌ File .env non trovato. Esegui prima 'make setup'"; \
		exit 1; \
	fi
	@set -a; . ./.env; set +a; \
	mkdir -p mosquitto/config; \
	docker run --rm \
		-v "$$(pwd)/mosquitto/config:/mosquitto/config" \
		eclipse-mosquitto:2.0 \
		mosquitto_passwd -b -c /mosquitto/config/passwd "$$MQTT_USER" "$$MQTT_PASSWORD"; \
	echo "✓ File password Mosquitto generato in mosquitto/config/passwd"

certs: ## Generate the local HTTPS certificate for the Caddy proxy (requires mkcert)
	./caddy/make-certs.sh

# Quality
test: ## Run the whole test suite in the api container
	$(COMPOSE) exec api pytest

lint: ## Check lint and formatting with ruff in the api container
	$(COMPOSE) exec api ruff check .
	$(COMPOSE) exec api ruff format --check .

format: ## Apply ruff's safe fixes and formatting in the api container
	$(COMPOSE) exec api ruff check --fix .
	$(COMPOSE) exec api ruff format .

# What .github/workflows/ci.yml runs, locally. One-off containers (`run --rm
# --no-deps`), so the stack doesn't have to be up and the dev database isn't touched.
ci: ## Run the whole CI locally: image builds, compose check, ruff, tests (stack need not be up)
	$(COMPOSE) build api mqtt-handler
	MESHBEE_DOMAIN=ci.example.org ACME_EMAIL=ci@example.org \
		$(COMPOSE) -f docker-compose.yml -f docker-compose.prod.yml config -q
	$(COMPOSE) --profile test up -d --wait postgres-test
	$(COMPOSE) run --rm --no-deps api sh -c \
		'ruff check . && ruff format --check . && pytest'

contract: ## Regenerate api/openapi.json and the MQTT payload schema (api container up)
	$(COMPOSE) exec api python -m scripts.export_openapi
	$(COMPOSE) exec api python -m scripts.export_mqtt_schema

# Database
db-backup: ## Dump the database to backups/backup_<timestamp>.sql
	@mkdir -p backups
	$(COMPOSE) exec postgres pg_dump -U beehive_user beehive_iot > backups/backup_$$(date +%Y%m%d_%H%M%S).sql
	@echo "✓ Backup creato in backups/"

db-restore: ## Restore a plain SQL dump (FILE=path/to/backup.sql)
	@if [ -z "$(FILE)" ]; then \
		echo "❌ Errore: specifica FILE=path/to/backup.sql"; \
		exit 1; \
	fi
	cat $(FILE) | $(COMPOSE) exec -T postgres psql -U beehive_user beehive_iot
	@echo "✓ Database ripristinato da $(FILE)"

clean-all: ## Remove containers AND volumes (DESTROYS ALL DATA, asks first)
	@echo "⚠️  ATTENZIONE: Questo comando cancellerà tutti i dati!"
	@read -p "Sei sicuro? [y/N] " -n 1 -r; \
	echo; \
	if [[ $$REPLY =~ ^[Yy]$$ ]]; then \
		$(COMPOSE) down -v; \
		echo "✓ Tutto rimosso"; \
	else \
		echo "Operazione annullata"; \
	fi

.DEFAULT_GOAL := help
