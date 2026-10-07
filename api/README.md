# `api/` — REST API

*[Versione italiana](README.it.md)*

The **FastAPI entry point**: the HTTP face of the backend, and the only piece the
mobile app talks to. It runs under uvicorn on port **8000**, with `--reload` in
development, and reads and writes the same PostgreSQL database the MQTT handler
writes to — through the same shared logic in [`meshbee_core/`](../meshbee_core/README.md).

It is deliberately **thin**: every handler validates its input, opens one session,
calls *one* service, and translates the outcome into a status code. There is no SQL
here.

## Contents

| Path | What it is |
|---|---|
| `main.py` | The application: lifespan, CORS, error translation and all 37 routes. |
| `auth.py` | JWT minting/decoding and the FastAPI dependencies that guard the routes. |
| `config.py` | `Settings(CoreSettings)` — JWT, API metadata and CORS on top of the DB fields. |
| `openapi.json` | The generated API contract. **Committed** — see [OpenAPI contract](#openapi-contract). |
| `Dockerfile` | Image for the `api` service (and for `seed`). Build context is the repo root. |
| `requirements.txt` | Runtime dependencies. |
| `requirements-dev.txt` | Test dependencies — baked into the same image, so one container runs the suite. |

## Endpoints

37 operations. `Auth` says what a request must carry:

- **none** — public.
- **user** — a valid bearer token for an active account (`get_current_active_user`).
- **admin** — the above *and* `ruolo = 'admin'` (`get_current_admin_user`).
- **user + `read`/`write`** — the above *and* that permission on the specific arnia.
  Admins pass this check unconditionally.

### Autenticazione

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/api/auth/login` | none | Exchange email + password for an access and a refresh token. |
| GET | `/api/auth/me` | user | The authenticated account. |

### Utente

Everything under `/api/user/arnie/{id_arnia}` is gated on that arnia.

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/api/user/arnie` | user | Hives visible to the caller, each with its latest reading. |
| GET | `/api/user/arnie/{id_arnia}` | user + `read` | One hive with its latest reading. |
| PUT | `/api/user/arnie/{id_arnia}` | user + `write` | Rename/move a hive. **Cannot** change `attiva`. |
| GET | `/api/user/arnie/{id_arnia}/letture` | user + `read` | Readings. `data_inizio`, `data_fine`, `limit` (1–10000, default 1000). |
| GET | `/api/user/arnie/{id_arnia}/letture/temperatura` | user + `read` | `{timestamp, temperatura}` only — sized for charts. |
| GET | `/api/user/arnie/{id_arnia}/letture/umidita` | user + `read` | `{timestamp, umidita}` only. |
| GET | `/api/user/arnie/{id_arnia}/letture/peso` | user + `read` | `{timestamp, peso}` only. |
| GET | `/api/user/arnie/{id_arnia}/letture/batteria` | user + `read` | `{timestamp, batteria}` only — node battery voltage. |
| GET | `/api/user/arnie/{id_arnia}/attivita` | user + `read` | Activity log. `data_inizio`, `data_fine`, `tipo_attivita`, `limit` (1–1000, default 100). |
| POST | `/api/user/arnie/{id_arnia}/attivita` | user + `write` | Record an activity. |
| PATCH | `/api/user/arnie/{id_arnia}/attivita/{id_log}` | user + `write` | Edit an activity — **only your own**. |
| DELETE | `/api/user/arnie/{id_arnia}/attivita/{id_log}` | user + `write` | Delete an activity — **only your own**. |
| PUT | `/api/user/password` | user | Change your own password. Requires `current_password`. |

The four series endpoints exist because a chart needs two columns out of a row of
nine; they drop rows where the field is NULL. The list of fields they accept is a
whitelist in `meshbee_core/repository/letture.py`, not string interpolation.

### Admin

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/api/admin/utenti` | admin | All accounts. |
| POST | `/api/admin/utenti` | admin | Create an account. |
| PUT | `/api/admin/utenti/{id_utente}` | admin | Update an account. |
| DELETE | `/api/admin/utenti/{id_utente}` | admin | Deactivate (soft delete). **You cannot deactivate yourself.** |
| PUT | `/api/admin/utenti/{id_utente}/password` | admin | Reset someone's password — no `current_password` needed. |
| POST | `/api/admin/utenti-arnie` | admin | Grant a user access to a hive at a permission level. |
| DELETE | `/api/admin/utenti-arnie` | admin | Revoke it. **`id_utente` and `id_arnia` are query parameters**, not a body. |
| GET | `/api/admin/nodi` | admin | All nodes. |
| POST | `/api/admin/nodi` | admin | Register a node. |
| GET | `/api/admin/nodi/{id_nodo}` | admin | One node. |
| PUT | `/api/admin/nodi/{id_nodo}` | admin | Update a node (body is a full `NodoCreate`). |
| DELETE | `/api/admin/nodi/{id_nodo}` | admin | Deactivate. Hives and readings are kept. |
| GET | `/api/admin/arnie` | admin | All hives, retired ones included. |
| POST | `/api/admin/arnie` | admin | Create a hive. |
| GET | `/api/admin/arnie/{id_arnia}` | admin | One hive with its latest reading. |
| PUT | `/api/admin/arnie/{id_arnia}` | admin | Update a hive — **including `attiva`**, unlike the user route. |
| DELETE | `/api/admin/arnie/{id_arnia}` | admin | Deactivate. Historical readings are kept. |
| GET | `/api/admin/letture` | admin | All readings. `limit` 1–10000, default 1000. |
| POST | `/api/admin/letture` | admin | Insert a reading by hand — backfill and testing. |
| GET | `/api/admin/attivita` | admin | All activities. `limit` 1–1000, default 100. |

`POST /api/admin/letture` and the MQTT path both end at the same INSERT, but they do
**not** behave the same on unknown references: this route answers **404** for an
unknown arnia, while the ingest path provisions the node and hive on the fly. That
difference is intentional and documented in
[`mqtt_handler/README.md`](../mqtt_handler/README.md#auto-provisioning); everything
that must stay identical is pinned by `tests/integration/test_ingest_parity.py`.

### Info

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/` | none | Name, version and the docs URLs. |
| GET | `/health` | none | Pings the database. |

`/health` **always answers 200** — the body carries the verdict
(`"status": "healthy"` / `"unhealthy"`). A monitor must read the body, not the status
code.

## Authentication and authorization

Login returns two JWTs signed HS256 with `JWT_SECRET_KEY`. The claim that identifies
the caller is `sub` (the email); the user row is re-read from the database on **every**
request, so deactivating an account takes effect immediately without waiting for the
token to expire.

The dependencies stack, each building on the previous one:

| Dependency | Rejects with | When |
|---|---|---|
| `get_current_user` | **401** + `WWW-Authenticate: Bearer` | No header, malformed token, bad signature, expired, `type != "access"`, or unknown email. |
| `get_current_active_user` | **400** `Utente non attivo` | The account exists but `attivo` is false. |
| `get_current_admin_user` | **403** `Permessi insufficienti - richiesto ruolo admin` | The account is not an admin. |
| `check_user_arnia_access` | **403** | No association with that arnia at the required level. |

`HTTPBearer(auto_error=False)` is deliberate. Left at its default, FastAPI answers a
*missing* header with a bare 403 and no `WWW-Authenticate`; disabling it lets the
request reach `get_current_user`, which returns the correct **401**. The distinction
the API keeps is: **401 means "who are you?", 403 means "I know who you are, and no"**.

Per-arnia permissions are a ladder — `read` < `write` < `admin` — compared numerically
in `meshbee_core/services/auth.py`. An account with `ruolo = 'admin'` bypasses the
association table entirely. An unrecognised permission name raises rather than
returning False, so a typo fails closed.

Two things to know about tokens:

- **The refresh token is minted but never redeemed.** There is no `/api/auth/refresh`
  route, and nothing reads or writes the `token_sessione` table. When the access token
  expires after `ACCESS_TOKEN_EXPIRE_MINUTES`, the client logs in again. The table is
  kept because it is the right shape for the feature —
  [issue #16](https://github.com/fablab-imperia/meshbee-server/issues/16).
- **A database outage is not a credentials error.** `authenticate_user` turns any
  `SQLAlchemyError` into **503** rather than letting it fall through to 401, so an
  unreachable database never looks like a wrong password.

Login answers the same 401 for an unknown email, a wrong password and a deactivated
account — one answer for every failure mode, so the endpoint cannot be used to
enumerate registered emails.

## Error translation

Services raise vocabulary from `meshbee_core.errors` and know nothing about HTTP. The
`db_operation` context manager in `main.py` is the only place the two vocabularies
meet:

| Raised | Becomes |
|---|---|
| `NotFound` | 404 |
| `Conflict` | 409 |
| `InvalidData` | 400 |
| `SQLAlchemyError` during login | 503 |
| anything else | 500 `Errore interno del server`, with the real error logged |

The 500 body stays vague on purpose: the exception text can name tables and columns.

## Configuration

`Settings` extends `CoreSettings` (the database fields — see
[`meshbee_core/`](../meshbee_core/README.md#configuration)) with:

| Variable | Type | Default |
|---|---|---|
| `JWT_SECRET_KEY` | secret | **required** — `openssl rand -hex 32` |
| `JWT_ALGORITHM` | str | `HS256` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | int | `30` |
| `REFRESH_TOKEN_EXPIRE_DAYS` | int | `7` |
| `API_TITLE` | str | `Beehive IoT API` |
| `API_VERSION` | str | `1.0.0` |
| `API_DESCRIPTION` | str | `API per gestione sistema IoT arnie` |
| `CORS_ORIGINS` | list | `["*"]` |

`CORS_ORIGINS` is a list, so from the environment it must be **JSON**, not a
comma-separated string:

```bash
CORS_ORIGINS=["https://app.example.org","https://admin.example.org"]
```

`["*"]` with `allow_credentials=True` is fine for development and wrong for a public
deployment — narrow it there.

## OpenAPI contract

FastAPI generates the schema from the code, so it is always complete and always
current. It is available three ways:

| Where | What for |
|---|---|
| <http://localhost:8000/docs> | Swagger UI — try requests, with an **Authorize** button for the bearer token. |
| <http://localhost:8000/redoc> | ReDoc — nicer to read than to click. |
| [`api/openapi.json`](openapi.json) | The committed contract, for anything that is not this repo. |

The committed file exists because a URL that only resolves while the stack is running
cannot be linked from another repository. It is what the umbrella repo's
[API contract](https://github.com/fablab-imperia/meshbee/blob/main/docs/contract/api.md)
references and what [`meshbee-app`](https://github.com/fablab-imperia/meshbee-app) can
generate a client from.

**Regenerate it whenever you add, remove or change a route or a schema** — nothing does
it automatically:

```bash
docker-compose exec api python -m scripts.export_openapi     # or: make openapi
```

It must run in the container: `api/config.py` builds `Settings` at import, so on the
host it fails before it reaches the schema. The output is sorted and indented, so
regenerating an unchanged API leaves an empty diff.

## Development

The container runs uvicorn with `--reload`, so **editing a file here is enough** —
`api/` is bind-mounted. (The MQTT handler has no such thing; see its README.)

```bash
docker-compose logs -f api                  # or: make logs-api
docker-compose restart api                  # only needed after a dependency change
curl -s localhost:8000/health | python3 -m json.tool
```

A full round trip from the shell, with the account `scripts/seed.py` creates:

```bash
TOKEN=$(curl -s -X POST localhost:8000/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@beehive.local","password":"<ADMIN_PASSWORD dal .env>"}' \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')

curl -s localhost:8000/api/auth/me -H "Authorization: Bearer $TOKEN"
curl -s localhost:8000/api/user/arnie -H "Authorization: Bearer $TOKEN"
```

Tests for this package live in `tests/unit/api/` and `tests/integration/api/` — see
[`tests/README.md`](../tests/README.md). **A new endpoint must be added to the table in
`tests/integration/api/test_main_authz.py`**: that one table sweeps every route for
anonymous, non-admin and no-association access, and it is what catches a missing gate.

## Gotchas

- **A new route needs three follow-ups**: `make openapi`, a row in the tables above,
  and a row in `test_main_authz.py`. None of them happen on their own.
- **The image is not API-only.** It also carries `mqtt_handler/`, `scripts/` and
  `tests/` plus `paho-mqtt`, so the whole suite — both entry points included — runs in
  this one container. That is why the build context is the repo root and not `api/`.
- **The `seed` service runs from this same image**, with `python -m scripts.seed`.
- **`/health` returning 200 says nothing.** Read `status` in the body.
- **`DELETE /api/admin/utenti-arnie` takes query parameters.** A JSON body is ignored,
  and the request then fails validation for the missing parameters.

## Related

- [`meshbee_core/`](../meshbee_core/README.md) — the services and schemas every handler calls.
- [`mqtt_handler/`](../mqtt_handler/README.md) — the other writer of the same database.
- [`tests/`](../tests/README.md) — how to run the suite and where a new test belongs.
- [`database/`](../database/README.md) — the tables behind these responses.
- Main [README](../README.md) — the stack as a whole.
