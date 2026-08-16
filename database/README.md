# `database/` — PostgreSQL schema

*[Versione italiana](README.it.md)*

The schema, and the migrations that got it here. PostgreSQL 15, running as the
`postgres` service; the data lives in the named volume `postgres_data`.

Domain names are Italian throughout — `utenti`, `nodi`, `arnie`, `letture` — because
they are the vocabulary of the project, not an accident of translation.

## Contents

| Path | What it is |
|---|---|
| `init.sql` | The **current** schema. Mounted at `/docker-entrypoint-initdb.d/init.sql`. |
| `migrate_v2.sql` | Coordinates in, alarms out. |
| `migrate_v3.sql` | Rebuild of `v_arnie_stato` with the full column list. |
| `migrate_v4.sql` | Removal of the `sensori` table and the unused views. |

**`init.sql` runs only once, on an empty volume.** On every later start PostgreSQL sees
an initialised data directory and ignores it entirely — this is the single most
surprising thing about the setup, and it is covered under
[Changing the schema](#changing-the-schema).

## Tables

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
| `ultimo_messaggio` | TIMESTAMP | **Written by a trigger. Never set it from Python** — see [Trigger](#trigger). |
| `attivo` | BOOLEAN | Soft delete. |
| `configurazione` | JSONB | Per-node settings. |

There is **no `sensori` table**. A sensor's identity lives on `arnie.id_sensore_fisico`,
and readings have fixed columns rather than generic `(sensore, valore)` rows. A
`sensori` table existed until `migrate_v4.sql`: it was the alternative model, never
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
| `dati_raw` | JSONB | Anything else the firmware wants to keep. |

All three measurements are nullable: a node that only carries a scale is valid.
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

## View

**`v_arnie_stato` is the only view**, and it earns its place: `arnie LEFT JOIN nodi`
plus four correlated subqueries for the latest `temperatura`, `umidita`, `peso` and
`timestamp`. That is what `GET /api/user/arnie` returns — a hive list where each row
already carries its current state.

There is no `v_letture_recenti` and there are no `v_serie_*` views; they existed until
`migrate_v4.sql` and were never queried. The reason is structural: **a view takes no
parameters**. Reading history means hive + time window + LIMIT, which is
`repository/letture.py::list_by_arnia` and `::series`. A view with a fixed 7-day window
cannot express it, so it would have encapsulated everything except the part that
matters.

## Trigger

One trigger, `trigger_aggiorna_nodo`: `AFTER INSERT ON letture FOR EACH ROW`, setting
`nodi.ultimo_messaggio = NEW.timestamp`.

**`nodi.ultimo_messaggio` is owned by the database.** Writing it from Python
accomplishes nothing — the trigger fires afterwards and overwrites you. Recording that
a node was heard from is the *reading's* job, which is why
`services/ingest.py` registers the node without touching that column.

Two known defects, both tracked in
[issue #17](https://github.com/fablab-imperia/meshbee-server/issues/17):

- **Wrong clock source.** It copies the *reported* timestamp, so a node with a wrong
  clock reports itself as stale (or as reporting from the future). "When did we last
  hear from this node" should be server time.
- **`FOR EACH ROW` costs about 55× on bulk inserts.** A backfill fires one UPDATE per
  row for a value only the last row's matters. `FOR EACH STATEMENT` would fix it.

## Changing the schema

`init.sql` runs **only when the data directory is empty**. So does `POSTGRES_PASSWORD`
— PostgreSQL sets it at init and ignores the variable afterwards. And `postgres_data`
survives `docker-compose down`, rebuilds and restarts.

Editing `init.sql` on a running installation therefore changes nothing. Two ways
forward:

```bash
# Development: throw the data away and start clean.
docker-compose down -v && docker-compose up -d      # DESTROYS every reading
```

```bash
# Anything with data worth keeping: write a migration and apply it.
docker-compose exec -T postgres psql -U beehive_user -d beehive_iot < database/migrate_v5.sql
```

**Do both**: a migration for existing installations *and* the same change in
`init.sql`, which stays the description of a fresh database. Wrap a migration in
`BEGIN`/`COMMIT`, make it idempotent, and end it with a query that verifies the result
— all three existing migrations do.

`init.sql` does not drift, because the integration test suite drops the schema and
reloads it from this file **on every run**. A statement that no longer parses fails
the whole suite.

## Migrations

| File | What it did |
|---|---|
| `migrate_v2.sql` | Added `latitudine`/`longitudine` with their CHECKs; **removed the alarms feature** entirely (table `allarmi`, view `v_allarmi_attivi`, function `controlla_soglie_allarmi`, trigger `trigger_controlla_allarmi`); rebuilt `v_arnie_stato` with coordinates; created the `v_serie_*` views. |
| `migrate_v3.sql` | Dropped and recreated `v_arnie_stato` with the full, correctly ordered column list — `CREATE OR REPLACE VIEW` cannot reorder or insert columns. |
| `migrate_v4.sql` | Dropped the `sensori` table (guarded: it raises if the table holds rows) and the four unused views (`v_serie_temperatura`, `v_serie_umidita`, `v_serie_peso`, `v_letture_recenti`). |

Alarms were removed in v2 and are not coming back in this shape: thresholds belong
where they can be configured per hive, not hard-coded in a trigger.

## Sample data

`init.sql` seeds one node (`NODE001`, "Apiario Collina"), two hives (`SENSOR01` /
`SENSOR02`) with coordinates and metadata, and four readings — enough for the app to
have something to draw on a fresh install.

Accounts, associations and the sample activity come from `scripts/seed.py` instead,
because they need a real bcrypt hash. See the main [README](../README.md#setup).

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
SELECT * FROM v_arnie_stato;
SELECT id_arnia, count(*), max(timestamp) FROM letture GROUP BY id_arnia;
```

Tests that touch SQL live in `tests/integration/` — the repository tests verify column
names, joins and parameter order against a real database, and
`tests/integration/core/test_schemas.py` asserts that the ranges here and the
validators in `meshbee_core/schemas.py` still agree. See [`tests/`](../tests/README.md).

## Gotchas

- **`init.sql` and `POSTGRES_PASSWORD` only apply to a fresh volume.** See
  [Changing the schema](#changing-the-schema).
- **Every CHECK here is duplicated as a pydantic validator** in
  `meshbee_core/schemas.py`, with nothing linking them. Change one, change the other,
  and add a case to `tests/integration/core/test_schemas.py`.
- **`ruolo` is `'user'`, `permessi` is `('read','write','admin')`.** Test fakes accept
  anything; the real database does not.
- **Nothing is hard-deleted.** Users, hives and nodes have an `attivo`/`attiva` flag,
  and readings are kept when their hive is retired. `ON DELETE CASCADE` is a safety
  net, not a workflow.
- **`nodi.ultimo_messaggio` belongs to the trigger.** See [Trigger](#trigger).

## Related

- [`meshbee_core/`](../meshbee_core/README.md) — `repository/`, the only code that writes SQL.
- [`api/`](../api/README.md) — the endpoints these tables answer.
- [`mqtt_handler/`](../mqtt_handler/README.md) — what fills `letture`.
- [`tests/`](../tests/README.md) — how `init.sql` is kept honest.
- Main [README](../README.md) — the stack as a whole.
