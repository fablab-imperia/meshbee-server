# `tests/` — la suite di test

*[English version](README.md)*

Un'unica suite pytest che copre **tutto**: entrambi gli entry point, la libreria
condivisa e gli script. Sta nella root del repo invece che dentro ogni package perché
`tests/integration/test_ingest_parity.py` deve confrontare il percorso API e quello MQTT
in un solo test, e nessuno dei due package può possederlo.

## Esecuzione

**Nel container, sempre.** `config.py` costruisce le sue `Settings` all'import, quindi
sull'host fallisce la collection prima ancora di eseguire un test.

```bash
docker-compose --profile test up -d postgres-test    # una volta per avvio, per il livello di integrazione
docker-compose exec api pytest                       # tutto (= make test)
```

I percorsi sono relativi alla root del repo, che nel container è `/app`:

```bash
docker-compose exec api pytest -m "not integration"          # senza database
docker-compose exec api pytest -m integration
docker-compose exec api pytest tests/unit/core/test_config.py
docker-compose exec api pytest tests/unit/core/test_config.py::test_database_url_escapes_special_characters
docker-compose exec api pytest -k "password or token" -v
docker-compose exec api pytest -x --lf                       # fermati al primo errore, poi rilancia solo quello
```

`postgres-test` sta dietro il profilo `test`, quindi un semplice `docker-compose up` non
lo avvia. I suoi dati stanno in tmpfs e non espone porte.

**Senza di lui il livello di integrazione fallisce con un messaggio esplicito — non
viene saltato.** È voluto: una suite che diventa verde perché un terzo dei test è
sparito in silenzio è peggio di una rossa.

