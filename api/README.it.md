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
| `main.py` | L'applicazione: lifespan, CORS, traduzione degli errori e tutte le 51 rotte. |
| `auth.py` | Emissione e verifica dei JWT, e le dipendenze FastAPI che proteggono le rotte. |
| `config.py` | `Settings(CoreSettings)` — JWT, metadati dell'API e CORS sopra ai campi del database. |
| `openapi.json` | Il contratto API generato. **Committato** — vedi [Contratto OpenAPI](#contratto-openapi). |
| `Dockerfile` | Immagine del servizio `api` (e di `seed`). Il contesto di build è la root del repo. |
| `requirements.txt` | Dipendenze di runtime. |
| `requirements-dev.txt` | Dipendenze di test — nella stessa immagine, così un solo container esegue la suite. |

## Endpoint

51 operazioni. La colonna `Auth` dice cosa deve portare una richiesta:

- **nessuna** — pubblico.
- **utente** — un bearer token valido di un account attivo (`get_current_active_user`).
- **admin** — quanto sopra *più* `ruolo = 'admin'` (`get_current_admin_user`).
- **utente + viewer / collaborator / manager / owner** — quanto sopra *più* almeno
  quell'accesso all'apiario dell'arnia (o all'apiario stesso): esserne proprietario, o
  un ruolo condiviso dal proprietario. Vedi
  [Autenticazione e autorizzazione](#autenticazione-e-autorizzazione). Gli admin passano
  il controllo comunque.

### Autenticazione

| Metodo | Percorso | Auth | Scopo |
|---|---|---|---|
| POST | `/api/auth/login` | nessuna | Scambia email + password per un access e un refresh token. |
| GET | `/api/auth/me` | utente | L'account autenticato. |

### Utente

Tutto quello sotto `/api/user/arnie/{id_arnia}` e `/api/user/apiari/{id_apiario}` è protetto
sull'accesso del chiamante all'apiario di quell'arnia, o a quell'apiario.

| Metodo | Percorso | Auth | Scopo |
|---|---|---|---|
| GET | `/api/user/arnie` | utente | Le arnie degli apiari di cui il chiamante è proprietario o che gli sono condivisi, ciascuna con l'ultima lettura, il suo apiario e `accesso` (l'accesso del chiamante). `id_apiario` opzionale la restringe a un apiario. |
| GET | `/api/user/arnie/{id_arnia}` | utente + viewer | Una singola arnia con l'ultima lettura. |
| PUT | `/api/user/arnie/{id_arnia}` | utente + manager | Rinomina/riposiziona un'arnia. `attiva` (dismetterla) vale solo per il proprietario. |
| PUT | `/api/user/arnie/{id_arnia}/apiario` | utente + owner | Sposta l'arnia in un altro apiario del suo proprietario. Chi può vederla segue l'apiario. |
| GET | `/api/user/arnie/{id_arnia}/letture` | utente + viewer | Letture. `data_inizio`, `data_fine`, `limit` (1–10000, default 1000). |
| GET | `/api/user/arnie/{id_arnia}/letture/temperatura` | utente + viewer | Solo `{timestamp, temperatura}` — dimensionato per i grafici. |
| GET | `/api/user/arnie/{id_arnia}/letture/umidita` | utente + viewer | Solo `{timestamp, umidita}`. |
| GET | `/api/user/arnie/{id_arnia}/letture/peso` | utente + viewer | Solo `{timestamp, peso}`. |
| GET | `/api/user/arnie/{id_arnia}/letture/batteria` | utente + viewer | Solo `{timestamp, batteria}` — tensione della batteria del nodo. |
| GET | `/api/user/arnie/{id_arnia}/attivita` | utente + viewer | Log attività. `data_inizio`, `data_fine`, `tipo_attivita`, `limit` (1–1000, default 100). |
| POST | `/api/user/arnie/{id_arnia}/attivita` | utente + collaborator | Registra un'attività. |
| PATCH | `/api/user/arnie/{id_arnia}/attivita/{id_log}` | utente + collaborator | Modifica un'attività — **solo le proprie**. |
| DELETE | `/api/user/arnie/{id_arnia}/attivita/{id_log}` | utente + collaborator | Elimina un'attività — **solo le proprie**. |
| PUT | `/api/user/password` | utente | Cambia la propria password. Richiede `current_password`. |
| GET | `/api/user/apiari` | utente | Gli apiari di cui il chiamante è proprietario (prima quello predefinito), poi quelli condivisi con lui, ciascuno con `accesso`. |
| POST | `/api/user/apiari` | utente | Crea un apiario del chiamante. |
| GET | `/api/user/apiari/{id_apiario}` | utente + viewer | Un singolo apiario. |
| PUT | `/api/user/apiari/{id_apiario}` | utente + manager | Lo modifica — anche quello predefinito. |
| DELETE | `/api/user/apiari/{id_apiario}` | utente + owner | Lo elimina, con le sue condivisioni. **409** per quello predefinito, e finché contiene arnie attive. |
| GET | `/api/user/apiari/{id_apiario}/condivisioni` | utente + owner | Con chi è condiviso, e con quale ruolo. |
| POST | `/api/user/apiari/{id_apiario}/condivisioni` | utente + owner | Lo condivide con un utente, tramite `email`, come `viewer` (default), `collaborator` o `manager`. Condividerlo di nuovo cambia il ruolo. |
| PUT | `/api/user/apiari/{id_apiario}/condivisioni/{id_utente}` | utente + owner | Cambia il ruolo di quell'utente. |
| DELETE | `/api/user/apiari/{id_apiario}/condivisioni/{id_utente}` | utente + owner | Smette di condividerlo con quell'utente. |

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
| GET | `/api/admin/nodi` | admin | Tutti i nodi. |
| POST | `/api/admin/nodi` | admin | Registra un nodo. |
| GET | `/api/admin/nodi/{id_nodo}` | admin | Un singolo nodo. |
| PUT | `/api/admin/nodi/{id_nodo}` | admin | Aggiorna un nodo (il body è un `NodoCreate` completo). |
| DELETE | `/api/admin/nodi/{id_nodo}` | admin | Disattiva. Arnie e letture restano. |
| PUT | `/api/admin/nodi/{id_nodo}/proprietario` | admin | Assegna il nodo a un utente (`id_utente`), lo trasferisce, o lo libera (`null`). Le sue arnie passano nell'apiario predefinito del nuovo proprietario. |
| GET | `/api/admin/arnie` | admin | Tutte le arnie, comprese quelle dismesse. `id_apiario` opzionale. |
| POST | `/api/admin/arnie` | admin | Crea un'arnia. Finisce nell'apiario predefinito del proprietario del nodo, o in `id_apiario` se è di quel proprietario; l'arnia di un nodo non assegnato non è assegnata. |
| GET | `/api/admin/arnie/{id_arnia}` | admin | Una singola arnia con l'ultima lettura. |
| PUT | `/api/admin/arnie/{id_arnia}` | admin | Aggiorna un'arnia — **`attiva` compresa**, a differenza della rotta utente. |
| DELETE | `/api/admin/arnie/{id_arnia}` | admin | Disattiva. Le letture storiche restano. |
| GET | `/api/admin/apiari` | admin | Gli apiari di tutti gli utenti. `id_utente` opzionale. |
| POST | `/api/admin/apiari` | admin | Crea un apiario per l'utente indicato in `id_utente_proprietario`. |
| GET | `/api/admin/apiari/{id_apiario}` | admin | L'apiario di un utente qualsiasi. |
| PUT | `/api/admin/apiari/{id_apiario}` | admin | Modifica l'apiario di un utente qualsiasi. |
| DELETE | `/api/admin/apiari/{id_apiario}` | admin | Elimina l'apiario di un utente qualsiasi, con le regole del proprietario (**409** come sopra). |
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
| `check_user_arnia_access` | **403** | L'accesso del chiamante all'apiario dell'arnia non consente l'azione. |
| `check_user_apiario_access` | **403** | L'accesso del chiamante all'apiario non consente l'azione. |

