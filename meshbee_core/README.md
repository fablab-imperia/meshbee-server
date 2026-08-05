# `meshbee_core/` — shared library

*[Versione italiana](README.it.md)*

**A library, not a service.** It has no `main`, no port and no container of its own.
Both entry points — [`api/`](../api/README.md) and
[`mqtt_handler/`](../mqtt_handler/README.md) — and the scripts in `scripts/` import it,
which is the whole point: a reading arriving over MQTT and one posted to the REST API
go through the *same* validation and the *same* INSERT.

It is installed into both images with `pip install -e .` from `pyproject.toml`
(distribution name `meshbee-core`), which is why both Dockerfiles build from the repo
root rather than from their own directory.

```
api/  ──┐
        ├──▶ meshbee_core ──▶ PostgreSQL
mqtt_handler/ ──┘
scripts/ ───────┘
```

## Contents

| Path | What it is |
|---|---|
| `config.py` | `CoreSettings` — the database fields, and nothing else. |
| `db.py` | The psycopg2 connection pool and `get_db_cursor()`. |
| `schemas.py` | Every pydantic model, and the validation ranges. |
| `security.py` | Password hashing and verification. Framework-free. |
| `errors.py` | `NotFound`, `Conflict`, `InvalidData` — the vocabulary services raise. |
| `repository/` | SQL. One module per table. |
| `services/` | Business decisions. One module per domain area. |

### `repository/` — tables and queries, nothing else

| Module | Covers |
|---|---|
| `utenti.py` | `utenti`. `get_credentials_by_email` is the only projection that includes `password_hash`. |
| `nodi.py` | `nodi`, including `register_if_absent` for the ingest path. |
| `arnie.py` | `arnie` and the `v_arnie_stato` view. `update` uses an `UNSET` sentinel so `attiva` is only touched when explicitly passed. |
| `letture.py` | `letture`. `insert` is the single INSERT both entry points reach; `series` whitelists the column name. |
| `attivita.py` | `log_attivita`, with ownership-scoped update and delete. |
| `accessi.py` | `utenti_arnie` — the association table. |

### `services/` — decisions

| Module | Covers |
|---|---|
| `auth.py` | Authentication and the `read < write < admin` permission ladder. |
| `utenti.py` | Account lifecycle, including the refusal to deactivate yourself. |
| `arnie.py` | Hives, and who is allowed to see which. |
| `letture.py` | Readings, the default one-year window, range validation. |
| `attivita.py` | The activity log. |
| `accessi.py` | Granting and revoking access to a hive. |
| `ingest.py` | The MQTT path: register the node, resolve or create the hive, store the reading. |

## Layer rules

The layering is the reason this package exists, and it is worth stating flatly:

- **`repository/` = tables and queries.** No decisions, no validation, no errors beyond
  what the driver raises. Every function takes a `cursor` as its first argument.
- **`services/` = Meshbee decisions.** They call the repository and raise
  `errors.NotFound` / `Conflict` / `InvalidData`. **Never `HTTPException`** — a service
  does not know it is being called over HTTP, and the MQTT handler calls the same code.
- **Entry points and scripts** validate their input, call *one* service, and translate
  the outcome into whatever their protocol says (a status code, a log line).

So: new business logic goes in a service; new SQL goes in a repository; a new route or
a new topic is a thin call into an existing service. **SQL appearing in `api/`,
`mqtt_handler/` or `scripts/` means it went to the wrong place.**

## Cursor lifecycle

**The caller owns the transaction.** Services and repositories take a cursor and never
open one.

```python
with get_db_cursor() as cursor:          # one block == one transaction
    utenti_service.create_utente(cursor, user)
```

`get_db_cursor()` borrows a connection from the pool, yields a `RealDictCursor` (rows
come back as dicts), and on the way out **commits on a clean exit, rolls back and
re-raises on an exception**, always returning the connection to the pool.

Two consequences worth internalising:

- **Several service calls in one block are one atomic unit.** That is the mechanism to
  reach for when two writes must both happen or neither.
- **Returning quietly instead of raising will commit a partial write.** This is why
  `ingest.register_node_and_resolve_arnia` raises `NotFound` rather than returning
  `None` — a quiet return would have persisted the node registration it had just done.

The pool is opened by each process at startup with its own size:
`init_db_pool(settings, maxconn=...)` — 20 for the API, 10 for the handler, 2 for the
seed. The library never picks its own configuration; settings are always passed in.

## Configuration

`CoreSettings` holds **only** what every process needs — the database:

