# 🐝 Meshbee Backend

[![Ultima release](https://img.shields.io/github/v/release/fablab-imperia/meshbee-server?sort=semver)](https://github.com/fablab-imperia/meshbee-server/releases/latest)

*[English version](README.md)*

Questo è il codice del **backend** del [progetto Meshbee](https://github.com/fablab-imperia/meshbee). Implementa l'API REST FastAPI, l'handler MQTT, il broker Mosquitto e PostgreSQL, tramite Docker Compose.

Le altre parti del progetto Meshbee:

| Repository | Cos'è |
|---|---|
| **[meshbee](https://github.com/fablab-imperia/meshbee)**  | Repo ombrello: documentazione, architettura e contratto MQTT/API versionato. |
| **[meshbee-firmware](https://github.com/fablab-imperia/meshbee-firmware)** | Firmware ESP32 per i nodi sensore e gateway (Meshtastic + MQTT). |
| **[meshbee-server](https://github.com/fablab-imperia/meshbee-server)** (questo) | Backend: API REST FastAPI, handler MQTT, broker Mosquitto e PostgreSQL, tramite Docker Compose. |
| **[meshbee-app](https://github.com/fablab-imperia/meshbee-app)** | App mobile in React Native / Expo — dashboard, grafici e notifiche push. |
| **[meshbee-hardware](https://github.com/fablab-imperia/meshbee-hardware)** | Progettazione hardware: schemi PCB e contenitori stampati in 3D. |

📖 **Documentazione:** <https://fablab-imperia.github.io/meshbee/>

🛠️ **Realizzato da:** [Fablab Imperia APS](https://www.fablabimperia.org)

## Indice

- [Panoramica](#panoramica)
- [Come stanno insieme](#come-stanno-insieme)
- [Requisiti](#requisiti)
- [Installazione](#installazione)
- [Configurazione](#configurazione)
- [Sviluppo](#sviluppo)
- [Troubleshooting](#troubleshooting)
- [Licenza](#licenza)
- [Versioning e contributi](#versioning-e-contributi)

## Panoramica

La parte server di Meshbee: riceve le letture delle arnie via MQTT, le archivia e le
serve all'app mobile tramite un'API REST.

Cosa fa:

- **Riceve** le letture via MQTT, registrando al volo nodi e arnie sconosciuti.
- **Archivia** in PostgreSQL, con i limiti delle misure verificati due volte —
  nell'applicazione e nello schema.
- **Espone** un'API REST con autenticazione JWT, permessi per singola arnia ed endpoint
  storici dimensionati per i grafici.
- **Registra** il lavoro dell'apicoltore: ispezioni, trattamenti, raccolte.
- Gira interamente in Docker Compose.

Chi produce le letture e chi le consuma sono documentati nei rispettivi repository —
vedi [Come stanno insieme](#come-stanno-insieme).

## Come stanno insieme

Tutto quello che ha una barra finale è una directory di **questo** repository; i due
capi della catena vivono in repository fratelli.

```
nodi ESP32 ──MQTT──▶ mosquitto/ ──▶ mqtt_handler/ ──┐
                                                    │
                                                    ├──▶ meshbee_core/ ──▶ database/
                                                    │
app mobile ──HTTPS──▶ caddy/ ─────▶ api/ ───────────┘
```

| Nel diagramma | Cos'è | Dove vive |
|---|---|---|
| nodi ESP32 | Nodi sensore e gateway. Pubblicano le letture su `beehive/<id_nodo>/data`. | [meshbee-firmware](https://github.com/fablab-imperia/meshbee-firmware) |
| `mosquitto/` | Configurazione e stato del broker MQTT. Immagine standard, nessun codice nostro. | [mosquitto/](mosquitto/README.it.md) |
| `mqtt_handler/` | Si sottoscrive al broker, decodifica il payload, archivia la lettura. | [mqtt_handler/](mqtt_handler/README.it.md) |
| `caddy/` | Reverse proxy che termina l'HTTPS su `:8443` davanti all'API. Opzionale. | [HTTPS locale](#https-locale) |
| `api/` | L'API REST FastAPI. L'unico pezzo con cui parla l'app. | [api/](api/README.it.md) |
| `meshbee_core/` | La libreria condivisa che entrambi gli entry point importano: schemi, service e tutto l'SQL. | [meshbee_core/](meshbee_core/README.it.md) |
| `database/` | Documentazione dello schema PostgreSQL, che `meshbee_core/models.py` definisce e Alembic applica. | [database/](database/README.it.md) |
| app mobile | Dashboard, grafici e avvisi. Consuma l'API REST. | [meshbee-app](https://github.com/fablab-imperia/meshbee-app) |

Due directory non stanno su quel percorso: [`tests/`](tests/README.it.md), l'unica suite
pytest che copre tutto, e `scripts/`, i job one-shot — `migrate.py` porta lo schema
all'ultima revisione, `seed.py` crea gli account iniziali, `export_openapi.py` ed `export_mqtt_schema.py` rigenerano i due artefatti del
contratto.

> L'architettura dell'**intero** progetto Meshbee, questo repository compreso, è
> documentata su <https://fablab-imperia.github.io/meshbee/architecture/>.

Due fatti spiegano quasi tutta la struttura.

**Due processi, una libreria.** `api` e `mqtt-handler` sono container separati con cicli
di vita separati — riavviare il broker non tocca l'API REST, e l'API non è un client
MQTT. Ma scrivono sullo stesso database, quindi devono essere d'accordo su cosa sia una
lettura valida e su come archiviarla. Quell'accordo è `meshbee_core`: una libreria,
importata da entrambi, mai deployata da sola. `tests/integration/test_ingest_parity.py`
dimostra che i due percorsi producono righe identiche.

**Tre livelli, una direzione.** L'SQL sta in `meshbee_core/repository/`; le decisioni
stanno in `meshbee_core/services/`, che sollevano i propri errori e non sanno nulla di
HTTP; gli entry point validano l'input, chiamano *un solo* service e traducono il
risultato in uno status code o in una riga di log. La logica nuova va in un service,
l'SQL nuovo in un repository, e una rotta nuova è una chiamata sottile a un service che
esiste già. **Se compare dell'SQL in `api/`, `mqtt_handler/` o `scripts/`, è finito nel
posto sbagliato.**

Porte:

| Porta | Servizio | Note |
|---|---|---|
| 8000 | `api` | HTTP. `/docs`, `/redoc`, `/openapi.json`. |
| 8443 | `caddy` | HTTPS. Solo dopo `make certs`. Si cambia con `HTTPS_PORT`. |
| 1883 | `mosquitto` | MQTT. Autenticazione obbligatoria. |
| 9001 | `mosquitto` | MQTT su WebSocket. Configurata ma non usata. |
| 5432 | `postgres` | Esposta per `psql` e i client grafici. |

## Requisiti

Docker e Docker Compose. Opzionalmente git e
[mkcert](https://github.com/FiloSottile/mkcert) se vuoi l'HTTPS locale.

## Installazione

```bash
git clone https://github.com/fablab-imperia/meshbee-server.git
cd meshbee-server
cp .env.example .env
```

**1. Compila il `.env`.** Ogni valore è una credenziale e vanno cambiate tutte:

```bash
POSTGRES_PASSWORD=...      # database
JWT_SECRET_KEY=...         # firma dei token — openssl rand -hex 32
MQTT_PASSWORD=...          # broker
ADMIN_PASSWORD=...         # admin@beehive.local, creato al primo avvio
USER_PASSWORD=...          # utente@test.local, creato al primo avvio
```

`ADMIN_PASSWORD` e `USER_PASSWORD` sono **obbligatorie e di almeno 8 caratteri**. Se ne
manca una il servizio `seed` si ferma con un errore esplicito, invece di creare un
account amministratore funzionante con password vuota.

**2. Genera il file password del broker.** Il broker gira con `allow_anonymous false`,
quindi **senza questo passo Mosquitto non parte**:

```bash
make mqtt-passwd
```

Rieseguilo ogni volta che cambi `MQTT_PASSWORD` — il file contiene un hash, quindi non
segue la variabile.

**3. (Opzionale) Abilita l'HTTPS.** Richiede mkcert; gira sull'host e tocca il trust
store di sistema:

```bash
make certs
```

Se lo salti, Caddy stampa un avviso ed esce con 0. Il resto dello stack, e l'HTTP su
`:8000`, continuano a funzionare.

**4. Avvia.**

```bash
docker-compose up -d       # oppure: make start
docker-compose ps
```

> **Scorciatoia:** `make setup` esegue in sequenza la copia del `.env`,
> `make mqtt-passwd` e l'avvio. Non genera i certificati.

**5. Verifica.**

- HTTP: <http://localhost:8000/docs>
- HTTPS: <https://localhost:8443/docs> (solo dopo `make certs`)

```bash
curl -s localhost:8000/health | python3 -m json.tool
```

> `meshbee-migrate` applica le migrazioni dello schema e `meshbee-seed` crea gli account
> iniziali; poi entrambi terminano. Vederli come **`Exited (0)` è normale**: sono job
> one-shot, non servizi andati in crash.

Su un database nuovo trovi i due account qui sopra, un nodo di esempio con due arnie e
qualche lettura. **Cambia quelle password prima di esporre qualsiasi cosa.**

## Configurazione

Tutto sta nel `.env`. Compose passa i valori ai servizi come variabili d'ambiente, che
hanno la precedenza sul file — il `.env` viene letto direttamente solo quando esegui un
processo fuori da Docker.

| Variabile | Usata da | Note |
|---|---|---|
| `POSTGRES_PASSWORD` | postgres, migrate, api, mqtt-handler, seed | Arriva anche come `DB_PASSWORD`. **Applicata solo su un volume nuovo.** |
| `JWT_SECRET_KEY` | api | Firma dei token. Cambiarla invalida tutti i token emessi. |
| `MQTT_USER` | mosquitto, mqtt-handler | Default `beehive`. |
| `MQTT_PASSWORD` | mosquitto, mqtt-handler | Deve corrispondere a `mosquitto/config/passwd`. |
| `ADMIN_PASSWORD` | seed | ≥ 8 caratteri. |
| `USER_PASSWORD` | seed | ≥ 8 caratteri. |
| `HTTPS_PORT` | caddy | Porta host per l'HTTPS. Default `8443`. |

Le impostazioni sono **divise per servizio**: `CoreSettings` in
`meshbee_core/config.py` tiene i campi del database, e ogni entry point la estende con i
propri — JWT e CORS per l'API, `MQTT_*` per l'handler, le due password iniziali per il
seed. Il README di ogni componente elenca i suoi campi.

**Metti un campo nuovo nella classe più stretta che ne ha bisogno.** Un campo
obbligatorio su `CoreSettings` deve esistere nell'ambiente di *ogni* servizio in
`docker-compose.yml`, altrimenti quel servizio va in crash all'import.

## Sviluppo

Il container `api` esegue uvicorn con `--reload` e `api/`, `meshbee_core/` e `tests/`
sono montati in bind, quindi basta modificare un file. **L'handler MQTT non ha hot
reload** e va riavviato:

```bash
docker-compose logs -f                       # tutto (make logs)
docker-compose logs -f api                   # make logs-api
docker-compose restart mqtt-handler          # make restart-mqtt — dopo ogni modifica lì
docker-compose exec postgres psql -U beehive_user -d beehive_iot     # make db-shell
```

**I test** girano nel container, sempre — `config.py` costruisce le `Settings`
all'import, quindi sull'host fallisce già la collection:

```bash
docker-compose --profile test up -d postgres-test    # una volta per avvio della macchina
docker-compose exec api pytest                       # make test
docker-compose exec api pytest -m "not integration"  # senza database
```

Vedi [`tests/README.it.md`](tests/README.it.md) per i due livelli, le fixture e dove va
un test nuovo.

**Dopo aver cambiato una rotta, uno schema o la forma del payload**, rigenera gli
artefatti del contratto committati:

```bash
docker-compose exec api python -m scripts.export_openapi        # make openapi
docker-compose exec api python -m scripts.export_mqtt_schema    # make mqtt-schema
make contract                                                   # entrambi in un colpo
```

`api/openapi.json` e `mqtt_handler/mqtt-payload.schema.json` sono quelli che
referenziano il
[contratto](https://github.com/fablab-imperia/meshbee/blob/main/docs/contract/index.md)
del repo ombrello e l'app mobile. Non li rigenera niente in automatico; `pytest`
fallisce se lo schema MQTT è vecchio, ma `openapi.json` non lo controlla nessuno. Un
endpoint nuovo richiede anche una riga nella tabella di autorizzazione in
`tests/integration/api/test_main_authz.py`.

**Pubblica una lettura di prova** senza installare nessun client:

```bash
set -a; . ./.env; set +a
docker-compose exec -T mosquitto mosquitto_pub \
  -h localhost -u "$MQTT_USER" -P "$MQTT_PASSWORD" \
  -t beehive/NODE001/data \
  -m '{"id_sensore":"SENSOR01","temperatura":34.5,"umidita":65,"peso":42.35}'
```

**Backup:**

```bash
make db-backup                                          # → backups/backup_<timestamp>.sql
make db-restore FILE=backups/backup_20260805_120000.sql
```

**Spegnere:** `docker-compose stop` mette in pausa; `docker-compose down`
(`make clean`) rimuove i container e **mantiene i dati**; `make clean-all` esegue
`down -v` e **distrugge il database**.

### HTTPS locale

In `caddy/` c'è un reverse proxy Caddy che termina il TLS su `:8443` e inoltra a
`api:8000`, con un certificato emesso da
[mkcert](https://github.com/FiloSottile/mkcert) e considerato attendibile dalla tua
macchina. Serve a sviluppare l'app mobile contro `https://` senza avvisi sul
certificato.

`make certs` gira sull'**host** (mkcert installa una CA locale nel trust store) e scrive
in `caddy/certs/`, che è gitignorato. Senza quei file Caddy stampa come crearli ed esce
con 0, così lo stack parte lo stesso.

## Troubleshooting

**Mosquitto non parte / si riavvia in loop.** Quasi sempre manca il file password — è
gitignorato, quindi un clone nuovo non ce l'ha mai. Esegui `make mqtt-passwd`, poi
`docker-compose logs mosquitto`. Stessa cosa se hai cambiato `MQTT_PASSWORD` senza
rigenerarlo.

**`api` e `mqtt-handler` non partono mai; `meshbee-migrate` è uscito con 1.** Leggi
`docker-compose logs migrate`. "no alembic_version" indica un database creato prima di
Alembic: marcalo una volta, come descritto in
[`database/README.it.md`](database/README.it.md#installazioni-esistenti).

**Una modifica alla password non ha avuto effetto.** `POSTGRES_PASSWORD` viene applicata
**solo quando la directory dati è vuota**, e `postgres_data` sopravvive a
`docker-compose down`, alle ricostruzioni e ai riavvii. O `docker-compose down -v` (che
**distrugge tutte le letture**) oppure cambiala dentro PostgreSQL. Le modifiche allo
schema sono un'altra cosa: passano da una migrazione — vedi
[`database/README.it.md`](database/README.it.md#cambiare-lo-schema).

**`meshbee-migrate` o `meshbee-seed` risulta `Exited (0)`.** È normale: sono job one-shot.

**`seed` esce con 1 e "Configurazione non valida".** `ADMIN_PASSWORD` o
`USER_PASSWORD` manca o è più corta di 8 caratteri. Correggi il `.env`, poi
`docker-compose up -d seed`.

**Le letture non arrivano mai.** Nell'ordine: il broker è su
(`docker-compose logs mosquitto`); l'handler è connesso e autenticato
(`docker-compose logs -f mqtt-handler`); il nodo pubblica su `beehive/<id>/data` e non
su un topic più profondo — la sottoscrizione è `beehive/+/data`, che copre esattamente
un livello. Poi controlla il payload rispetto a
[`mqtt_handler/README.it.md`](mqtt_handler/README.it.md#payload): una misura fuori
range viene scartata e loggata come `Lettura scartata`.

**Le modifiche in `mqtt_handler/` non hanno effetto.** Non c'è hot reload:
`docker-compose restart mqtt-handler`.

**Tutto il livello di integrazione non riesce a connettersi.** `postgres-test` sta
dietro un profilo compose e non parte con un semplice `up`:
`docker-compose --profile test up -d postgres-test`.

**`/health` risponde `unhealthy`.** L'API è su ma il database non è raggiungibile. Il
corpo della risposta contiene l'errore; `/health` risponde volutamente 200 in entrambi i
casi, quindi il monitoraggio deve leggere il corpo.

## Licenza

Distribuito con licenza **AGPL-3.0**. Vedi [LICENSE](LICENSE).

## Versioning e contributi

Le release seguono il versionamento semantico; il tag dell'
[ultima release](https://github.com/fablab-imperia/meshbee-server/releases/latest) è
quello da deployare. La compatibilità fra i repository del progetto è tracciata nel repo
ombrello:
[matrice di compatibilità](https://fablab-imperia.github.io/meshbee/contract/compatibility/).

Le release le crea [release-please](https://github.com/googleapis/release-please)
(`.github/workflows/release-please.yml`). A ogni push su `main` apre o aggiorna una
**PR di release** che sceglie la versione successiva dai tipi di commit — `fix:` →
patch, `feat:` → minor, `!` o `BREAKING CHANGE:` → major — e la scrive in
`API_VERSION` in `api/config.py`, in `info.version` in `api/openapi.json`, nella
versione di `pyproject.toml` e in una nuova voce di `CHANGELOG.md`. Il merge di quella
PR crea il tag (`1.3.0`, senza `v`) e la release su GitHub. Quindi:

- **Non aggiornare la versione né creare tag a mano.** Fai il merge della PR di release
  quando vuoi pubblicare.
- **Fai lo squash-merge delle PR**, così il titolo della PR diventa l'unico commit che
  release-please legge. Un merge commit normale viene ignorato, e un titolo che non è
  un Conventional Commit resta fuori dal changelog.
- **Per scegliere tu la versione**, metti `Release-As: 2.0.0` nel corpo di un commit.

Ogni pull request esegue tre controlli, che devono passare tutti prima del merge:

- **`ci / test`**: l'intera suite di test su un PostgreSQL usa e getta
  ([dettagli](tests/README.it.md#esecuzione)). Comprende i controlli che
  `api/openapi.json` e `mqtt_handler/mqtt-payload.schema.json` committati
  corrispondano al codice.
- **`ci / images`**: entrambe le immagini Docker si costruiscono ancora.
- **`pr-title`**: il titolo della PR è un Conventional Commit, perché diventa il
  commit squashato che release-please legge.

Dependabot (`.github/dependabot.yml`) apre ogni settimana PR per i pacchetti Python,
le immagini di base e le GitHub Actions fissate a un commit.

I contributi sono benvenuti — vedi il
[CONTRIBUTING](https://github.com/fablab-imperia/.github/blob/main/CONTRIBUTING.md)
dell'organizzazione. I commit seguono i
[Conventional Commits](https://www.conventionalcommits.org/). La documentazione è
bilingue: l'inglese è la versione canonica (`README.md`), l'italiano è la traduzione
(`README.it.md`), e le due si mantengono allineate.

## Supporto

Apri una [issue](https://github.com/fablab-imperia/meshbee-server/issues), oppure scrivi
a [Fablab Imperia APS](https://www.fablabimperia.org).
