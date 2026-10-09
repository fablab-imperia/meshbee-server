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
| `main.py` | The application: lifespan, CORS, error translation and all 54 routes. |
| `auth.py` | JWT minting/decoding and the FastAPI dependencies that guard the routes. |
| `paging.py` | The optional `limit`/`offset` parameters of the list routes, and their `X-Total-Count` header — see [Paging](#paging). |
| `config.py` | `Settings(CoreSettings)` — JWT, API metadata and CORS on top of the DB fields. |
| `admin/` | The admin page served at `/admin/` — see [Admin page](#admin-page). |
| `openapi.json` | The generated API contract. **Committed** — see [OpenAPI contract](#openapi-contract). |
| `Dockerfile` | Image for the `api` service (and for `seed`). Build context is the repo root. |
| `requirements.txt` | Runtime dependencies. |
| `requirements-dev.txt` | Test dependencies — baked into the same image, so one container runs the suite. |

## Endpoints

54 operations. `Auth` says what a request must carry:

- **none** — public.
- **user** — a valid bearer token for an active account (`get_current_active_user`).
- **admin** — the above *and* `ruolo = 'admin'` (`get_current_admin_user`).
- **user + viewer / collaborator / manager / owner** — the above *and* at least that
  access to the hive's apiary (or the apiary itself): owning it, or a role its owner
  shared. See [Authentication and authorization](#authentication-and-authorization).
  Admins pass this check unconditionally.

**Paged** marks a list route that takes `limit` and `offset` — see [Paging](#paging).

### Autenticazione

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/api/auth/login` | none | Exchange email + password for an access and a refresh token. |
| GET | `/api/auth/me` | user | The authenticated account. |

### Utente

Everything under `/api/user/arnie/{id_arnia}` and `/api/user/apiari/{id_apiario}` is gated on
the caller's access to that hive's apiary, or that apiary.

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/api/user/arnie` | user | Hives in the apiaries the caller owns or has been shared, each with its latest reading, its apiary and `accesso` (the caller's access). Optional `id_apiario` narrows it to one apiary. **Paged**. |
| GET | `/api/user/arnie/{id_arnia}` | user + viewer | One hive with its latest reading. |
| PUT | `/api/user/arnie/{id_arnia}` | user + manager | Rename/reposition a hive. `attiva` (retiring it) is applied only for the owner. |
| PUT | `/api/user/arnie/{id_arnia}/apiario` | user + owner | Move the hive into another apiary of its owner. Who can see it follows the apiary. |
| GET | `/api/user/arnie/{id_arnia}/letture` | user + viewer | Readings. `data_inizio`, `data_fine`, `limit` (1–10000, default 1000). **Paged**. |
| GET | `/api/user/arnie/{id_arnia}/letture/temperatura` | user + viewer | `{timestamp, temperatura}` only — sized for charts. |
| GET | `/api/user/arnie/{id_arnia}/letture/umidita` | user + viewer | `{timestamp, umidita}` only. |
| GET | `/api/user/arnie/{id_arnia}/letture/peso` | user + viewer | `{timestamp, peso}` only. |
| GET | `/api/user/arnie/{id_arnia}/letture/batteria` | user + viewer | `{timestamp, batteria}` only — node battery voltage. |
| GET | `/api/user/arnie/{id_arnia}/attivita` | user + viewer | Activity log. `data_inizio`, `data_fine`, `tipo_attivita`, `limit` (1–1000, default 100). **Paged**. |
| POST | `/api/user/arnie/{id_arnia}/attivita` | user + collaborator | Record an activity. |
| PATCH | `/api/user/arnie/{id_arnia}/attivita/{id_log}` | user + collaborator | Edit an activity — **only your own**. |
| DELETE | `/api/user/arnie/{id_arnia}/attivita/{id_log}` | user + collaborator | Delete an activity — **only your own**. |
| PUT | `/api/user/password` | user | Change your own password. Requires `current_password`. |
| GET | `/api/user/apiari` | user | The apiaries the caller owns (the default one first), then those shared with them, each with `accesso`. **Paged**. |
| POST | `/api/user/apiari` | user | Create an apiary owned by the caller. |
| GET | `/api/user/apiari/{id_apiario}` | user + viewer | One apiary. |
| PUT | `/api/user/apiari/{id_apiario}` | user + manager | Edit it — the default one included. |
| DELETE | `/api/user/apiari/{id_apiario}` | user + owner | Delete it, with its shares. **409** for the default one, and while active hives are still in it. |
| GET | `/api/user/apiari/{id_apiario}/condivisioni` | user + owner | Who it is shared with, and as what. **Paged**. |
| POST | `/api/user/apiari/{id_apiario}/condivisioni` | user + owner | Share it with a user, by `email`, as `viewer` (default), `collaborator` or `manager`. Sharing again changes the role. |
| PUT | `/api/user/apiari/{id_apiario}/condivisioni/{id_utente}` | user + owner | Change that user's role. |
| DELETE | `/api/user/apiari/{id_apiario}/condivisioni/{id_utente}` | user + owner | Stop sharing it with that user. |

The four series endpoints exist because a chart needs two columns out of a row of
nine; they drop rows where the field is NULL. The list of fields they accept is a
whitelist in `meshbee_core/repository/letture.py`, not string interpolation.

### Admin

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/api/admin/utenti` | admin | All accounts. **Paged**. |
| POST | `/api/admin/utenti` | admin | Create an account. |
| PUT | `/api/admin/utenti/{id_utente}` | admin | Update an account. |
| DELETE | `/api/admin/utenti/{id_utente}` | admin | Deactivate (soft delete). **You cannot deactivate yourself.** |
| PUT | `/api/admin/utenti/{id_utente}/password` | admin | Reset someone's password — no `current_password` needed. |
| GET | `/api/admin/nodi` | admin | All nodes. **Paged**. |
| POST | `/api/admin/nodi` | admin | Register a node. |
| GET | `/api/admin/nodi/{id_nodo}` | admin | One node. |
| PUT | `/api/admin/nodi/{id_nodo}` | admin | Update a node (body is a full `NodoCreate`). |
| DELETE | `/api/admin/nodi/{id_nodo}` | admin | Deactivate. Hives and readings are kept. |
| PUT | `/api/admin/nodi/{id_nodo}/proprietario` | admin | Assign the node to a user (`id_utente`), transfer it, or unassign it (`null`). Its hives move to the new owner's default apiary. |
| GET | `/api/admin/arnie` | admin | All hives, retired ones included. Optional `id_apiario`. **Paged**. |
| POST | `/api/admin/arnie` | admin | Create a hive. It goes in the node owner's default apiary, or in `id_apiario` if that is the node owner's; a hive of an unassigned node is unassigned. |
| GET | `/api/admin/arnie/{id_arnia}` | admin | One hive with its latest reading. |
| PUT | `/api/admin/arnie/{id_arnia}` | admin | Update a hive — **including `attiva`**, unlike the user route. |
| DELETE | `/api/admin/arnie/{id_arnia}` | admin | Deactivate. Historical readings are kept. |
| GET | `/api/admin/apiari` | admin | Every user's apiaries. Optional `id_utente`. **Paged**. |
| POST | `/api/admin/apiari` | admin | Create an apiary for the user named in `id_utente_proprietario`. |
| GET | `/api/admin/apiari/{id_apiario}` | admin | Any user's apiary. |
| PUT | `/api/admin/apiari/{id_apiario}` | admin | Edit any user's apiary. |
| DELETE | `/api/admin/apiari/{id_apiario}` | admin | Delete any user's apiary, under the owner's rules (**409** as above). |
| GET | `/api/admin/letture` | admin | All readings. `limit` 1–10000, default 1000. **Paged**. |
| POST | `/api/admin/letture` | admin | Insert a reading by hand — backfill and testing. |
| PATCH | `/api/admin/letture/{id_lettura}` | admin | Correct a reading: only the fields sent change, a measurement sent as `null` is cleared, `timestamp` cannot be. Hive and node are not editable. **404** if unknown. |
| DELETE | `/api/admin/letture/{id_lettura}` | admin | Delete one reading (a real delete). **404** if unknown. |
| POST | `/api/admin/letture/elimina` | admin | Delete readings in bulk: `{"id_letture": [...]}`, 1–10000 ids. Unknown ids are skipped; the message says how many went. Pick them with the hive and date filters of `GET /api/user/arnie/{id_arnia}/letture`. |
| GET | `/api/admin/attivita` | admin | All activities. `limit` 1–1000, default 100. **Paged**. |

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
(`"status": "healthy"` / `"unhealthy"`), never the reason: that goes to the API log. A monitor must read the body, not the status
code.

## Paging

The 11 routes marked **Paged** above accept `limit` and `offset`
([api/paging.py](paging.py)). Both are optional, and a request with neither gets exactly
what the route returned before paging existed: the whole list, or the newest `limit`
readings and activities.

| Parameter | Meaning |
|---|---|
| `offset` | Rows to skip, ≥ 0, default 0. |
| `limit` | Rows to return at most. Readings and activities keep their default and maximum (above); the other lists default to all, at most 1000 per page. |

A request that carries either parameter also gets **`X-Total-Count`**: the size of the
whole list, filters applied. It costs a COUNT query, which is why a request without
paging parameters doesn't pay for it. CORS exposes the header, so a browser on another
origin can read it. The body stays the plain JSON list in every case. `openapi.json`
declares the header on each paged route's 200 response.

```http
GET /api/admin/utenti?limit=25&offset=50

200 OK
X-Total-Count: 132

[ ... ]
```

Every paged ordering ends on a unique column (the id, or the email for shares), so
consecutive pages neither repeat nor skip rows that share a timestamp or a name. An
offset past the end is an empty page, still with its total. The chart series
(`/letture/{grandezza}`) are not paged: their date window and `limit` already bound them.

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
| `check_user_arnia_access` | **403** | The caller's access to the hive's apiary does not allow the action. |
| `check_user_apiario_access` | **403** | The caller's access to the apiary does not allow the action. |

`HTTPBearer(auto_error=False)` is deliberate. Left at its default, FastAPI answers a
*missing* header with a bare 403 and no `WWW-Authenticate`; disabling it lets the
request reach `get_current_user`, which returns the correct **401**. The distinction
the API keeps is: **401 means "who are you?", 403 means "I know who you are, and no"**.

**Access follows ownership (#36).** A node belongs to a user, assigned by an admin;
its hives stand in that user's apiaries, and a hive's owner is its apiary's owner.
Every account starts with a `Default` apiary, where the hives of its newly assigned
nodes land. A node nobody has been assigned yet, and its hives, are reachable by
admins only.

The owner of an apiary may do everything on it and its hives, and is the **only one
who can share it**. A share grants one of three roles on the whole apiary, hives
added later included:

| Action | viewer | collaborator | manager | owner |
|---|---|---|---|---|
| See the apiary, its hives, readings and activity log | ✓ | ✓ | ✓ | ✓ |
| Log activities (and edit or delete one's own) | | ✓ | ✓ | ✓ |
| Edit hive and apiary details | | | ✓ | ✓ |
| Retire a hive, move it, delete the apiary, share it | | | | ✓ |

The table lives once, as `ROLE_ACTIONS` in `meshbee_core/services/auth.py`; every
route names the action it needs, and an account with `ruolo = 'admin'` passes every
check. An unknown action raises rather than returning False, so a typo fails closed.
`?id_apiario=` narrows the caller's hive list, it never widens it. Moving a hive into
an apiary that is not its owner's gets the same **400** whether it exists or not, so
the answer reveals nothing.

A share response identifies the user only by the email the owner typed — no name.
Known gap: sharing with an unregistered email answers **404**, so any user can still
test which emails have an account ([#40](https://github.com/fablab-imperia/meshbee-server/issues/40)).

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

## Admin page

`/admin/` serves a small page for administrators
([#41](https://github.com/fablab-imperia/meshbee-server/issues/41)): an overview (counts
and the active nodes silent for 24 hours), list, create, edit and deactivate users,
nodes, hives and apiaries, assign a node's owner, move a hive to another apiary of its
owner, reset a password, browse readings (as a table or as charts) and activities; manage who an apiary is shared with, insert a
reading by hand, correct one, and delete readings one at a time or as a selection
([#42](https://github.com/fablab-imperia/meshbee-server/issues/42),
[#21](https://github.com/fablab-imperia/meshbee-server/issues/21)). Swagger UI at
`/docs` remains the full fallback.

It is **a client of this API, not a second one**. `main.py` mounts `admin/` with
`StaticFiles`; the page logs in through `/api/auth/login`, refuses a non-admin account
after `/api/auth/me`, and from then on calls the same routes as any other client with
the bearer token. So the page itself adds no route, no session and no logic: soft
deletes, password hashing, node transfers and validation all happen in the services, and
the page shows the API's own `detail` on a 4xx. Value lists (`ruolo`, the apiary roles,
`tipo_attivita`) are read from `/openapi.json`, so they stay declared once in
`meshbee_core/limits.py`.

| File | What it is |
|---|---|
| `index.html` | The markup, with [Alpine.js](https://alpinejs.dev) bindings. |
| `resources.js` | `RESOURCES` — per tab: route, columns, form fields, row actions. A new admin operation is usually one entry there. |
| `admin.js` | The core of the one Alpine component: login, requests, the table and the generic form that `RESOURCES` drives. `admin()` merges the feature files below into it. |
| `overview.js`, `charts.js`, `shares.js`, `pagination.js` | One feature each, with its own state: the Panoramica tab, the readings charts, an apiary's sharing panel, the pager under each table. A new feature with state of its own gets a file like these, not more branches in `admin.js`. |
| `admin.css` | The little [Pico CSS](https://picocss.com) does not cover. |
| `vendor/` | Alpine.js and Pico CSS, **vendored** with the version in the file name: no build step, no CDN, works on a LAN with no internet. To upgrade, replace the file and its references in `index.html`. |

Things to know:

- **No build step and no npm.** Edit the files; `--reload` is not even needed, they are
  read on each request.
- **Data reaches the DOM only through `x-text`**, which escapes it. Names are typed by
  users; `x-html` or `innerHTML` would let one run script with the admin's token.
  `tests/unit/api/test_admin_page.py` fails on either.
- **The token lives in `sessionStorage`** (gone when the tab closes). There is no refresh
  ([#16](https://github.com/fablab-imperia/meshbee-server/issues/16)): when it expires
  the next request gets a 401 and the page asks for the login again.
- Picking a hive on the readings or activities tab switches to the hive-scoped
  `/api/user/arnie/{id_arnia}/…` route — the one with date filters, which admins pass.
  To delete a hive's readings over a period, filter by hive and dates, tick the header
  checkbox, press **Seleziona tutte** and delete the selection. The header covers only the
  page shown; Seleziona tutte fetches every reading the filters match (up to 10000, the
  most a bulk delete takes) in one request.
- **The main table pages on the server**, 25 rows to start: each page is one request
  with `limit` and `offset`, and [`X-Total-Count`](#paging) sizes the pager. A page change
  reloads only the rows. Changing a filter goes back to page 1; Aggiorna and a save keep
  the page. The lookups behind the selects and the readable cells (users, apiaries,
  hives, nodes) still load whole, so the silent nodes and an apiary's shares page in the
  browser.
- An apiary's **Condivisioni** use the owner's `/api/user/apiari/{id_apiario}/condivisioni`
  routes, which admins pass too: there are no admin twins of them. So does a hive's
  **Sposta**, through `PUT /api/user/arnie/{id_arnia}/apiario`.
- The **charts** load their own readings, since the table holds only a page: the
  picked hive's in the picked period (the last year without dates), up to the newest
  10000. Inline SVG, no chart library. A missing value breaks the line, so a measurement
  the ingest nulled shows as a gap.
- The **Panoramica** tab is computed from the lists every tab already loads; it has no
  request of its own.

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
anonymous and non-admin access, and checks every hive- and apiary-scoped route at each
access level against its minimum. It is what catches a missing or wrong gate.

## Gotchas

- **A new route needs three follow-ups**: `make openapi`, a row in the tables above,
  and a row in `test_main_authz.py`. None of them happen on their own.
- **The image is not API-only.** It also carries `mqtt_handler/`, `scripts/` and
  `tests/` plus `paho-mqtt`, so the whole suite — both entry points included — runs in
  this one container. That is why the build context is the repo root and not `api/`.
- **The `seed` service runs from this same image**, with `python -m scripts.seed`.
- **`/health` returning 200 says nothing.** Read `status` in the body.

## Related

- [`meshbee_core/`](../meshbee_core/README.md) — the services and schemas every handler calls.
- [`mqtt_handler/`](../mqtt_handler/README.md) — the other writer of the same database.
- [`tests/`](../tests/README.md) — how to run the suite and where a new test belongs.
- [`database/`](../database/README.md) — the tables behind these responses.
- Main [README](../README.md) — the stack as a whole.
