# `tests/` — the test suite

*[Versione italiana](README.it.md)*

One pytest suite covering **everything**: both entry points, the shared library and the
scripts. It lives at the repo root rather than inside each package because
`tests/integration/test_ingest_parity.py` has to compare the API and the MQTT paths in
a single test, and neither package can own that.

## Running

**In the container, always.** `config.py` builds its `Settings` at import time, so on
the host collection fails before a single test runs.

```bash
docker-compose --profile test up -d postgres-test    # once per boot, for the integration tier
docker-compose exec api pytest                       # everything (= make test)
```

Paths are relative to the repo root, which is `/app` in the container:

```bash
docker-compose exec api pytest -m "not integration"          # no database needed
docker-compose exec api pytest -m integration
docker-compose exec api pytest tests/unit/core/test_config.py
docker-compose exec api pytest tests/unit/core/test_config.py::test_database_url_escapes_special_characters
docker-compose exec api pytest -k "password or token" -v
docker-compose exec api pytest -x --lf                       # stop at the first failure, then rerun just it
```

`postgres-test` is behind the `test` profile, so a plain `docker-compose up` does not
start it. Its data lives in tmpfs and it publishes no port.

**Without it, the integration tier fails with an actionable message — it does not
skip.** That is deliberate: a suite that goes green because a third of it silently
disappeared is worse than a red one.

A new dev dependency means `docker-compose build api` (`requirements-dev.txt` is baked
into the image). New *test files* need nothing — `tests/` is bind-mounted.

**CI runs the same suite** on every pull request and every push to `main`
(`.github/workflows/ci.yml`), outside Docker: Python 3.11 on the runner, a throwaway
`postgres:15-alpine` service in place of `postgres-test`, and
`TEST_DB_HOST=localhost` / `TEST_DB_SCHEMA=database/init.sql` pointing the fixtures at
it. So a test may not depend on anything only the `api` container provides — a path
under `/app`, or an environment variable compose sets. CI only exports
`DB_PASSWORD` and `JWT_SECRET_KEY`.

## Two tiers

```
tests/
  unit/           no database at all
  integration/    a real PostgreSQL
```

The split is the top level of the tree because it drives the marker: anything under
`integration/` is marked `integration` automatically, by path, in
`tests/integration/conftest.py`. Source paths mirror *inside* each tier, one test module
per source module — `meshbee_core/config.py` → `tests/unit/core/test_config.py`.

**Unit** is for logic with no SQL in it: settings resolution, validators, JWT and
password handling, permission arithmetic, payload parsing.

**Integration** is for everything whose substance *is* SQL — column names, joins,
parameter order, CHECK constraints. A fake cursor only ever proves that we passed a
string to `execute()`; it cannot tell you the string was wrong. So: **if the thing you
are testing is a query, it belongs in `integration/`.**

The `test_schema` session fixture drops the schema and rebuilds it with Alembic's
`upgrade head` once per run — the path a fresh install takes — so every revision is
exercised on every run and cannot quietly rot. `integration/test_migrations.py` then
checks that what the revisions build is what `meshbee_core/models.py` describes, CHECK
bodies included.

## The two modules that carry the most weight

**`integration/core/test_schemas.py` — model↔schema agreement.** The ranges come from
one place, `meshbee_core/limits.py`, but a database only has the CHECKs its migrations
gave it. This module derives its cases from the published MQTT contract and asserts
that the pydantic schemas and the real database refuse the same values. Add a case
whenever you add a bound.

**`integration/test_ingest_parity.py` — the reason the shared layer exists.** It proves
the API path and the MQTT path write **equal rows**, every column but `id_lettura`.
Its `deliver` fixture wraps each message in a SAVEPOINT, because in production every
message gets its own transaction and the test must not let one message see another's
uncommitted work.

**`integration/api/test_main_authz.py` — the gate.** One table sweeps **all 37
endpoints** for anonymous, authenticated-but-not-admin, and authenticated-without-the-
association. **Add every new endpoint to that table.** It is what catches a route that
forgot its `Depends`.

