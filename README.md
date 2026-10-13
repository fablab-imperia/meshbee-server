# 🐝 Meshbee Backend

[![Latest release](https://img.shields.io/github/v/release/fablab-imperia/meshbee-server?sort=semver)](https://github.com/fablab-imperia/meshbee-server/releases/latest)
[![Code quality](https://sonarcloud.io/api/project_badges/measure?project=fablab-imperia_meshbee-server&metric=alert_status)](https://sonarcloud.io/summary/new_code?id=fablab-imperia_meshbee-server)
[![Test coverage](https://sonarcloud.io/api/project_badges/measure?project=fablab-imperia_meshbee-server&metric=coverage)](https://sonarcloud.io/component_measures?id=fablab-imperia_meshbee-server&metric=coverage)
[![Maintainability](https://sonarcloud.io/api/project_badges/measure?project=fablab-imperia_meshbee-server&metric=sqale_rating)](https://sonarcloud.io/component_measures?id=fablab-imperia_meshbee-server&metric=sqale_rating)
[![Reliability](https://sonarcloud.io/api/project_badges/measure?project=fablab-imperia_meshbee-server&metric=reliability_rating)](https://sonarcloud.io/component_measures?id=fablab-imperia_meshbee-server&metric=reliability_rating)
[![Security](https://sonarcloud.io/api/project_badges/measure?project=fablab-imperia_meshbee-server&metric=security_rating)](https://sonarcloud.io/component_measures?id=fablab-imperia_meshbee-server&metric=security_rating)

*[Versione italiana](README.it.md)*

This is the **backend** code for the [Meshbee project](https://github.com/fablab-imperia/meshbee). Implements FastAPI REST API, MQTT handler, Mosquitto broker and PostgreSQL, via Docker Compose.

Other parts of the Meshbee project include:

| Repository | What it is |
|---|---|
| **[meshbee](https://github.com/fablab-imperia/meshbee)**  | Umbrella repo: documentation, architecture and the versioned MQTT/API contract. |
| **[meshbee-firmware](https://github.com/fablab-imperia/meshbee-firmware)** | ESP32 firmware for the sensor and gateway nodes (Meshtastic + MQTT). |
| **[meshbee-server](https://github.com/fablab-imperia/meshbee-server)** (this one) | Backend: FastAPI REST API, MQTT handler, Mosquitto broker and PostgreSQL, via Docker Compose. |
| **[meshbee-app](https://github.com/fablab-imperia/meshbee-app)** | Mobile app in React Native / Expo — dashboards, charts and push alerts. |
| **[meshbee-hardware](https://github.com/fablab-imperia/meshbee-hardware)** | Hardware design: PCB schematics and 3D-printed enclosures. |

📖 **Documentation:** <https://fablab-imperia.github.io/meshbee/>

🛠️ **Built by:** [Fablab Imperia APS](https://www.fablabimperia.org)

## Contents

- [Overview](#overview)
- [How they fit together](#how-they-fit-together)
- [Requirements](#requirements)
- [Setup](#setup)
- [Configuration](#configuration)
- [Development](#development)
- [Production](#production)
- [Troubleshooting](#troubleshooting)
- [License](#license)
- [Versioning and contributing](#versioning-and-contributing)

## Overview

The server side of Meshbee: it receives hive readings over MQTT, stores them, and serves
them to the mobile app over a REST API.

What it does:

- **Ingests** readings over MQTT, provisioning unknown nodes and hives on the fly.
- **Stores** them in PostgreSQL, with the measurement ranges enforced twice — in the
  application and in the schema.
- **Serves** a REST API with JWT authentication, hive ownership with roles shared per
  apiary, and history
  endpoints sized for charts.
- **Records** what the beekeeper did: inspections, treatments, harvests.
- Runs entirely in Docker Compose.

What produces the readings and what consumes them are documented in their own
repositories — see [How they fit together](#how-they-fit-together).

## How they fit together

Everything named with a trailing slash is a directory in **this** repository; the two
ends of the chain live in sibling repositories.

```
ESP32 nodes ──MQTT──▶ mosquitto/ ──▶ mqtt_handler/ ──┐
                                                     │
                                                     ├──▶ meshbee_core/ ──▶ database/
                                                     │
mobile app ──HTTPS──▶ caddy/ ─────▶ api/ ────────────┘
                                     ▲
browser ──▶ admin/ (served by api/) ─┘
```

| In the diagram | What it is | Where it lives |
|---|---|---|
| ESP32 nodes | Sensor and gateway nodes. They publish readings to `beehive/<id_nodo>/data`. | [meshbee-firmware](https://github.com/fablab-imperia/meshbee-firmware) |
| `mosquitto/` | The MQTT broker's configuration and state. Off-the-shelf image, no code of ours. | [mosquitto/](mosquitto/README.md) |
| `mqtt_handler/` | Subscribes to the broker, decodes the payload, stores the reading. | [mqtt_handler/](mqtt_handler/README.md) |
| `caddy/` | Reverse proxy terminating HTTPS in front of the API: on `:8443` with a local certificate in development (optional), with Let's Encrypt in production. | [Local HTTPS](#local-https), [Production](#production) |
| `api/` | The FastAPI REST API. The only piece the app talks to. | [api/](api/README.md) |
| `admin/` | The static admin page the API serves at `/admin/`, a client of its routes. | [admin/](admin/README.md) |
| `meshbee_core/` | The shared library both entry points import: schemas, services, and all the SQL. | [meshbee_core/](meshbee_core/README.md) |
| `database/` | Docs for the PostgreSQL schema, which `meshbee_core/models.py` defines and Alembic applies. | [database/](database/README.md) |
| mobile app | Dashboards, charts and alerts. Consumes the REST API. | [meshbee-app](https://github.com/fablab-imperia/meshbee-app) |

Two directories are not on that path: [`tests/`](tests/README.md), one pytest suite
covering all of it, and `scripts/`, one-shot jobs — `migrate.py` brings the schema to
the latest revision, `seed.py` creates the initial accounts, `export_openapi.py` and `export_mqtt_schema.py` regenerate the two contract
artifacts.

> The architecture of the **whole** Meshbee project, this repository included, is
> documented at <https://fablab-imperia.github.io/meshbee/architecture/>.

Two facts explain most of the layout.

**Two processes, one library.** `api` and `mqtt-handler` are separate containers with
separate lifecycles — restarting the broker does not touch the REST API, and the API is
not an MQTT client. But they write to the same database, so they must agree on what a
valid reading is and on how to store one. That agreement is `meshbee_core`: a library,
imported by both, never deployed on its own. `tests/integration/test_ingest_parity.py`
proves the two paths produce identical rows.

**Three layers, one direction.** SQL lives in `meshbee_core/repository/`; decisions live
in `meshbee_core/services/`, which raise their own errors and know nothing about HTTP;
the entry points validate their input, call *one* service, and translate the outcome
into a status code or a log line. New business logic goes in a service, new SQL goes in
a repository, and a new route is a thin call into an existing service. **SQL appearing
in `api/`, `mqtt_handler/` or `scripts/` means it went to the wrong place.**

Ports:

| Port | Service | Notes |
|---|---|---|
| 8000 | `api` | HTTP. `/admin/`, `/docs`, `/redoc`, `/openapi.json`. |
| 8443 | `caddy` | HTTPS. Only if you ran `make certs`. Override with `HTTPS_PORT`. |
| 1883 | `mosquitto` | MQTT. Authentication required. |
| 9001 | `mosquitto` | MQTT over WebSockets. Configured but unused. |
| 5432 | `postgres` | Published for `psql` and GUI clients. |

These are the development ports. A production install publishes fewer; see
[Production](#production).

## Requirements

Docker and Docker Compose. Optionally git, and
[mkcert](https://github.com/FiloSottile/mkcert) if you want local HTTPS.

## Setup

```bash
git clone https://github.com/fablab-imperia/meshbee-server.git
cd meshbee-server
cp .env.example .env
```

**1. Fill in `.env`.** Every value is a credential and every one must be changed:

```bash
POSTGRES_PASSWORD=...      # database
JWT_SECRET_KEY=...         # token signing — openssl rand -hex 32
MQTT_PASSWORD=...          # broker
ADMIN_PASSWORD=...         # admin@beehive.local, created on first start
USER_PASSWORD=...          # utente@test.local, created on first start
```

`ADMIN_PASSWORD` and `USER_PASSWORD` are **required and at least 8 characters**. If one
is missing, the `seed` service stops with an explicit error rather than creating a
working administrator account with an empty password.

**2. Generate the broker password file.** The broker runs with `allow_anonymous false`,
so **without this step Mosquitto will not start**:

```bash
make mqtt-passwd
```

Re-run it whenever you change `MQTT_PASSWORD` — the file holds a hash, so it does not
follow the variable.

**3. (Optional) Enable HTTPS.** Requires mkcert; it runs on the host and touches your
system trust store:

```bash
make certs
```

Skip it and Caddy prints a note and exits 0. The rest of the stack, and HTTP on `:8000`,
carry on regardless.

**4. Start.**

```bash
docker-compose up -d       # or: make start
docker-compose ps
```

> **Shortcut:** `make setup` does the `.env` copy, `make mqtt-passwd` and the start, in
> that order. It does not generate certificates.

**5. Check.**

- HTTP: <http://localhost:8000/docs>
- HTTPS: <https://localhost:8443/docs> (only after `make certs`)
- Admin page: <http://localhost:8000/admin/> — log in with the admin account
  ([details](admin/README.md))

```bash
curl -s localhost:8000/health | python3 -m json.tool
```

> `meshbee-migrate` applies the schema migrations and `meshbee-seed` creates the initial
> accounts; both then exit. Seeing them as **`Exited (0)` is normal** — they are
> one-shot jobs, not crashed services.

On a fresh database you get: the two accounts above, one sample node with two hives, and
a handful of readings. **Change those passwords before exposing anything.**

## Configuration

Everything is in `.env`. Compose passes the values to the services as environment
variables, which take precedence over the file — the `.env` file itself is only read
directly when you run a process outside Docker.

| Variable | Used by | Notes |
|---|---|---|
| `POSTGRES_PASSWORD` | postgres, migrate, api, mqtt-handler, seed | Also arrives as `DB_PASSWORD`. **Only applied on a fresh volume.** |
| `JWT_SECRET_KEY` | api | Token signing. Changing it invalidates every issued token. |
| `MQTT_USER` | mosquitto, mqtt-handler | Default `beehive`. |
| `MQTT_PASSWORD` | mosquitto, mqtt-handler | Must match `mosquitto/config/passwd`. |
| `ADMIN_PASSWORD` | seed | ≥ 8 characters. |
| `USER_PASSWORD` | seed | ≥ 8 characters. |
| `HTTPS_PORT` | caddy | Host port for HTTPS. Default `8443`. Development only. |
| `COMPOSE_FILE` | compose | Production only: `docker-compose.yml:docker-compose.prod.yml`. |
| `MESHBEE_DOMAIN` | caddy, api | Production only: the public host name. |
| `ACME_EMAIL` | caddy | Production only: Let's Encrypt contact address. |
| `SMTP_*`, `MAIL_FROM`, `PUBLIC_BASE_URL` | api | Optional outgoing email; see [below](#outgoing-email). |

Settings are **split by service**: `CoreSettings` in `meshbee_core/config.py` holds the
database fields, and each entry point subclasses it with its own extras — JWT and CORS
for the API, `MQTT_*` for the handler, the two initial passwords for the seed. Each
component's README lists its own fields.

**Put a new field in the narrowest class that needs it.** A required field on
`CoreSettings` must exist in the environment of *every* service in
`docker-compose.yml`, or that service crashes on import.

### Outgoing email

The API can send email through **any SMTP server**: a provider (Resend, Brevo, Mailgun,
SES, …), the organisation's own mail server, or a relay on the same host. It is **off
until `SMTP_HOST` is set**, and nothing changes for an install that leaves it unset.
Only the `api` service reads these variables; the MQTT handler sends nothing.

| Variable | Default | Notes |
|---|---|---|
| `SMTP_HOST` | unset | Unset = email disabled. |
| `SMTP_SECURITY` | `starttls` | `ssl` (implicit TLS, usually 465), `starttls` (usually 587) or `none` (a local relay or Mailpit only). |
| `SMTP_PORT` | by security | Unset = 465 / 587 / 25 for `ssl` / `starttls` / `none`. |
| `SMTP_USER` | unset | Unset = no login, for relays that need none. |
| `SMTP_PASSWORD` | unset | Required with `SMTP_USER`. Never logged. |
| `SMTP_TIMEOUT` | `10` | Seconds, per connection. |
| `MAIL_FROM` | unset | Required with `SMTP_HOST`, e.g. `Meshbee <noreply@example.org>`. Use an address on a domain the provider has verified. |
| `PUBLIC_BASE_URL` | unset | Where the app is reached, e.g. `https://meshbee.example.org`. Used for links in emails. |

With email on and `PUBLIC_BASE_URL` set, users can **reset a forgotten password** on
their own at `/reset-password`, and sharing an apiary emails a notice, or an
invitation to sign up at `/invite` for someone with no account yet. Settings and limits
are in [`api/`](api/README.md#password-reset) and [`api/`](api/README.md#invitations).

A half-done configuration (a host without `MAIL_FROM`, a user without a password) stops
the API at startup instead of failing on the first email. Routes send mail after the
response, so a slow server never holds a request. A failed send is logged with the
server's reply, but never the password or the message body.

**Check a configuration** by sending one message:

```bash
docker-compose up -d api        # picks up the .env changes
docker-compose exec api python -m scripts.send_test_mail you@example.org
```

**Locally, without a provider:** [Mailpit](https://mailpit.axllent.org/) catches
everything and shows it in a web inbox at <http://localhost:8025/>.

```bash
docker-compose --profile mail up -d mailpit
# in .env:
SMTP_HOST=mailpit
SMTP_PORT=1025
SMTP_SECURITY=none
MAIL_FROM=Meshbee <noreply@meshbee.local>
```

**Example: Resend.** This is one option among several, picked here because it is an easy
start for a small install. The free tier allows 3,000 emails a month (at most 100 a day)
and includes SMTP. Create an account, add a sending domain (or a subdomain such as
`mail.example.org`) and publish the SPF/DKIM records it shows, then create an API key
with *sending access* only:

```bash
SMTP_HOST=smtp.resend.com
SMTP_SECURITY=ssl              # port 465; or starttls on 587, and 2465/2587 if those are blocked
SMTP_USER=resend
SMTP_PASSWORD=re_...           # the API key
MAIL_FROM=Meshbee <noreply@mail.example.org>
```

## Development

The `api` container runs uvicorn with `--reload` and `api/`, `admin/`, `meshbee_core/`
and `tests/` are bind-mounted, so editing a file is enough. **The MQTT handler has no hot
reload** and must be restarted:

```bash
docker-compose logs -f                       # everything (make logs)
docker-compose logs -f api                   # make logs-api
docker-compose restart mqtt-handler          # make restart-mqtt — after every edit there
docker-compose exec postgres psql -U beehive_user -d beehive_iot     # make db-shell
```

**Tests** run in the container, always — `config.py` builds its `Settings` at import, so
on the host collection fails:

```bash
docker-compose --profile test up -d postgres-test    # once per boot
docker-compose exec api pytest                       # make test
docker-compose exec api pytest -m "not integration"  # no database needed
```

See [`tests/README.md`](tests/README.md) for the two tiers, the fixtures and where a new
test belongs.

**Lint and format** with [Ruff](https://docs.astral.sh/ruff/), also in the container
(config in `ruff.toml`, version pinned in `api/requirements-dev.txt`):

```bash
docker-compose exec api ruff check .          # lint (make lint runs both checks)
docker-compose exec api ruff format --check . # formatting
docker-compose exec api ruff check --fix .    # apply the safe fixes (make format)
docker-compose exec api ruff format .         # reformat
```

New Alembic revisions are run through Ruff as they are generated (`alembic.ini`).

**After changing a route, a schema or the payload shape**, regenerate the committed
contract artifacts:

```bash
docker-compose exec api python -m scripts.export_openapi        # make openapi
docker-compose exec api python -m scripts.export_mqtt_schema    # make mqtt-schema
make contract                                                   # both at once
```

`api/openapi.json` and `mqtt_handler/mqtt-payload.schema.json` are what the umbrella
repo's [contract](https://github.com/fablab-imperia/meshbee/blob/main/docs/contract/index.md)
and the mobile app reference. Nothing regenerates them automatically; `pytest` fails
while the MQTT schema is stale, but nothing checks `openapi.json`. A new endpoint also
needs a row in the authorization table in `tests/integration/api/test_main_authz.py`.

**Publish a test reading** without any client installed:

```bash
set -a; . ./.env; set +a
docker-compose exec -T mosquitto mosquitto_pub \
  -h localhost -u "$MQTT_USER" -P "$MQTT_PASSWORD" \
  -t beehive/NODE001/data \
  -m '{"id_sensore":"SENSOR01","temperatura":34.5,"umidita":65,"peso":42.35}'
```

**Backups:**

```bash
make db-backup                                          # → backups/backup_<timestamp>.sql
make db-restore FILE=backups/backup_20260805_120000.sql
```

**Stopping:** `docker-compose stop` pauses; `docker-compose down` (`make clean`) removes
the containers and **keeps the data**; `make clean-all` runs `down -v` and **destroys
the database**.

### Local HTTPS

`caddy/` holds a Caddy reverse proxy that terminates TLS on `:8443` and forwards to
`api:8000`, using a certificate issued by [mkcert](https://github.com/FiloSottile/mkcert)
and trusted by your machine. It exists so the mobile app can be developed against
`https://` without certificate warnings.

`make certs` runs on the **host** (mkcert installs a local CA into your trust store) and
writes `caddy/certs/`, which is gitignored. Without those files Caddy prints how to
create them and exits 0, so the stack still comes up.

## Production

`docker-compose.yml` is the development setup. `docker-compose.prod.yml` is the layer a
server adds on top of it. Select both once in the server's `.env`, along with the public
host name, and plain `docker compose` commands use them:

```bash
COMPOSE_FILE=docker-compose.yml:docker-compose.prod.yml
MESHBEE_DOMAIN=meshbee.example.org     # must already resolve to the server
ACME_EMAIL=admin@example.org           # Let's Encrypt contact
```

What the layer changes:

- **HTTPS with a real certificate.** Caddy (`caddy/Caddyfile.prod`) obtains and renews
  a Let's Encrypt certificate for `MESHBEE_DOMAIN`. `http://` on that name redirects
  to `https://`. The certificates live in the `caddy_data` volume.
- **Only Caddy and MQTT are published:** 80, 443, 8000 and 1883. Postgres, the
  WebSocket listener and the API itself are reachable only inside the compose network.
  Ports 80 and 443 must be open in the server's firewall; port 80 is needed for the
  certificate challenge.
- **Plain HTTP stays available, by IP on :80 and on :8000.** Clients configured before
  the domain existed keep working while they move to `https://`. Close these once
  nobody uses them.
- **The images' own code runs.** There is no `--reload` and no bind mounts, so a
  change reaches the server only through a rebuild (`docker compose build`).
- **CORS is limited to `https://MESHBEE_DOMAIN`,** and container logs rotate (3 × 10 MB
  per service).

**Email is optional in production too.** The layer changes nothing about it: the
`SMTP_*` settings reach the API from `.env` as in development (see
[Outgoing email](#outgoing-email)). To turn it on, set them and
`PUBLIC_BASE_URL=https://MESHBEE_DOMAIN`. Reset and invitation links point there, so it
must be the public HTTPS name, never an IP or a plain-HTTP address. Run
`docker compose run --rm api python -m scripts.send_test_mail you@example.org` to check
before relying on it.

In both setups the API takes the client address from Caddy's `X-Forwarded-For`
(`FORWARDED_ALLOW_IPS: "*"`), so the IP a login records is the user's, not Caddy's.
Caddy ignores an `X-Forwarded-For` sent by the client, so the address can't be spoofed
through it. If a load balancer is ever put in front of Caddy, configure Caddy's
`trusted_proxies`, or every user will show the balancer's address.

Check the merged configuration before starting it:

```bash
docker compose config --format json | python3 -c "import json,sys; c=json.load(sys.stdin)['services']; [print(s, [p.get('published') for p in c[s].get('ports', [])]) for s in c]"
```

## Troubleshooting

**Mosquitto will not start / restarts in a loop.** Almost always the missing password
file — it is gitignored, so a fresh clone never has one. Run `make mqtt-passwd`, then
`docker-compose logs mosquitto`. Same if you changed `MQTT_PASSWORD` and did not
regenerate.

**`api` and `mqtt-handler` never start; `meshbee-migrate` exited 1.** Read
`docker-compose logs migrate`. "no alembic_version" means a database created before
Alembic: stamp it once, as described in
[`database/README.md`](database/README.md#existing-installations).

**A password change had no effect.** `POSTGRES_PASSWORD` is applied **only when the data
directory is empty**, and `postgres_data` survives `docker-compose down`, rebuilds and
restarts. Either `docker-compose down -v` (which **destroys every reading**) or change
it inside PostgreSQL. Schema changes are different: they go through a migration — see
[`database/README.md`](database/README.md#changing-the-schema).

**`meshbee-migrate` or `meshbee-seed` shows `Exited (0)`.** Normal — they are one-shot jobs.

**`seed` exits 1 with "Configurazione non valida".** `ADMIN_PASSWORD` or
`USER_PASSWORD` is missing or shorter than 8 characters. Fix `.env`, then
`docker-compose up -d seed`.

**Readings never arrive.** In order: is the broker up (`docker-compose logs mosquitto`);
is the handler connected and authenticated (`docker-compose logs -f mqtt-handler`); is
the node publishing to `beehive/<id>/data` and not to a deeper topic — the subscription
is `beehive/+/data`, which matches exactly one level. Then check the payload against
[`mqtt_handler/README.md`](mqtt_handler/README.md#payload): an out-of-range measurement
is stored as null and logged as a warning; a whole message is dropped (`Lettura
scartata`) only when its hive can't be resolved or the payload itself is unusable.

**Code changes in `mqtt_handler/` do nothing.** There is no hot reload:
`docker-compose restart mqtt-handler`.

**The whole integration tier fails to connect.** `postgres-test` is behind a compose
profile and is not started by a plain `up`:
`docker-compose --profile test up -d postgres-test`.

**`/health` says `unhealthy`.** The API is up but the database is not reachable. The
reason is in `docker-compose logs api`, not in the body: the endpoint is public and the
error names the database host and user. `/health` deliberately answers 200 either way,
so a monitor must read the body.

## License

Distributed under **AGPL-3.0**. See [LICENSE](LICENSE).

## Versioning and contributing

Releases follow semantic versioning; the tag on the
[latest release](https://github.com/fablab-imperia/meshbee-server/releases/latest) is
the one to deploy. Compatibility between the repositories of the project is tracked in
the umbrella repo:
[compatibility matrix](https://fablab-imperia.github.io/meshbee/contract/compatibility/).

Releases are cut by [release-please](https://github.com/googleapis/release-please)
(`.github/workflows/release-please.yml`). Every push to `main` opens or updates a
**release PR** that picks the next version from the commit types — `fix:` → patch,
`feat:` → minor, `!` or `BREAKING CHANGE:` → major — and writes it to
`API_VERSION` in `api/config.py`, `info.version` in `api/openapi.json`, the version
in `pyproject.toml` and a new entry in `CHANGELOG.md`. Merging that PR creates the tag
(`1.3.0`, no `v`) and the GitHub release. So:

- **Don't bump versions or tag by hand.** Merge the release PR when you want to ship.
- **Squash-merge PRs**, so the PR title becomes the one commit release-please reads.
  A plain merge commit is ignored, and a title that isn't a Conventional Commit is
  left out of the changelog.
- **To pick a version yourself**, put `Release-As: 2.0.0` in the body of a commit.

Every pull request runs four checks, all of which should pass before merging:

- **`ci / test`**: the whole test suite against a throwaway PostgreSQL
  ([details](tests/README.md#running)). It includes the checks that the committed
  `api/openapi.json` and `mqtt_handler/mqtt-payload.schema.json` match the code.
- **`ci / lint`**: `ruff check` and `ruff format --check` are clean.
- **`ci / images`**: both Docker images still build.
- **`pr-title`**: the PR title is a Conventional Commit, since it becomes the
  squashed commit release-please reads.

Dependabot (`.github/dependabot.yml`) opens weekly PRs for Python packages, base
images and the pinned GitHub Actions.

Contributions are welcome — see the organisation's
[CONTRIBUTING](https://github.com/fablab-imperia/.github/blob/main/CONTRIBUTING.md).
Commits follow [Conventional Commits](https://www.conventionalcommits.org/).
Documentation is bilingual: English is canonical (`README.md`), Italian is the
translation (`README.it.md`), and both are kept in step.

## Support

Open an [issue](https://github.com/fablab-imperia/meshbee-server/issues), or write to
[Fablab Imperia APS](https://www.fablabimperia.org).
