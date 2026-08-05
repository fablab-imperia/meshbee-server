# `mqtt_handler/` — MQTT ingest

*[Versione italiana](README.it.md)*

The **MQTT entry point**: a headless subscriber that listens to the broker, decodes
what the nodes publish and stores it. It has no HTTP surface, no port and no clients —
it is a loop between Mosquitto and PostgreSQL.

```
ESP32 nodes ──MQTT──▶ Mosquitto ──▶ mqtt-handler ──▶ PostgreSQL ◀── FastAPI
                       :1883         (this package)                 (api)
```

Like the API it is **thin**: `payload.py` decodes, `handler.py` opens a cursor and
calls one service. The writing itself is `meshbee_core.services.ingest`, which is why
a reading arriving over MQTT and one posted to `/api/admin/letture` produce the same
row.

## Contents

| Path | What it is |
|---|---|
| `handler.py` | Broker plumbing: connect, subscribe, the `on_message` callback, signal handling. |
| `payload.py` | Decoding what a node actually put on the wire. No broker, no database — the testable part. |
| `config.py` | `Settings(CoreSettings)` — the `MQTT_*` fields on top of the DB fields. |
| `__main__.py` | `python -m mqtt_handler` → `handler.main()`. |
| `Dockerfile` | Image for the `mqtt-handler` service. Build context is the repo root. |
| `requirements.txt` | `paho-mqtt` only — everything else comes from `meshbee_core`. |

## The topic

The handler subscribes to **`beehive/+/data`** (`MQTT_TOPIC`). Nodes publish to
`beehive/<id_nodo>/data`.

`+` is **one** level of wildcard. A node publishing to `beehive/NODE001/sensors/data`
connects happily, gets no error from the broker, and is silently ignored — this is the
failure mode to check first when a node "works" but nothing lands in the database.

## Payload

The payload is a **JSON object**. Anything else — an array, a bare number, invalid
UTF-8, malformed JSON — is logged and dropped.

| Field | Type | Required | Notes |
|---|---|---|---|
| `id_nodo` | string | see below | Falls back to the topic. |
| `id_sensore` | string | no | Identifies the hive on that node. Unknown value → a hive is created. |
| `timestamp` | string | no | ISO 8601. Absent or unparseable → server time. |
| `temperatura` | number | no | °C, **−50 to 100**. |
| `umidita` | number | no | %, **0 to 100**. |
| `peso` | number | no | kg, **≥ 0**. |
| `dati_raw` | object | no | Stored verbatim as JSONB — battery, RSSI, whatever the firmware wants to keep. |

```json
{
  "id_sensore": "SENSOR01",
  "timestamp": "2026-08-05T14:30:00Z",
  "temperatura": 34.5,
  "umidita": 65.2,
  "peso": 42.35,
  "dati_raw": {"battery": 3.7, "rssi": -67}
}
```

Four details that are easy to get wrong:

- **The node id may come from either place, and the payload wins.** `id_nodo` in the
  payload overrides the topic segment. A message is only rejected when neither
  supplies one.
- **A bad clock never costs a measurement.** `Z` is rewritten to `+00:00` (the ESP32
  firmware sends the Zulu suffix, which `fromisoformat` rejected before Python 3.11);
  a value that still will not parse is logged as a warning and the reading is stored
  with the **server's** time. Silence is worse than a slightly wrong timestamp.
- **Every measurement is optional, but the ranges are enforced.** A payload with only
  `peso` is valid; a `temperatura` of 200 is not, and the whole message is dropped. The
  same limits exist as CHECK constraints in the schema — see
  [`database/`](../database/README.md).