## Fixtures

Shared ones are in `tests/conftest.py`; the database ones in
`tests/integration/conftest.py`.

### Settings

- `build_settings()` / `build_core_settings()` — explicit kwargs plus `_env_file=None`.
- `required_env` — the minimum for a valid `Settings`.
- `isolated_settings_env` — **autouse**: strips every `Settings` field from the
  environment and clears the `lru_cache`s before and after each test.

That autouse fixture is not optional decoration. Compose injects `DB_HOST=postgres` and
friends into the container, so **without it every assertion about a default value would
be testing compose's environment, not the code**.

### Database

- `fake_db(module, rows=[...], error=...)` — unit tier. Patches `get_db_cursor` **on the
  importing module** (`api.auth`, `api.main`, `mqtt_handler.handler`), because each one
  holds its own reference and patching `meshbee_core.db` does nothing. `.queries`
  records `(sql, params)`; `error=` simulates an outage.
- `db` / `use_db(module)` — integration tier, same seam. `db` wraps each test in a
  transaction that is rolled back afterwards.
- `fake_cursor(rows=[...])` — a bare cursor to *pass in*. Repository and service
  functions take a cursor rather than opening one, so they need no patching at all.

The single seam is the point: patching `get_db_cursor` once covers a whole request,
because the cursor flows on into the service and repository calls unchanged.

### HTTP

- `client` — a `TestClient` that is **never entered as a context manager**. Doing so
  would run the lifespan, and the lifespan calls `init_db_pool()` against the *dev*
  database.
- `as_user(row)` — overrides **only** `get_current_active_user`, so
  `get_current_admin_user` still runs for real and the admin gate is genuinely tested.
- `anyio_backend` — an async test just needs `@pytest.mark.anyio`. anyio ships with
  FastAPI; **do not add pytest-asyncio**. Await dependencies directly rather than
  routing through a client.

### Data builders

`make_utente`, `make_arnia`, `grant_access`, `utente_con_arnia`, `make_lettura`,
`make_attivita`.

## Conventions

- **Sentence-style names**, English, and a docstring that says **why the test matters**
  — not what the code does. `test_password_longer_than_72_bytes_is_rejected` with a
  docstring explaining bcrypt's truncation.
- **One test module per source module**, mirroring the source path.
- **Every test directory needs `__init__.py`** — without it, two modules with the same
  basename collide during collection.
- **Test our own logic, not the libraries.** No tests for pydantic, FastAPI or bcrypt —
  except a library quirk we are exposed to (bcrypt's 72-byte truncation), and then the
  docstring says so.
- **Never pin known-wrong behaviour.** Assert the property you want, not the output you
  currently get, or fixing the bug means fighting the suite. If something is wrong and
  not being fixed today, that is an issue and an `xfail`, not a green assertion.

## Gotchas

- **`utenti.ruolo` is `('user','admin')`** — not `'utente'` — and
  `utenti_arnie.permessi` is `('read','write','admin')`. The fakes accept anything; the
  real database rejects it, so a unit test can pass on data that integration will
  refuse.
- **Missing credentials give 401 + `WWW-Authenticate`; authenticated-but-forbidden
  gives 403.** Asserting the wrong one is how a real authorization regression slips
  through.
- **New endpoint → new row in `test_main_authz.py`.**
- **`postgres-test` is per-boot, not per-run.** Started once, it stays up; a "cannot
  connect" failure across the whole integration tier usually just means the machine was
  rebooted.
- **`tests/integration/core/services/` exists but is empty** — service behaviour is
  currently covered through the API tests and the repository tests. A pure service test
  is welcome there.

## Related

- [`api/`](../api/README.md), [`mqtt_handler/`](../mqtt_handler/README.md),
  [`meshbee_core/`](../meshbee_core/README.md) — what is under test.
- [`database/`](../database/README.md) — the schema the integration tier reloads.
- Main [README](../README.md) — the stack as a whole.