`HTTPBearer(auto_error=False)` è voluto. Lasciato al default, FastAPI risponde a un
header *mancante* con un 403 secco e senza `WWW-Authenticate`; disattivandolo la
richiesta arriva a `get_current_user`, che restituisce il **401** corretto. La
distinzione che l'API mantiene è: **401 significa "chi sei?", 403 significa "so chi sei,
e no"**.

**L'accesso segue la proprietà (#36).** Un nodo appartiene a un utente, assegnato da
un admin; le sue arnie stanno negli apiari di quell'utente, e il proprietario di
un'arnia è il proprietario del suo apiario. Ogni account parte con un apiario
`Default`, dove finiscono le arnie dei nodi che gli vengono assegnati. Un nodo non
ancora assegnato, e le sue arnie, sono raggiungibili solo dagli admin.

Il proprietario di un apiario può fare tutto sull'apiario e sulle sue arnie, ed è
**l'unico che può condividerlo**. Una condivisione dà uno di tre ruoli sull'intero
apiario, comprese le arnie aggiunte dopo:

| Azione | viewer | collaborator | manager | owner |
|---|---|---|---|---|
| Vedere l'apiario, le sue arnie, letture e log attività | ✓ | ✓ | ✓ | ✓ |
| Registrare attività (e modificare o eliminare le proprie) | | ✓ | ✓ | ✓ |
| Modificare i dati di arnie e apiario | | | ✓ | ✓ |
| Dismettere un'arnia, spostarla, eliminare l'apiario, condividerlo | | | | ✓ |

