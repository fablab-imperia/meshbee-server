# `mosquitto/` — broker MQTT

*[English version](README.md)*

Questa directory è la **directory di stato del broker Mosquitto**, montata
direttamente dentro il container `eclipse-mosquitto:2.0`. Non contiene codice
applicativo: il broker è un'immagine pronta all'uso, e qui c'è soltanto la sua
configurazione e i suoi dati di runtime.

## Contenuto

| Percorso | Cos'è | In git |
|---|---|---|
| `config/mosquitto.conf` | Configurazione del broker. L'unico file sorgente qui. | **versionato** |
| `config/passwd` | Credenziali del broker, con hash bcrypt generato da `mosquitto_passwd`. | ignorato — è un segreto |
| `data/mosquitto.db` | Persistenza: messaggi retained e code QoS 1/2 per i subscriber offline. | ignorato — stato di runtime |

`docker-compose.yml` monta i primi due:

```yaml
volumes:
  - ./mosquitto/config:/mosquitto/config
  - ./mosquitto/data:/mosquitto/data
```

**Non c'è alcun mount per i log**, di proposito: il broker scrive su stdout e
Docker si occupa della rotazione. Si leggono con
`docker-compose logs -f mosquitto`.

> Se ti resta una directory `mosquitto/log/` da un checkout precedente, non ci
> scrive più nessuno e può essere cancellata.

## Come si inserisce nel sistema

```
Nodi ESP32 ──MQTT──▶ Mosquitto ──▶ mqtt-handler ──▶ PostgreSQL ◀── FastAPI ◀── app
                      :1883         (subscriber)                    (api)
```

Il broker è il **punto d'ingresso dei dati dei sensori**. I nodi pubblicano su
`beehive/<id_nodo>/data`; il servizio `mqtt-handler` si sottoscrive a
`beehive/+/data`, decodifica il payload e lo salva passando per `meshbee_core`.

Due cose da tenere a mente:

- **L'API non tocca MQTT.** Legge lo stesso database, ma non è un client del
  broker. Riavviare il broker non ha effetti sull'API REST.
- **Mosquitto non conserva dati nostri.** In `data/` c'è solo contabilità
  interna del broker. Le letture stanno in PostgreSQL. Cancellare `data/` fa
  perdere al massimo messaggi retained/QoS non ancora consegnati, mai letture
  già salvate.

Porte: **1883** (MQTT, in uso) e **9001** (WebSocket, configurata ma non
utilizzata — è lì per un futuro client browser).

## Setup

Il broker gira con `allow_anonymous false`, quindi **non parte senza
`config/passwd`**. È di gran lunga la causa più frequente di stack che non si
avvia.

```bash
make mqtt-passwd     # genera config/passwd da MQTT_USER / MQTT_PASSWORD in .env
```

`make setup` lo fa già su un clone nuovo. **Va rigenerato ogni volta che
`MQTT_PASSWORD` cambia** in `.env`: il file contiene un hash, quindi non segue
automaticamente la variabile, e l'handler comincerebbe a fallire
l'autenticazione.

## Sviluppo

Pubblicare una lettura di prova (dall'interno del container del broker, così non
serve installare alcun client):

```bash
set -a; . ./.env; set +a
docker-compose exec -T mosquitto mosquitto_pub \
  -h localhost -u "$MQTT_USER" -P "$MQTT_PASSWORD" \
  -t beehive/NODE001/data \
  -m '{"id_sensore":"SENSOR01","temperatura":34.5,"umidita":65,"peso":42.35}'
```

Osservare tutti i topic in tempo reale — utile per capire se un nodo sta
davvero trasmettendo:

```bash
docker-compose exec mosquitto mosquitto_sub \
  -h localhost -u "$MQTT_USER" -P "$MQTT_PASSWORD" -t 'beehive/#' -v
```

Seguire broker e handler affiancati:

```bash
docker-compose logs -f mosquitto
docker-compose logs -f mqtt-handler     # oppure: make logs-mqtt
```

Verificare che l'autenticazione sia davvero attiva — questo deve essere
rifiutato:

```bash
docker-compose exec -T mosquitto mosquitto_pub -h localhost -t beehive/X/data -m '{}'
# Error: The connection was refused.
```

Dopo aver modificato `mosquitto.conf`, riavvia e **leggi il log**: una direttiva
sbagliata fa uscire il broker che poi riparte in loop, cosa che
`docker-compose ps` da solo non rende evidente.

```bash
docker-compose up -d --force-recreate mosquitto
docker-compose logs --tail=20 mosquitto
```

## Trappole

- **`max_packet_size` non accetta `0`.** È il sostituto moderno del deprecato
  `message_size_limit 0`, ma passandogli `0` il broker si rifiuta di partire.
  Nessun limite è già il default, quindi la direttiva è semplicemente assente.
- **Nessuna ACL.** Qualunque account autenticato può pubblicare e sottoscrivere
  qualsiasi topic. Con un'unica credenziale condivisa fra i nodi è il design
  attuale; un `acl_file` sarebbe il modo per limitare ogni nodo al proprio topic.
- **L'handler si sottoscrive a `beehive/+/data`** — un solo livello di wildcard.
  Un nodo che pubblica su `beehive/NODE001/sensors/data` si connette senza errori
  e viene ignorato in silenzio. Vedi `MQTT_TOPIC` in `mqtt_handler/config.py`.
- **Le credenziali sono condivise.** Tutti i nodi usano lo stesso `MQTT_USER`,
  quindi un nodo compromesso non può essere revocato singolarmente.

## Collegamenti

- [`mqtt_handler/`](../mqtt_handler/README.it.md) — il subscriber: `payload.py` decodifica, `handler.py` salva, e il formato del payload.
- `docker-compose.yml` — i servizi `mosquitto` e `mqtt-handler`.
- [README](../README.it.md) principale — lo stack nel suo insieme.