- **`timestamp` is what the trigger writes to `nodi.ultimo_messaggio`**, not arrival
  time. A node with a wrong clock will make itself look stale
  ([issue #17](https://github.com/fablab-imperia/meshbee-server/issues/17)).

## Auto-provisioning

A node may start transmitting before anybody registers it, so the ingest path creates
what it needs instead of refusing the reading (`meshbee_core/services/ingest.py`):

1. The node is registered if it is not already known (`Nodo <id_nodo>`).
2. With an `id_sensore`: the matching hive is used, or **a new one is created**
   (`Arnia <id_nodo>-<id_sensore>`).
3. Without an `id_sensore`: the node's **first** hive is used.
4. If the node has no hive at all and sent no `id_sensore`, the reading is dropped with
   `NotFound` — raising rather than returning quietly, because the caller's cursor
   commits on a clean exit and a silent return would leave the node registration
   behind.

**`POST /api/admin/letture` deliberately does not do any of this** — it answers 404 for
an unknown arnia. Provisioning is a property of the ingest path, not of the shared
layer. Everything that must stay identical between the two paths is pinned by
`tests/integration/test_ingest_parity.py`, which compares every column but
`id_lettura`.

## Configuration

`Settings` extends `CoreSettings` (the database fields — see
[`meshbee_core/`](../meshbee_core/README.md#configuration)) with:

| Variable | Default | Set by compose to |
|---|---|---|
| `MQTT_BROKER` | `localhost` | `mosquitto` |
| `MQTT_PORT` | `1883` | `1883` |
| `MQTT_TOPIC` | `beehive/+/data` | `beehive/+/data` |
| `MQTT_CLIENT_ID` | `beehive-mqtt-handler` | — |
| `MQTT_USER` | none | `${MQTT_USER:-beehive}` |
| `MQTT_PASSWORD` | none | `${MQTT_PASSWORD}` |

Credentials are only sent when **both** are set; with either missing the client
connects anonymously, which the broker refuses (`allow_anonymous false`). The password
must match the hash in `mosquitto/config/passwd` — regenerate it with `make mqtt-passwd`
whenever you change `MQTT_PASSWORD`.

## Development

**There is no hot reload.** Editing a file here changes nothing until the process
restarts — this is the single most common way to spend ten minutes debugging code that
is not running:

```bash
docker-compose restart mqtt-handler        # or: make restart-mqtt
docker-compose logs -f mqtt-handler        # or: make logs-mqtt
```

Publish a test reading from inside the broker container, so no client install is needed:

```bash
set -a; . ./.env; set +a
docker-compose exec -T mosquitto mosquitto_pub \
  -h localhost -u "$MQTT_USER" -P "$MQTT_PASSWORD" \
  -t beehive/NODE001/data \
  -m '{"id_sensore":"SENSOR01","temperatura":34.5,"umidita":65,"peso":42.35}'
```

The handler logs one line per stored reading. Confirm it landed:

```bash
docker-compose exec postgres psql -U beehive_user -d beehive_iot \
  -c 'SELECT id_lettura, id_arnia, timestamp, temperatura FROM letture ORDER BY id_lettura DESC LIMIT 3;'
```

Tests live in `tests/unit/mqtt_handler/` (payload decoding, no broker needed) and
`tests/integration/test_ingest_parity.py` — see [`tests/`](../tests/README.md).

## Gotchas

- **No hot reload** — `docker-compose restart mqtt-handler` after every edit.
- **A rejected reading is dropped, not retried.** A `CoreError` is logged as
  `Lettura scartata` with no traceback and the message is gone: the broker got its
  acknowledgement before the handler ever looked at the payload. There is no
  dead-letter queue.
- **`beehive/+/data` matches exactly one level** — see [The topic](#the-topic).
- **Every node shares one credential.** A compromised node cannot be revoked
  individually, and any account that authenticates can publish to any topic (no ACLs).
  See [`mosquitto/`](../mosquitto/README.md).
- **The pool here is 10 connections**, against the API's 20 — one process consuming one
  message at a time does not need more.

## Related

- [`mosquitto/`](../mosquitto/README.md) — the broker: credentials, persistence, ACLs.
- [`meshbee_core/`](../meshbee_core/README.md) — `services/ingest.py`, where the reading is actually written.
- [`api/`](../api/README.md) — the other writer, and `POST /api/admin/letture`.
- [`database/`](../database/README.md) — `letture`, `nodi`, `arnie` and the trigger.
- Main [README](../README.md) — the stack as a whole.
