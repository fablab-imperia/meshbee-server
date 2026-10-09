# `mqtt_handler/` — ingest MQTT

*[English version](README.md)*

L'**entry point MQTT**: un subscriber senza interfaccia che ascolta il broker,
decodifica quello che pubblicano i nodi e lo archivia. Non ha superficie HTTP, non ha
porte e non ha client — è un ciclo fra Mosquitto e PostgreSQL.

```
nodi ESP32 ──MQTT──▶ Mosquitto ──▶ mqtt-handler ──▶ PostgreSQL ◀── FastAPI
                      :1883        (questo package)                 (api)
```

Come l'API è **sottile**: `payload.py` decodifica, `handler.py` apre una sessione e chiama
un service. La scrittura vera è `meshbee_core.services.ingest`, ed è per questo che una
lettura arrivata via MQTT e una inviata a `/api/admin/letture` producono la stessa riga.

## Contenuto

| Percorso | Cos'è |
|---|---|
| `handler.py` | Il collegamento al broker: connessione, sottoscrizione, callback `on_message`, gestione dei segnali. |
| `payload.py` | La decodifica di quello che il nodo ha messo davvero sul filo. Niente broker, niente database — la parte testabile. |
| `contract.py` | Il formato del filo come modello pydantic. Niente ci valida contro a runtime: serve a generare lo schema. |
| `mqtt-payload.schema.json` | Lo JSON Schema generato. Committato — vedi [Schema](#schema). |
| `config.py` | `Settings(CoreSettings)` — i campi `MQTT_*` sopra a quelli del database. |
| `__main__.py` | `python -m mqtt_handler` → `handler.main()`. |
| `Dockerfile` | Immagine del servizio `mqtt-handler`. Il contesto di build è la root del repo. |
| `requirements.txt` | Solo `paho-mqtt` — tutto il resto arriva da `meshbee_core`. |

## Il topic

L'handler si sottoscrive a **`beehive/+/data`** (`MQTT_TOPIC`). I nodi pubblicano su
`beehive/<id_nodo>/data`.

`+` è **un** livello di wildcard. Un nodo che pubblica su
`beehive/NODE001/sensors/data` si connette senza problemi, non riceve nessun errore dal
broker e viene ignorato in silenzio — è la prima cosa da controllare quando un nodo
"funziona" ma nel database non arriva niente.

## Payload

Il payload è un **oggetto JSON**. Qualsiasi altra cosa — un array, un numero, UTF-8 non
valido, JSON malformato — viene loggata e scartata. La tabella qui sotto è la forma
leggibile del contratto; [Schema](#schema) è quella leggibile da una macchina.

| Campo | Tipo | Obbligatorio | Note |
|---|---|---|---|
| `id_nodo` | stringa | vedi sotto | Ripiega sul topic. |
| `id_sensore` | stringa | no | Identifica l'arnia su quel nodo. Valore sconosciuto → viene creata un'arnia. |
| `timestamp` | stringa | no | ISO 8601. Assente o non interpretabile → ora del server. |
| `temperatura` | numero | no | °C, **da −50 a 100**. |
| `umidita` | numero | no | %, **da 0 a 100**. |
| `peso` | numero | no | kg, **≥ 0**. |
| `bat` | numero | no | Tensione della batteria, V, **da 0 a 5**. Archiviata come `letture.batteria`. |
| `dati_raw` | oggetto | no | Archiviato tale e quale come JSONB — RSSI, quello che il firmware vuole conservare. |

```json
{
  "id_sensore": "SENSOR01",
  "timestamp": "2026-08-05T14:30:00Z",
  "temperatura": 34.5,
  "umidita": 65.2,
  "peso": 42.35,
  "bat": 4.01,
  "dati_raw": {"rssi": -67}
}
```

Quattro dettagli facili da sbagliare:

- **L'id del nodo può arrivare da due posti, e vince il payload.** `id_nodo` nel payload
  ha la precedenza sul segmento del topic. Un messaggio viene rifiutato solo se non lo
  fornisce nessuno dei due.
- **Un orologio sbagliato non fa perdere la misura.** La `Z` viene riscritta in `+00:00`
  (il firmware ESP32 manda il suffisso Zulu, che `fromisoformat` rifiutava prima di
  Python 3.11); un valore che comunque non si interpreta viene loggato come warning e la
  lettura viene archiviata con l'ora del **server**. Il silenzio è peggio di un timestamp
  leggermente sbagliato.
- **Ogni misura è opzionale, e un valore sbagliato non costa gli altri.** Un payload
  con la sola `peso` è valido. Una `temperatura` di 200 (o `"n/a"`) viene archiviata come
  null, il resto della lettura viene conservato, e il valore scartato viene registrato
  come testo in `dati_raw.discarded` e loggato come warning. L'inserimento manuale
  dell'API rifiuta lo stesso valore con un 422: una persona può correggerlo, un nodo no.
  I limiti sono gli stessi nei due percorsi ed esistono come vincoli CHECK nello schema
  — vedi [`database/`](../database/README.it.md).
- **`timestamp` è l'ora della lettura, non l'"ultimo contatto" del nodo.** Ogni
  messaggio archiviato imposta `nodi.ultimo_messaggio` all'ora in cui è stato
  *ricevuto*, quindi un nodo con l'orologio sbagliato risulta comunque vivo, e letture
  vecchie riprodotte non possono farla tornare indietro.

## Schema

La tabella qui sopra è prosa; [`mqtt-payload.schema.json`](mqtt-payload.schema.json) è lo
stesso contratto in **JSON Schema (draft 2020-12)**, per i consumatori che una tabella
non la sanno leggere — il firmware, l'app, un generatore di codice.

| Dove | Cos'è |
|---|---|
| `contract.py` | La fonte di verità: un modello pydantic, un campo per ogni campo del filo. |
| `mqtt-payload.schema.json` | L'artefatto generato, committato come `api/openapi.json`. |
| <https://raw.githubusercontent.com/fablab-imperia/meshbee-server/main/mqtt_handler/mqtt-payload.schema.json> | Lo stesso file servito raw da `main`, ed è quello che dice il suo `$id`. Fai riferimento a **quell'**URL — un percorso relativo si risolve solo per chi ha questo repo in locale. |

Spostare o rinominare `mqtt-payload.schema.json` rompe quindi ogni `$ref` scritto
verso di esso. Considera il percorso come parte del contratto.

**`contract.py` non è nel percorso del codice.** `parse_message` non ci valida contro e
non lo farà mai: un nodo con un sensore rotto deve comunque vedersi archiviate le altre
misure, quindi la decodifica resta permissiva e i limiti vengono applicati una volta
sola, dopo, in `meshbee_core`. Il modello esiste per essere esportato, non per girare.

Il che vuol dire che a tenere onesti i due sono solo i test.
`tests/unit/mqtt_handler/test_contract.py` verifica che i campi del modello siano
esattamente le chiavi che `parse_message` restituisce, che il JSON committato sia quello
che il modello genera e che l'esempio qui sopra sia valido — in entrambe le lingue.
I suoi limiti non sono suoi: vengono importati da `meshbee_core/limits.py`, le costanti
da cui sono costruiti `LetturaBase` e i vincoli CHECK, e
`tests/integration/core/test_schemas.py` verifica i valori pubblicati contro un database
reale.

**Rigeneralo dopo ogni modifica alla forma del payload** — non lo fa niente in automatico:

```bash
docker-compose exec api python -m scripts.export_mqtt_schema   # oppure: make mqtt-schema
```

L'output è ordinato e indentato, quindi rigenerare un contratto invariato lascia un diff
vuoto. `pytest` fallisce finché non l'hai fatto.

## Auto-provisioning

Un nodo può iniziare a trasmettere prima che qualcuno lo registri, quindi il percorso di
ingest crea quello che gli serve invece di rifiutare la lettura
(`meshbee_core/services/ingest.py`):

1. Il nodo viene registrato se non è già noto (`Nodo <id_nodo>`), **non assegnato**:
   nessuno lo possiede finché un admin non lo assegna, e fino ad allora lo vedono solo
   gli admin.
2. Con un `id_sensore`: viene usata l'arnia corrispondente, oppure **ne viene creata una
   nuova** (`Arnia <id_nodo>-<id_sensore>`) — nell'apiario `Default` del proprietario del
   nodo, o non assegnata come il suo nodo.
3. Senza `id_sensore`: viene usata la **prima** arnia del nodo.
4. Se il nodo non ha nessuna arnia e non ha mandato un `id_sensore`, la lettura viene
   scartata con `NotFound` — sollevando un'eccezione invece di uscire in silenzio,
   perché la sessione del chiamante fa commit su un'uscita pulita e un return silenzioso
   lascerebbe dietro la registrazione del nodo appena fatta.

**`POST /api/admin/letture` volutamente non fa niente di tutto questo** — risponde 404
per un'arnia sconosciuta. Il provisioning è una proprietà del percorso di ingest, non
del livello condiviso. Tutto quello che invece deve restare identico fra i due percorsi
è fissato da `tests/integration/test_ingest_parity.py`, che confronta ogni colonna
tranne `id_lettura`.

## Configurazione

`Settings` estende `CoreSettings` (i campi del database — vedi
[`meshbee_core/`](../meshbee_core/README.it.md#configurazione)) con:

| Variabile | Default | Valore da compose |
|---|---|---|
| `MQTT_BROKER` | `localhost` | `mosquitto` |
| `MQTT_PORT` | `1883` | `1883` |
| `MQTT_TOPIC` | `beehive/+/data` | `beehive/+/data` |
| `MQTT_CLIENT_ID` | `beehive-mqtt-handler` | — |
| `MQTT_USER` | assente | `${MQTT_USER:-beehive}` |
| `MQTT_PASSWORD` | assente | `${MQTT_PASSWORD}` |

Le credenziali vengono inviate solo se ci sono **entrambe**; se ne manca una il client
si connette in anonimo, cosa che il broker rifiuta (`allow_anonymous false`). La
password deve corrispondere all'hash in `mosquitto/config/passwd` — rigeneralo con
`make mqtt-passwd` ogni volta che cambi `MQTT_PASSWORD`.

## Sviluppo

**Non c'è hot reload.** Modificare un file qui non cambia niente finché il processo non
riparte — è il modo più comune di passare dieci minuti a fare debug di codice che non è
in esecuzione:

```bash
docker-compose restart mqtt-handler        # oppure: make restart-mqtt
docker-compose logs -f mqtt-handler        # oppure: make logs-mqtt
```

Pubblica una lettura di prova da dentro il container del broker, così non serve
installare nessun client:

```bash
set -a; . ./.env; set +a
docker-compose exec -T mosquitto mosquitto_pub \
  -h localhost -u "$MQTT_USER" -P "$MQTT_PASSWORD" \
  -t beehive/NODE001/data \
  -m '{"id_sensore":"SENSOR01","temperatura":34.5,"umidita":65,"peso":42.35,"bat":4.01}'
```

L'handler logga una riga per ogni lettura archiviata. Verifica che sia arrivata:

```bash
docker-compose exec postgres psql -U beehive_user -d beehive_iot \
  -c 'SELECT id_lettura, id_arnia, timestamp, temperatura, batteria FROM letture ORDER BY id_lettura DESC LIMIT 3;'
```

I test stanno in `tests/unit/mqtt_handler/` (decodifica del payload e contratto, senza
broker) e in `tests/integration/test_ingest_parity.py` — vedi
[`tests/`](../tests/README.it.md).

## Trappole

- **Niente hot reload** — `docker-compose restart mqtt-handler` dopo ogni modifica.
- **Una lettura rifiutata viene scartata, non ritentata.** Un `CoreError` viene loggato
  come `Lettura scartata` senza traceback e il messaggio è perso: il broker ha ricevuto
  la sua conferma prima ancora che l'handler guardasse il payload. Non c'è nessuna coda
  di messaggi morti.
- **`beehive/+/data` copre esattamente un livello** — vedi [Il topic](#il-topic).
- **`contract.py` è documentazione, non validazione.** Modificarlo non cambia nessun
  comportamento; modificare `payload.py` non cambia nessun contratto. Cambiare la forma
  del payload è entrambe le cose, più `make mqtt-schema`.
- **Tutti i nodi condividono una sola credenziale.** Un nodo compromesso non si può
  revocare singolarmente, e qualsiasi account autenticato può pubblicare su qualsiasi
  topic (nessuna ACL). Vedi [`mosquitto/`](../mosquitto/README.it.md).
- **Qui il pool è di 10 connessioni**, contro le 20 dell'API — un processo che consuma
  un messaggio alla volta non ne ha bisogno di più.

## Collegamenti

- [`mosquitto/`](../mosquitto/README.it.md) — il broker: credenziali, persistenza, ACL.
- [`meshbee_core/`](../meshbee_core/README.it.md) — `services/ingest.py`, dove la lettura viene scritta davvero.
- [`api/`](../api/README.it.md) — l'altro scrittore, e `POST /api/admin/letture`.
- [`database/`](../database/README.it.md) — `letture`, `nodi`, `arnie`, e perché non c'è un trigger.
- [Il contratto pubblicato](https://fablab-imperia.github.io/meshbee/contract/mqtt-payload/) — lo stesso payload, documentato per il firmware e per l'app.
- [README](../README.it.md) principale — lo stack nel suo insieme.