Una dipendenza di sviluppo nuova richiede `docker-compose build api`
(`requirements-dev.txt` è dentro l'immagine). I *file di test* nuovi no — `tests/` è
montata in bind.

## Due livelli

```
tests/
  unit/           nessun database
  integration/    un PostgreSQL vero
```

La divisione è al primo livello dell'albero perché guida il marker: tutto quello sotto
`integration/` viene marcato `integration` in automatico, in base al percorso, in
`tests/integration/conftest.py`. I percorsi dei sorgenti sono rispecchiati *dentro* ogni
livello, un modulo di test per modulo sorgente — `meshbee_core/config.py` →
`tests/unit/core/test_config.py`.

**Unit** è per la logica senza SQL: risoluzione delle impostazioni, validatori, gestione
di JWT e password, aritmetica dei permessi, parsing del payload.

**Integration** è per tutto ciò la cui sostanza *è* SQL — nomi di colonna, join, ordine
dei parametri, vincoli CHECK. Un cursore finto dimostra soltanto che abbiamo passato una
stringa a `execute()`; non può dirti che la stringa era sbagliata. Quindi: **se quello
che stai testando è una query, va in `integration/`.**

La fixture di sessione `test_schema` elimina lo schema e lo ricostruisce con
`upgrade head` di Alembic una volta per esecuzione — il percorso di un'installazione
nuova — così ogni revisione viene esercitata a ogni run e non può marcire in silenzio.
`integration/test_migrations.py` verifica poi che ciò che costruiscono le revisioni sia
ciò che descrive `meshbee_core/models.py`, corpi dei CHECK compresi.

## I due moduli che pesano di più

**`integration/core/test_schemas.py` — l'accordo modello↔schema.** I limiti vengono da
un solo posto, `meshbee_core/limits.py`, ma un database ha soltanto i CHECK che gli hanno
dato le sue migrazioni. Questo modulo ricava i suoi casi dal contratto MQTT pubblicato e
verifica che gli schemi pydantic e il database reale rifiutino gli stessi valori.
Aggiungi un caso ogni volta che aggiungi un limite.

**`integration/test_ingest_parity.py` — il motivo per cui esiste il livello
condiviso.** Dimostra che il percorso API e quello MQTT scrivono righe **uguali**, ogni
colonna tranne `id_lettura`. La sua fixture `deliver` racchiude ogni messaggio in un
SAVEPOINT, perché in produzione ogni messaggio ha la sua transazione e il test non deve
lasciare che un messaggio veda il lavoro non committato di un altro.

**`integration/api/test_main_authz.py` — il cancello.** Un'unica tabella passa in
rassegna **tutti i 37 endpoint** per accesso anonimo, autenticato-ma-non-admin e
autenticato-senza-associazione. **Aggiungi ogni endpoint nuovo a quella tabella.** È
quello che becca una rotta che si è dimenticata il suo `Depends`.

## Fixture

Quelle condivise stanno in `tests/conftest.py`; quelle con database in
`tests/integration/conftest.py`.

### Impostazioni

- `build_settings()` / `build_core_settings()` — kwargs espliciti più `_env_file=None`.
- `required_env` — il minimo per delle `Settings` valide.
- `isolated_settings_env` — **autouse**: rimuove dall'ambiente ogni campo di `Settings` e
  svuota le `lru_cache` prima e dopo ogni test.

Quella fixture autouse non è un ornamento. Compose inietta `DB_HOST=postgres` e simili
nel container, quindi **senza di lei ogni asserzione su un valore di default
verificherebbe l'ambiente di compose, non il codice**.

### Database

- `fake_db(module, rows=[...], error=...)` — livello unit. Sostituisce `get_db_cursor`
  **sul modulo che lo importa** (`api.auth`, `api.main`, `mqtt_handler.handler`), perché
  ognuno ne tiene un proprio riferimento e sostituirlo su `meshbee_core.db` non fa
  niente. `.queries` registra `(sql, params)`; `error=` simula un guasto.
- `db` / `use_db(module)` — livello integration, stessa cucitura. `db` racchiude ogni
  test in una transazione che viene poi annullata.
- `fake_cursor(rows=[...])` — un cursore nudo da *passare*. Le funzioni di repository e
  service ricevono un cursore invece di aprirlo, quindi non serve sostituire niente.

La cucitura unica è il punto: sostituire `get_db_cursor` una volta copre un'intera
richiesta, perché il cursore prosegue immutato nelle chiamate a service e repository.

### HTTP

- `client` — un `TestClient` che **non viene mai usato come context manager**. Farlo
  eseguirebbe il lifespan, e il lifespan chiama `init_db_pool()` sul database di
  *sviluppo*.
- `as_user(row)` — sostituisce **solo** `get_current_active_user`, così
  `get_current_admin_user` gira per davvero e il controllo admin viene testato sul serio.
- `anyio_backend` — a un test async basta `@pytest.mark.anyio`. anyio arriva con
  FastAPI; **non aggiungere pytest-asyncio**. Le dipendenze si aspettano direttamente,
  senza passare da un client.

### Costruttori di dati

`make_utente`, `make_arnia`, `grant_access`, `utente_con_arnia`, `make_lettura`,
`make_attivita`.

## Convenzioni

- **Nomi in forma di frase**, in inglese, e una docstring che dice **perché quel test
  conta** — non cosa fa il codice.
- **Un modulo di test per modulo sorgente**, rispecchiando il percorso del sorgente.
- **Ogni directory di test ha bisogno di `__init__.py`** — senza, due moduli con lo
  stesso nome base collidono durante la collection.
- **Testa la nostra logica, non le librerie.** Nessun test per pydantic, FastAPI o
  bcrypt — tranne una stranezza della libreria a cui siamo esposti (il troncamento a 72
  byte di bcrypt), e in quel caso lo dice la docstring.
- **Non fissare mai un comportamento noto come sbagliato.** Verifica la proprietà che
  vuoi, non il risultato che ottieni oggi, altrimenti correggere il bug significherà
  combattere contro la suite. Se qualcosa è sbagliato e non si corregge adesso, quella è
  una issue e un `xfail`, non un'asserzione verde.

## Trappole

- **`utenti.ruolo` è `('user','admin')`** — non `'utente'` — e `utenti_arnie.permessi` è
  `('read','write','admin')`. I fake accettano qualsiasi cosa; il database reale la
  rifiuta, quindi un test unit può passare su dati che l'integrazione respinge.
- **Credenziali mancanti danno 401 + `WWW-Authenticate`; autenticato-ma-vietato dà
  403.** Verificare quello sbagliato è il modo in cui una vera regressione di
  autorizzazione passa inosservata.
- **Endpoint nuovo → riga nuova in `test_main_authz.py`.**
- **`postgres-test` è per avvio della macchina, non per esecuzione.** Una volta avviato
  resta su; un fallimento di connessione su tutto il livello di integrazione di solito
  significa solo che la macchina è stata riavviata.
- **`tests/integration/core/services/` esiste ma è vuota** — il comportamento dei service
  è oggi coperto attraverso i test dell'API e quelli dei repository. Un test puro di
  service lì è benvenuto.

## Collegamenti

- [`api/`](../api/README.it.md), [`mqtt_handler/`](../mqtt_handler/README.it.md),
  [`meshbee_core/`](../meshbee_core/README.it.md) — quello che viene testato.
- [`database/`](../database/README.it.md) — lo schema che il livello di integrazione ricarica.
- [README](../README.it.md) principale — lo stack nel suo insieme.