La tabella sta in un solo posto, `ROLE_ACTIONS` in `meshbee_core/services/auth.py`;
ogni rotta dichiara l'azione che le serve, e un account con `ruolo = 'admin'` passa
ogni controllo. Un'azione sconosciuta solleva un'eccezione invece di restituire False,
così un errore di battitura fallisce in chiusura. `?id_apiario=` restringe l'elenco
delle arnie del chiamante, non lo allarga mai. Spostare un'arnia in un apiario che non
è del suo proprietario riceve lo stesso **400** che esista o no, così la risposta non
rivela nulla.

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
ogni rotta per accesso anonimo e non-admin, e prova ogni rotta su arnia o apiario a
ogni livello di accesso contro il suo minimo. È quello che becca un controllo
dimenticato o sbagliato.

## Trappole

- **Una rotta nuova richiede tre cose dopo**: `make openapi`, una riga nelle tabelle qui
  sopra e una riga in `test_main_authz.py`. Nessuna delle tre succede da sola.
- **L'immagine non contiene solo l'API.** Porta anche `mqtt_handler/`, `scripts/` e
  `tests/` più `paho-mqtt`, così l'intera suite — entrambi gli entry point compresi —
  gira in questo unico container. Per questo il contesto di build è la root del repo e
  non `api/`.
- **Il servizio `seed` usa questa stessa immagine**, con `python -m scripts.seed`.
- **Un `/health` che risponde 200 non dice niente.** Leggi `status` nel corpo.

## Collegamenti

- [`meshbee_core/`](../meshbee_core/README.it.md) — i service e gli schemi che ogni handler chiama.
- [`mqtt_handler/`](../mqtt_handler/README.it.md) — l'altro scrittore dello stesso database.
- [`tests/`](../tests/README.it.md) — come eseguire la suite e dove va un test nuovo.
- [`database/`](../database/README.it.md) — le tabelle dietro queste risposte.
- [README](../README.it.md) principale — lo stack nel suo insieme.
