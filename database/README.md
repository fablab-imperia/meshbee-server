# `database/` — PostgreSQL schema

*[Versione italiana](README.it.md)*

What is in the database, and how it changes. PostgreSQL 15, running as the
`postgres` service; the data lives in the named volume `postgres_data`.

This directory holds documentation only. The schema is defined in Python, in
[`meshbee_core/models.py`](../meshbee_core/models.py), with its bounds and value sets in
[`meshbee_core/limits.py`](../meshbee_core/limits.py); the migrations that bring a
database up to it are Alembic revisions in
[`meshbee_core/migrations/versions/`](../meshbee_core/migrations/versions/).

Domain names are Italian throughout — `utenti`, `nodi`, `arnie`, `letture` — because
they are the vocabulary of the project, not an accident of translation.

## Contents

| Path | What it is |
|---|---|
| `meshbee_core/models.py` | The **current** schema, as SQLModel table classes. The single source. |
| `meshbee_core/limits.py` | Ranges and value sets the CHECK constraints are built from. |
| `meshbee_core/migrations/` | Alembic: `env.py`, and one file per revision under `versions/`. |
| `scripts/migrate.py` | What the `migrate` compose service runs: `upgrade head`, then exit. |
| `alembic.ini` (repo root) | For the `alembic` CLI only, when authoring a revision. |

