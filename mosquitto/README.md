# `mosquitto/` — MQTT broker

*[Versione italiana](README.it.md)*

This directory is the **state directory of the Mosquitto broker**, bind-mounted
straight into the `eclipse-mosquitto:2.0` container. It holds no application
code: the broker is an off-the-shelf image, and everything here is its
configuration and runtime data.

## Contents

| Path | What it is | In git |
|---|---|---|
| `config/mosquitto.conf` | Broker configuration. The only source file here. | **tracked** |
| `config/passwd` | Broker credentials, bcrypt-hashed by `mosquitto_passwd`. | ignored — it is a secret |
| `data/mosquitto.db` | Persistence: retained messages and queued QoS 1/2 messages for offline subscribers. | ignored — runtime state |

`docker-compose.yml` mounts the first two:

```yaml
volumes:
  - ./mosquitto/config:/mosquitto/config
  - ./mosquitto/data:/mosquitto/data
```

There is deliberately **no log mount** — the broker logs to stdout and Docker
rotates it. Read it with `docker-compose logs -f mosquitto`.

> If you have a leftover `mosquitto/log/` directory from an older checkout,
> nothing writes to it any more and it can be deleted.

## How it fits the system

```
ESP32 nodes ──MQTT──▶ Mosquitto ──▶ mqtt-handler ──▶ PostgreSQL ◀── FastAPI ◀── app
                       :1883         (subscriber)                    (api)
```

The broker is the **entry point for sensor data**. Nodes publish to
`beehive/<id_nodo>/data`; the `mqtt-handler` service subscribes to
`beehive/+/data`, decodes the payload and stores it through `meshbee_core`.

Two things to keep in mind:

- **The API never touches MQTT.** It reads the same database, but it is not a
  broker client. Restarting the broker does not affect the REST API.
- **Mosquitto stores nothing of ours.** `data/` only holds broker-level
  bookkeeping. The readings live in PostgreSQL. Deleting `data/` loses at most
  undelivered retained/QoS messages, never stored readings.

Ports: **1883** (MQTT, used) and **9001** (WebSockets, configured but unused —
it exists for a future browser client).

## Setup

The broker runs with `allow_anonymous false`, so **it will not start without
`config/passwd`**. This is the single most common cause of a failing stack.

```bash
make mqtt-passwd     # generates config/passwd from MQTT_USER / MQTT_PASSWORD in .env
```

`make setup` does this for you on a fresh clone. **Regenerate it whenever
`MQTT_PASSWORD` changes in `.env`** — the file holds a hash, so it does not
follow the variable automatically, and the handler will start failing
authentication.

## Development

Publish a test reading (from inside the broker container, so no client install
is needed):

```bash
set -a; . ./.env; set +a
docker-compose exec -T mosquitto mosquitto_pub \
  -h localhost -u "$MQTT_USER" -P "$MQTT_PASSWORD" \
  -t beehive/NODE001/data \
  -m '{"id_sensore":"SENSOR01","temperatura":34.5,"umidita":65,"peso":42.35}'
```

Watch every topic live — useful to confirm a node is actually transmitting:

```bash
docker-compose exec mosquitto mosquitto_sub \
  -h localhost -u "$MQTT_USER" -P "$MQTT_PASSWORD" -t 'beehive/#' -v
```

Follow the broker and the handler side by side:

```bash
docker-compose logs -f mosquitto
docker-compose logs -f mqtt-handler     # or: make logs-mqtt
```

Confirm authentication is really enforced — this must be refused:

```bash
docker-compose exec -T mosquitto mosquitto_pub -h localhost -t beehive/X/data -m '{}'
# Error: The connection was refused.
```

After editing `mosquitto.conf`, restart and **read the log** — a bad directive
makes the broker exit and restart in a loop, which `docker-compose ps` alone
will not make obvious:

```bash
docker-compose up -d --force-recreate mosquitto
docker-compose logs --tail=20 mosquitto
```

## Gotchas

- **`max_packet_size` does not accept `0`.** It is the modern replacement for
  the deprecated `message_size_limit 0`, but passing `0` makes the broker refuse
  to start. No limit is already the default, so the directive is simply absent.
- **No ACLs.** Any account that authenticates can publish and subscribe to any
  topic. With a single shared node credential that is the current design; an
  `acl_file` would be the way to restrict a node to its own topic.
- **The handler subscribes to `beehive/+/data`** — one level of wildcard. A node
  publishing to `beehive/NODE001/sensors/data` will connect happily and be
  silently ignored. See `MQTT_TOPIC` in `mqtt_handler/config.py`.
- **Credentials are shared.** Every node uses the same `MQTT_USER`, so a
  compromised node cannot be revoked individually.

## Related

- `mqtt_handler/` — the subscriber: `payload.py` decodes, `handler.py` stores.
- `docker-compose.yml` — the `mosquitto` and `mqtt-handler` services.
- Main [README](../README.md) — the MQTT payload format and the full stack.
