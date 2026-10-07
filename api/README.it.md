# `api/` — API REST

*[English version](README.md)*

L'**entry point FastAPI**: la faccia HTTP del backend, e l'unico pezzo con cui parla
l'app mobile. Gira sotto uvicorn sulla porta **8000**, con `--reload` in sviluppo, e
legge e scrive lo stesso database PostgreSQL su cui scrive l'handler MQTT — attraverso
la stessa logica condivisa in [`meshbee_core/`](../meshbee_core/README.it.md).

È volutamente **sottile**: ogni handler valida l'input, apre una sessione, chiama *un
solo* service e traduce il risultato in uno status code. Qui non c'è SQL.

## Contenuto

| Percorso | Cos'è |
|---|---|
| `main.py` | L'applicazione: lifespan, CORS, traduzione degli errori e tutte le 37 rotte. |
| `auth.py` | Emissione e verifica dei JWT, e le dipendenze FastAPI che proteggono le rotte. |
| `config.py` | `Settings(CoreSettings)` — JWT, metadati dell'API e CORS sopra ai campi del database. |
| `openapi.json` | Il contratto API generato. **Committato** — vedi [Contratto OpenAPI](#contratto-openapi). |
| `Dockerfile` | Immagine del servizio `api` (e di `seed`). Il contesto di build è la root del repo. |
| `requirements.txt` | Dipendenze di runtime. |
| `requirements-dev.txt` | Dipendenze di test — nella stessa immagine, così un solo container esegue la suite. |

## Endpoint

37 operazioni. La colonna `Auth` dice cosa deve portare una richiesta:

- **nessuna** — pubblico.
- **utente** — un bearer token valido di un account attivo (`get_current_active_user`).
- **admin** — quanto sopra *più* `ruolo = 'admin'` (`get_current_admin_user`).
- **utente + `read`/`write`** — quanto sopra *più* quel permesso su quella specifica
  arnia. Gli admin passano il controllo comunque.

### Autenticazione

| Metodo | Percorso | Auth | Scopo |
|---|---|---|---|
| POST | `/api/auth/login` | nessuna | Scambia email + password per un access e un refresh token. |
| GET | `/api/auth/me` | utente | L'account autenticato. |

### Utente

Tutto quello sotto `/api/user/arnie/{id_arnia}` è protetto su quell'arnia.

| Metodo | Percorso | Auth | Scopo |
|---|---|---|---|
| GET | `/api/user/arnie` | utente | Le arnie visibili al chiamante, ciascuna con l'ultima lettura. |
| GET | `/api/user/arnie/{id_arnia}` | utente + `read` | Una singola arnia con l'ultima lettura. |
| PUT | `/api/user/arnie/{id_arnia}` | utente + `write` | Rinomina/sposta un'arnia. **Non** può cambiare `attiva`. |
| GET | `/api/user/arnie/{id_arnia}/letture` | utente + `read` | Letture. `data_inizio`, `data_fine`, `limit` (1–10000, default 1000). |
| GET | `/api/user/arnie/{id_arnia}/letture/temperatura` | utente + `read` | Solo `{timestamp, temperatura}` — dimensionato per i grafici. |
| GET | `/api/user/arnie/{id_arnia}/letture/umidita` | utente + `read` | Solo `{timestamp, umidita}`. |
| GET | `/api/user/arnie/{id_arnia}/letture/peso` | utente + `read` | Solo `{timestamp, peso}`. |
| GET | `/api/user/arnie/{id_arnia}/letture/batteria` | utente + `read` | Solo `{timestamp, batteria}` — tensione della batteria del nodo. |
| GET | `/api/user/arnie/{id_arnia}/attivita` | utente + `read` | Log attività. `data_inizio`, `data_fine`, `tipo_attivita`, `limit` (1–1000, default 100). |
| POST | `/api/user/arnie/{id_arnia}/attivita` | utente + `write` | Registra un'attività. |
| PATCH | `/api/user/arnie/{id_arnia}/attivita/{id_log}` | utente + `write` | Modifica un'attività — **solo le proprie**. |
| DELETE | `/api/user/arnie/{id_arnia}/attivita/{id_log}` | utente + `write` | Elimina un'attività — **solo le proprie**. |
| PUT | `/api/user/password` | utente | Cambia la propria password. Richiede `current_password`. |

I quattro endpoint di serie esistono perché a un grafico servono due colonne su una riga di
nove; scartano le righe in cui il campo è NULL. L'elenco dei campi accettati è una
whitelist in `meshbee_core/repository/letture.py`, non un'interpolazione di stringhe.

### Admin

| Metodo | Percorso | Auth | Scopo |
|---|---|---|---|
| GET | `/api/admin/utenti` | admin | Tutti gli account. |
| POST | `/api/admin/utenti` | admin | Crea un account. |
| PUT | `/api/admin/utenti/{id_utente}` | admin | Aggiorna un account. |
| DELETE | `/api/admin/utenti/{id_utente}` | admin | Disattiva (soft delete). **Non puoi disattivare te stesso.** |
| PUT | `/api/admin/utenti/{id_utente}/password` | admin | Reimposta la password di qualcuno — senza `current_password`. |
| POST | `/api/admin/utenti-arnie` | admin | Dà a un utente accesso a un'arnia a un certo livello. |
| DELETE | `/api/admin/utenti-arnie` | admin | Lo revoca. **`id_utente` e `id_arnia` sono query parameter**, non un body. |
| GET | `/api/admin/nodi` | admin | Tutti i nodi. |
| POST | `/api/admin/nodi` | admin | Registra un nodo. |
| GET | `/api/admin/nodi/{id_nodo}` | admin | Un singolo nodo. |
| PUT | `/api/admin/nodi/{id_nodo}` | admin | Aggiorna un nodo (il body è un `NodoCreate` completo). |
| DELETE | `/api/admin/nodi/{id_nodo}` | admin | Disattiva. Arnie e letture restano. |
| GET | `/api/admin/arnie` | admin | Tutte le arnie, comprese quelle dismesse. |
| POST | `/api/admin/arnie` | admin | Crea un'arnia. |
| GET | `/api/admin/arnie/{id_arnia}` | admin | Una singola arnia con l'ultima lettura. |
| PUT | `/api/admin/arnie/{id_arnia}` | admin | Aggiorna un'arnia — **`attiva` compresa**, a differenza della rotta utente. |
| DELETE | `/api/admin/arnie/{id_arnia}` | admin | Disattiva. Le letture storiche restano. |
| GET | `/api/admin/letture` | admin | Tutte le letture. `limit` 1–10000, default 1000. |
| POST | `/api/admin/letture` | admin | Inserisce una lettura a mano — backfill e test. |
| GET | `/api/admin/attivita` | admin | Tutte le attività. `limit` 1–1000, default 100. |

`POST /api/admin/letture` e il percorso MQTT finiscono nella stessa INSERT, ma **non**
si comportano allo stesso modo sui riferimenti sconosciuti: questa rotta risponde
**404** per un'arnia inesistente, mentre il percorso di ingest registra nodo e arnia al
volo. La differenza è voluta ed è documentata in
[`mqtt_handler/README.it.md`](../mqtt_handler/README.it.md#auto-provisioning); tutto
quello che invece deve restare identico è fissato da
`tests/integration/test_ingest_parity.py`.

### Info

| Metodo | Percorso | Auth | Scopo |
|---|---|---|---|
| GET | `/` | nessuna | Nome, versione e URL della documentazione. |
| GET | `/health` | nessuna | Verifica il database. |

`/health` **risponde sempre 200** — il verdetto sta nel corpo (`"status": "healthy"` /
`"unhealthy"`), mai il motivo: quello finisce nel log dell'API. Un sistema di monitoraggio deve leggere il corpo, non lo status code.

## Autenticazione e autorizzazione

Il login restituisce due JWT firmati HS256 con `JWT_SECRET_KEY`. Il claim che
identifica il chiamante è `sub` (l'email); la riga dell'utente viene riletta dal
database a **ogni** richiesta, quindi disattivare un account ha effetto immediato senza
aspettare la scadenza del token.

Le dipendenze si impilano, ciascuna sopra la precedente:

| Dipendenza | Rifiuta con | Quando |
|---|---|---|
| `get_current_user` | **401** + `WWW-Authenticate: Bearer` | Header assente, token malformato, firma errata, scaduto, `type != "access"`, o email sconosciuta. |
| `get_current_active_user` | **400** `Utente non attivo` | L'account esiste ma `attivo` è falso. |
| `get_current_admin_user` | **403** `Permessi insufficienti - richiesto ruolo admin` | L'account non è admin. |
| `check_user_arnia_access` | **403** | Nessuna associazione con quell'arnia al livello richiesto. |

`HTTPBearer(auto_error=False)` è voluto. Lasciato al default, FastAPI risponde a un
header *mancante* con un 403 secco e senza `WWW-Authenticate`; disattivandolo la
richiesta arriva a `get_current_user`, che restituisce il **401** corretto. La
distinzione che l'API mantiene è: **401 significa "chi sei?", 403 significa "so chi sei,
e no"**.

I permessi per arnia sono una scala — `read` < `write` < `admin` — confrontata
numericamente in `meshbee_core/services/auth.py`. Un account con `ruolo = 'admin'`
scavalca del tutto la tabella delle associazioni. Un nome di permesso non riconosciuto
solleva un'eccezione invece di restituire False, così un errore di battitura fallisce in
chiusura.

Due cose da sapere sui token:

- **Il refresh token viene emesso ma non viene mai riscattato.** Non esiste una rotta
  `/api/auth/refresh`, e niente legge o scrive la tabella `token_sessione`. Quando
  l'access token scade dopo `ACCESS_TOKEN_EXPIRE_MINUTES`, il client rifà il login. La
  tabella resta perché ha la forma giusta per la funzionalità:
  [issue #16](https://github.com/fablab-imperia/meshbee-server/issues/16).
- **Un database irraggiungibile non è un errore di credenziali.** `authenticate_user`
  trasforma qualsiasi `SQLAlchemyError` in **503** invece di lasciarla arrivare al 401,
  così un database giù non somiglia mai a una password sbagliata.

Il login risponde con lo stesso 401 per email sconosciuta, password sbagliata e account
disattivato — una sola risposta per ogni modo di fallire, così l'endpoint non può essere
usato per enumerare le email registrate.

## Traduzione degli errori

I service sollevano il vocabolario di `meshbee_core.errors` e non sanno nulla di HTTP.
Il context manager `db_operation` in `main.py` è l'unico punto in cui i due vocabolari
si incontrano:

| Sollevato | Diventa |
|---|---|
| `NotFound` | 404 |
| `Conflict` | 409 |
| `InvalidData` | 400 |
| `SQLAlchemyError` durante il login | 503 |
| qualsiasi altra cosa | 500 `Errore interno del server`, con l'errore vero nel log |

Il corpo del 500 resta volutamente vago: il testo dell'eccezione può nominare tabelle e
colonne.

## Configurazione

`Settings` estende `CoreSettings` (i campi del database — vedi
[`meshbee_core/`](../meshbee_core/README.it.md#configurazione)) con:

| Variabile | Tipo | Default |
|---|---|---|
| `JWT_SECRET_KEY` | secret | **obbligatoria** — `openssl rand -hex 32` |
| `JWT_ALGORITHM` | str | `HS256` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | int | `30` |
| `REFRESH_TOKEN_EXPIRE_DAYS` | int | `7` |
| `API_TITLE` | str | `Beehive IoT API` |
| `API_VERSION` | str | `1.0.0` |
| `API_DESCRIPTION` | str | `API per gestione sistema IoT arnie` |
| `CORS_ORIGINS` | list | `["*"]` |

`CORS_ORIGINS` è una lista, quindi dall'ambiente va passata in **JSON**, non come
stringa separata da virgole:

```bash
CORS_ORIGINS=["https://app.example.org","https://admin.example.org"]
```

`["*"]` con `allow_credentials=True` va bene in sviluppo ed è sbagliato in un
deployment pubblico — lì va ristretta.

## Contratto OpenAPI

FastAPI genera lo schema dal codice, quindi è sempre completo e sempre aggiornato. È
disponibile in tre modi:

| Dove | A cosa serve |
|---|---|
| <http://localhost:8000/docs> | Swagger UI — per provare le richieste, con il pulsante **Authorize** per il bearer token. |
| <http://localhost:8000/redoc> | ReDoc — più comodo da leggere che da cliccare. |
| [`api/openapi.json`](openapi.json) | Il contratto committato, per tutto ciò che non è questo repo. |

Il file committato esiste perché un URL che risolve solo a stack acceso non si può
linkare da un altro repository. È quello che referenzia il
[contratto API](https://github.com/fablab-imperia/meshbee/blob/main/docs/contract/api.md)
del repo ombrello, ed è quello da cui
[`meshbee-app`](https://github.com/fablab-imperia/meshbee-app) può generare un client.

**Rigeneralo ogni volta che aggiungi, togli o cambi una rotta o uno schema** — non lo fa
niente in automatico:

```bash
docker-compose exec api python -m scripts.export_openapi     # oppure: make openapi
```

Deve girare nel container: `api/config.py` costruisce le `Settings` all'import, quindi
sull'host fallisce prima di arrivare allo schema. L'output è ordinato e indentato, così
rigenerare un'API invariata non produce diff.

## Sviluppo

Il container esegue uvicorn con `--reload`, quindi **basta modificare un file qui** —
`api/` è montata in bind. (L'handler MQTT non ha niente del genere; vedi il suo README.)

```bash
docker-compose logs -f api                  # oppure: make logs-api
docker-compose restart api                  # serve solo dopo un cambio di dipendenze
curl -s localhost:8000/health | python3 -m json.tool
```

Un giro completo dalla shell, con l'account creato da `scripts/seed.py`:

```bash
TOKEN=$(curl -s -X POST localhost:8000/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@beehive.local","password":"<ADMIN_PASSWORD dal .env>"}' \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')

curl -s localhost:8000/api/auth/me -H "Authorization: Bearer $TOKEN"
curl -s localhost:8000/api/user/arnie -H "Authorization: Bearer $TOKEN"
```

I test di questo package stanno in `tests/unit/api/` e `tests/integration/api/` — vedi
[`tests/README.it.md`](../tests/README.it.md). **Un endpoint nuovo va aggiunto alla
tabella in `tests/integration/api/test_main_authz.py`**: quella tabella passa in rassegna
ogni rotta per accesso anonimo, non-admin e senza associazione, ed è quello che becca un
controllo dimenticato.

## Trappole

- **Una rotta nuova richiede tre cose dopo**: `make openapi`, una riga nelle tabelle qui
  sopra e una riga in `test_main_authz.py`. Nessuna delle tre succede da sola.
- **L'immagine non contiene solo l'API.** Porta anche `mqtt_handler/`, `scripts/` e
  `tests/` più `paho-mqtt`, così l'intera suite — entrambi gli entry point compresi —
  gira in questo unico container. Per questo il contesto di build è la root del repo e
  non `api/`.
- **Il servizio `seed` usa questa stessa immagine**, con `python -m scripts.seed`.
- **Un `/health` che risponde 200 non dice niente.** Leggi `status` nel corpo.
- **`DELETE /api/admin/utenti-arnie` prende query parameter.** Un body JSON viene
  ignorato, e la richiesta fallisce poi la validazione per i parametri mancanti.

## Collegamenti

- [`meshbee_core/`](../meshbee_core/README.it.md) — i service e gli schemi che ogni handler chiama.
- [`mqtt_handler/`](../mqtt_handler/README.it.md) — l'altro scrittore dello stesso database.
- [`tests/`](../tests/README.it.md) — come eseguire la suite e dove va un test nuovo.
- [`database/`](../database/README.it.md) — le tabelle dietro queste risposte.
- [README](../README.it.md) principale — lo stack nel suo insieme.