**The schema is applied by the `migrate` service, on every start.** It runs before
`api`, `mqtt-handler` and `seed`, which all wait for it to exit 0, and does nothing when
the database is already at head. See [Changing the schema](#changing-the-schema).

## Tables

A table and the API responses built from it share one declaration in
[`meshbee_core/models.py`](../meshbee_core/models.py), so every column a response
requires is NOT NULL here too (revision `0002`). The tables below give the remaining
detail.

### `utenti` — accounts

| Column | Type | Notes |
|---|---|---|
| `id_utente` | SERIAL | PK |
| `email` | VARCHAR(255) | UNIQUE NOT NULL. Normalised (trimmed, lowercased) by the application. |
| `password_hash` | VARCHAR(255) | bcrypt, cost 12. |
| `nome`, `cognome` | VARCHAR(100) | NOT NULL |
| `ruolo` | VARCHAR(20) | CHECK `('user','admin')`, default `user`. |
| `data_creazione`, `data_attivazione`, `data_disattivazione`, `ultimo_accesso` | TIMESTAMP | CHECK: deactivation cannot precede activation. |
| `attivo` | BOOLEAN | default true. Accounts are **soft-deleted**, never removed. |

`ruolo` is `'user'`, **not** `'utente'` — the one Italian/English seam in the data, and
a reliable source of a failing INSERT.

### `nodi` — transmitters

| Column | Type | Notes |
|---|---|---|
| `id_nodo` | VARCHAR(50) | PK — the id the firmware publishes under. |
| `nome_nodo`, `descrizione`, `posizione` | | Free text. |
| `data_registrazione` | TIMESTAMP | |
| `ultimo_messaggio` | TIMESTAMP | When the last MQTT message was **received**; set by `services/ingest.py` — see [No views, no triggers](#no-views-no-triggers). |
| `attivo` | BOOLEAN | Soft delete. |
| `configurazione` | JSONB | Per-node settings. |

There is **no `sensori` table**. A sensor's identity lives on `arnie.id_sensore_fisico`,
and readings have fixed columns rather than generic `(sensore, valore)` rows. A
`sensori` table existed until the old hand-written `migrate_v4.sql`: it was the alternative model, never
joined to `arnie` and never read.

### `arnie` — hives

| Column | Type | Notes |
|---|---|---|
| `id_arnia` | SERIAL | PK |
| `id_nodo` | VARCHAR(50) | FK → `nodi` ON DELETE CASCADE. |
| `id_sensore_fisico` | VARCHAR(50) | NOT NULL. **UNIQUE together with `id_nodo`** — that pair is how ingest resolves a reading to a hive. |
| `nome_arnia`, `descrizione`, `posizione` | | Free text. |
| `latitudine`, `longitudine` | DECIMAL(9,6) | Decimal degrees, optional. CHECK −90..90 and −180..180. |
| `data_installazione`, `data_rimozione` | TIMESTAMP | |
| `attiva` | BOOLEAN | Soft delete — readings survive. |
| `metadati` | JSONB | Queen's race and year, hive colour, whatever the beekeeper tracks. |
| `id_apiario` | INTEGER | FK → `apiari` ON DELETE SET NULL. **Optional**: hives provisioned over MQTT, and those that predate apiaries, are in none. |

### `apiari` — where hives stand

| Column | Type | Notes |
|---|---|---|
| `id_apiario` | SERIAL | PK |
| `nome_apiario` | VARCHAR(100) | NOT NULL |
| `descrizione`, `posizione` | | Free text. |
| `latitudine`, `longitudine` | DECIMAL(9,6) | Same bounds as a hive's, CHECKs prefixed `apiari_`. Independent of the hives' own coordinates. |
| `id_utente_proprietario` | INTEGER | FK → `utenti` ON DELETE SET NULL. **Informational**: it grants nothing. |
| `data_creazione`, `data_disattivazione` | TIMESTAMP | |
| `attivo` | BOOLEAN | Soft delete, refused by the service while active hives are still in it. |
| `metadati` | JSONB | |

An apiary has **no permissions of its own**: a user sees one because they are
associated (`utenti_arnie`) with an active hive in it, and inside it only those hives.

### `utenti_arnie` — who may see which hive

| Column | Type | Notes |
|---|---|---|
| `id` | SERIAL | PK |
| `id_utente`, `id_arnia` | INTEGER | FKs, CASCADE. **UNIQUE together.** |
| `data_associazione`, `data_disassociazione` | TIMESTAMP | CHECK: end cannot precede start. |
| `permessi` | VARCHAR(20) | CHECK `('read','write','admin')`, default `read`. |
| `attivo` | BOOLEAN | Revocation is a flag, so the history stays. |

Permissions are a ladder: `read` < `write` < `admin`. An account with `ruolo = 'admin'`
bypasses this table entirely.

### `letture` — the telemetry

| Column | Type | Notes |
|---|---|---|
| `id_lettura` | BIGSERIAL | PK — `BIG` on purpose, this is the table that grows. |
| `id_arnia` | INTEGER | FK → `arnie` CASCADE. |
| `id_nodo` | VARCHAR(50) | NOT NULL. Denormalised: which node reported it, even if the hive moves. |
| `timestamp` | TIMESTAMP | NOT NULL, default `CURRENT_TIMESTAMP`. **The node's clock**, when it sends one. |
| `temperatura` | DECIMAL(5,2) | CHECK −50..100 |
| `umidita` | DECIMAL(5,2) | CHECK 0..100 |
| `peso` | DECIMAL(10,3) | CHECK ≥ 0 |
| `batteria` | DECIMAL(4,3) | CHECK 0..5. Node battery voltage in V — the payload key is `bat`. |
| `dati_raw` | JSONB | Anything else the firmware wants to keep. |

All four measurements are nullable: a node that only carries a scale is valid.
Indexes: `id_arnia`, `timestamp DESC`, the composite `(id_arnia, timestamp DESC)` that
every chart query uses, and `id_nodo`.

### `log_attivita` — what the beekeeper did

| Column | Type | Notes |
|---|---|---|
| `id_log` | BIGSERIAL | PK |
| `id_utente` | INTEGER | FK → `utenti` **ON DELETE SET NULL** — the record outlives the account. |
| `id_arnia` | INTEGER | FK → `arnie` CASCADE. |
| `timestamp` | TIMESTAMP | Backdatable: you log the inspection after you have washed your hands. |
| `tipo_attivita` | VARCHAR(50) | NOT NULL, CHECK over 8 values: `ispezione`, `trattamento`, `raccolta_miele`, `nutrizione`, `sostituzione_regina`, `controllo_salute`, `manutenzione`, `altro`. |
| `descrizione` | TEXT | |
| `dati` | JSONB | Structured detail — frames of honey, brood present, and so on. |

### `token_sessione` — unused, deliberately

Refresh tokens are **stateless JWTs** and there is no `/api/auth/refresh` endpoint, so
nothing in the application reads or writes this table. It is kept because it is the
right shape for the feature when it lands (revocation, `ip_address`, `user_agent`):
[issue #16](https://github.com/fablab-imperia/meshbee-server/issues/16).

## No views, no triggers

**The database holds no logic**: no view, no trigger, no function of ours.
`tests/integration/test_migrations.py` fails if a migration leaves one behind. What used
to live here is now in `meshbee_core`, where it is declared once and tested like the
rest of the code:

- **The hive list with its latest readings** was the view `v_arnie_stato`. It is now
  `repository/arnie.py::STATO`: `arnie LEFT JOIN nodi LEFT JOIN apiari` plus one `LATERAL` subquery for
  the latest reading, so every "ultimo" value comes from the same row. That is what
  `GET /api/user/arnie` returns.
- **`nodi.ultimo_messaggio`** was set by `trigger_aggiorna_nodo` on every insert into
  `letture`, with the reading's *reported* time and one UPDATE per row
  ([issue #17](https://github.com/fablab-imperia/meshbee-server/issues/17)). It is now
  set by `services/ingest.py`, once per MQTT message, with the time it was
  **received**. A node with a wrong clock, or a replay of buffered readings, can no
  longer move it backwards, and a bulk insert into `letture` no longer touches `nodi`.
  Only a message from the node counts: a reading entered through the API, or the
  seed's sample readings, leave it alone.

Both were dropped by revision `0003`; its downgrade recreates them.

There never were `v_letture_recenti` or `v_serie_*` views worth keeping either — they
existed until the old `migrate_v4.sql` and were never queried. **A view takes no
parameters**, and reading history means hive + time window + LIMIT, which is
`repository/letture.py::list_by_arnia` and `::series`.

## Changing the schema

Change the models, then generate a revision from the difference:

```bash
# 1. Edit meshbee_core/models.py (or a constant in limits.py).
# 2. Generate the revision, against a database that is at head:
docker-compose exec api alembic revision --autogenerate -m "add x to letture"
# 3. Read the new file in meshbee_core/migrations/versions/ and complete it (below).
# 4. Apply it — or just restart the stack, which runs `migrate` first:
docker-compose run --rm migrate
```

**Autogenerate does not see CHECK constraints.** It diffs tables, columns, types,
nullability, indexes and foreign keys; a changed range in `limits.py` produces an
empty revision. Write the constraint change by hand
(`op.drop_constraint` + `op.create_check_constraint`), with the **literal** values:
a revision is history and must not import `limits.py`, or replaying it after the
next change would build the wrong schema. `tests/integration/test_migrations.py`
builds the schema both ways — `create_all()` from the models and `upgrade head` from
the revisions — and fails, printing both definitions, if anything differs.

Views, triggers and functions are not compared either — and there should be none: logic belongs in `meshbee_core`.

### Existing installations

An install created before Alembic has the tables but no `alembic_version`, and
`migrate` refuses to touch it. If it had every hand-written migration up to
`migrate_v5.sql` applied, it is exactly at the baseline revision — mark it once:

```bash
docker-compose exec postgres pg_dump -U beehive_user beehive_iot > backup.sql   # first
docker-compose run --rm migrate alembic stamp 0001
docker-compose up -d
```

An install older than v5 must apply the missing `database/migrate_v*.sql` files first;
they are in git history before the switch to Alembic.

### Fresh volumes

`POSTGRES_PASSWORD` still applies **only when the data directory is empty** —
PostgreSQL sets it at init and ignores the variable afterwards — and `postgres_data`
survives `docker-compose down`, rebuilds and restarts. To start over in development:

```bash
docker-compose down -v && docker-compose up -d      # DESTROYS every reading
```

## Migrations

| Revision | What it did |
|---|---|
| `0001` | Baseline: the schema as the hand-written migrations left it. |
| `0002` | NOT NULL on the 16 columns the API returns as required. Fills existing NULLs first — flags to **false**, `ruolo` to `user`, `permessi` to `read` with the association deactivated, dates from the best evidence in the row — and **stops without changing anything** if a foreign key is NULL (an arnia without a node, a reading without an arnia), since those cannot be filled. |
| `0003` | Dropped `trigger_aggiorna_nodo`, its function and `v_arnie_stato`: their logic moved to `services/ingest.py` and `repository/arnie.py` (#17). |
| `0004` | Dropped the `uuid-ossp` extension, which `init.sql` installed and nothing ever used. Without CASCADE: anything depending on it makes the migration stop instead. |
| `0005` | Added `apiari` and the nullable `arnie.id_apiario` (#2). Nothing is backfilled: existing hives start in no apiary. |

Before Alembic the schema moved through hand-written scripts, applied with `psql`;
they are in git history:

| File | What it did |
|---|---|
| `migrate_v2.sql` | Added `latitudine`/`longitudine` with their CHECKs; **removed the alarms feature** entirely (table `allarmi`, view `v_allarmi_attivi`, function `controlla_soglie_allarmi`, trigger `trigger_controlla_allarmi`); rebuilt `v_arnie_stato` with coordinates; created the `v_serie_*` views. |
| `migrate_v3.sql` | Dropped and recreated `v_arnie_stato` with the full, correctly ordered column list — `CREATE OR REPLACE VIEW` cannot reorder or insert columns. |
| `migrate_v4.sql` | Dropped the `sensori` table (guarded: it raises if the table holds rows) and the four unused views (`v_serie_temperatura`, `v_serie_umidita`, `v_serie_peso`, `v_letture_recenti`). |
| `migrate_v5.sql` | Added `letture.batteria` (DECIMAL(4,3), CHECK 0..5) and appended `ultima_batteria` to `v_arnie_stato`. |

Alarms were removed in v2 and are not coming back in this shape: thresholds belong
where they can be configured per hive, not hard-coded in a trigger.

## Sample data

Revisions carry no data. On an install with no hives at all, `scripts/seed.py` creates
one apiary ("Apiario Collina"), one node (`NODE001`), two hives in that apiary
(`SENSOR01` / `SENSOR02`) with coordinates and metadata, and four readings — enough for the app to have something to
draw. Once any hive exists it leaves them alone, so deleting the demo data does not
bring it back.

The seed also creates the accounts, the associations and a sample activity. See the
main [README](../README.md#setup).

## Development

```bash
docker-compose exec postgres psql -U beehive_user -d beehive_iot      # or: make db-shell
make db-backup                                                        # → backups/backup_<timestamp>.sql
make db-restore FILE=backups/backup_20260805_120000.sql
```

Useful once you are in:

```sql
\dt                                  -- tables
\d+ letture                          -- one table, constraints included
SELECT id_arnia, count(*), max(timestamp) FROM letture GROUP BY id_arnia;
```

```bash
docker-compose exec api alembic current      # which revision the database is at
docker-compose exec api alembic history      # the chain
docker-compose exec api alembic check        # would autogenerate find anything?
```

Tests that touch SQL live in `tests/integration/` — the repository tests verify column
names, joins and parameter order against a real database, `test_migrations.py` that the
revisions match the models, and `tests/integration/core/test_schemas.py` that the
database and the API shapes in `meshbee_core/models.py` reject the same values. The test database is
built with `upgrade head` on every run. See [`tests/`](../tests/README.md).

## Gotchas

- **Autogenerate misses CHECK changes.** A new range in `limits.py` needs a hand-written
  constraint change in the revision; `test_migrations.py` fails until it has one.
- **A pre-Alembic install must be stamped once.** `migrate` refuses it until then, and
  so `api` and `mqtt-handler` do not start. See [Existing installations](#existing-installations).
- **`POSTGRES_PASSWORD` only applies to a fresh volume.** See [Fresh volumes](#fresh-volumes).
- **`ruolo` is `'user'`, `permessi` is `('read','write','admin')`.** Test fakes accept
  anything; the real database does not.
- **Nothing is hard-deleted.** Users, hives and nodes have an `attivo`/`attiva` flag,
  and readings are kept when their hive is retired. `ON DELETE CASCADE` is a safety
  net, not a workflow.
- **`nodi.ultimo_messaggio` is receipt time, and only MQTT sets it.** A reading posted through the API does not. See [No views, no triggers](#no-views-no-triggers).

## Related

- [`meshbee_core/`](../meshbee_core/README.md) — `repository/`, the only code that writes SQL.
- [`api/`](../api/README.md) — the endpoints these tables answer.
- [`mqtt_handler/`](../mqtt_handler/README.md) — what fills `letture`.
- [`tests/`](../tests/README.md) — how the migrations are kept honest.
- Main [README](../README.md) — the stack as a whole.