| Variable | Type | Default |
|---|---|---|
| `DB_HOST` | str | `localhost` (compose: `postgres`) |
| `DB_PORT` | int | `5432` |
| `DB_NAME` | str | `beehive_iot` |
| `DB_USER` | str | `beehive_user` |
| `DB_PASSWORD` | secret | **required** |

Each entry point subclasses it with its own extras: `api/config.py` adds the JWT and
CORS fields, `mqtt_handler/config.py` the `MQTT_*` fields, `scripts/seed.py` the two
initial passwords.

**Put a new field in the narrowest class that needs it.** A required field added to
`CoreSettings` must be present in the environment of *every* service in
`docker-compose.yml`, or that service crashes on import — the `seed` container, for
instance, is never given `JWT_SECRET_KEY` because it has no use for one.

Secrets are `SecretStr`, so they do not leak into a log line or a traceback; read them
with `.get_secret_value()`. `get_core_settings()` is `lru_cache`d — the test suite
clears that cache between tests, which is what makes settings testable at all.

## Validation

The ranges live in `schemas.py`:

| Field | Range | Where else |
|---|---|---|
| `temperatura` | −50 to 100 °C | CHECK `valid_temperatura` |
| `umidita` | 0 to 100 % | CHECK `valid_umidita` |
| `peso` | ≥ 0 kg | CHECK `valid_peso` |
| `latitudine` | −90 to 90 | CHECK `valid_latitudine` |
| `longitudine` | −180 to 180 | CHECK `valid_longitudine` |
| password | 8 chars min, **72 bytes** max | — |
| `ruolo` | `user`, `admin` | CHECK on `utenti.ruolo` |
| `permessi` | `read`, `write`, `admin` | CHECK on `utenti_arnie.permessi` |
| `tipo_attivita` | 8 values | CHECK on `log_attivita.tipo_attivita` |

**Every range is duplicated as a CHECK constraint in `database/init.sql`, and nothing
links the two.** `tests/integration/core/test_schemas.py` is what keeps them honest: it
asserts both sides against a real database. Add a case there whenever you add or change
a validator that mirrors a constraint.

Two more validation notes:

- **`UserLogin.email` is normalised but not format-checked.** A malformed email at
  login must produce a **401**, not a 422 — a validation error would tell an attacker
  which of the two fields was wrong. `UserBase.email` (creating an account) *is*
  checked.
- **The password limit is 72 bytes, not 72 characters.** That is bcrypt's, not ours: it
  truncates silently past 72 bytes, so a longer password would have characters that
  make no difference. Under UTF-8 an emoji costs four.

## Security

`security.py` is deliberately tiny and depends on nothing: bcrypt at **cost 12**,
`get_password_hash` and `verify_password`. Verification returns `False` on *any*
exception (a malformed hash in the database is a failed login, not a 500).

The API and `scripts/seed.py` both use it, which is why a seeded account and one
created through the admin API are indistinguishable.

## Development

The package is bind-mounted into every container, so an edit is live for the API
(uvicorn `--reload`) and needs a restart for the handler.

```bash
docker-compose exec api pytest tests/unit/core tests/integration/core
```

Tests mirror the source layout: `meshbee_core/config.py` →
`tests/unit/core/test_config.py`. **Anything whose substance is SQL belongs in
`tests/integration/`** — a fake cursor only proves we passed a string to `execute()`.
See [`tests/`](../tests/README.md).

## Gotchas

- **Adding a required field to `CoreSettings` can break services that never use it.**
  Narrowest class wins.
- **Never write `nodi.ultimo_messaggio` from Python.** A database trigger on `letture`
  owns that column and fires after you — see [`database/`](../database/README.md).
- **`repository/letture.py::series` whitelists the column name.** It is the one place a
  column name comes from a caller, so it is compared against `SERIES_FIELDS` and raises
  on anything else. Do not "simplify" it into an f-string.
- **`arnie.update` uses an `UNSET` sentinel, not `None`.** `None` is a legitimate value
  to write; the sentinel is how "the caller said nothing about this column" is kept
  distinct, which is what stops a user-facing update from silently retiring a hive.
- **An unknown permission name raises** rather than returning `False` — a typo fails
  closed instead of quietly denying everyone.

## Related

- [`api/`](../api/README.md) — how these errors become status codes.
- [`mqtt_handler/`](../mqtt_handler/README.md) — the other caller, and `services/ingest.py`.
- [`database/`](../database/README.md) — the tables the repository layer talks to.
- [`tests/`](../tests/README.md) — the two tiers and where a new test belongs.
- Main [README](../README.md) — the stack as a whole.
