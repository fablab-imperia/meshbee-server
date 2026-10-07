# `meshbee_core/` — libreria condivisa

*[English version](README.md)*

**Una libreria, non un servizio.** Non ha un `main`, non ha una porta e non ha un
container suo. Entrambi gli entry point — [`api/`](../api/README.it.md) e
[`mqtt_handler/`](../mqtt_handler/README.it.md) — e gli script in `scripts/` la
importano, ed è tutto il punto: una lettura arrivata via MQTT e una inviata all'API REST
passano per la *stessa* validazione e la *stessa* INSERT.

Viene installata in entrambe le immagini con `pip install -e .` a partire da
`pyproject.toml` (nome di distribuzione `meshbee-core`), ed è per questo che entrambi i
Dockerfile hanno come contesto di build la root del repo e non la propria directory.

```
api/  ──┐
        ├──▶ meshbee_core ──▶ PostgreSQL
mqtt_handler/ ──┘
scripts/ ───────┘
```

## Contenuto

| Percorso | Cos'è |
|---|---|
| `config.py` | `CoreSettings` — i campi del database, e nient'altro. |
| `db.py` | L'engine SQLAlchemy, `get_session()` e `integrity_errors()`. |
| `limits.py` | Ogni limite e insieme di valori, dichiarato una volta sola. Letto da `models.py` e da `mqtt_handler/contract.py`. |
| `models.py` | Il modello dei dati, dichiarato una volta sola: ogni tabella e le sue forme API (`XBase`, `XCreate`, `XUpdate`, `XResponse`) come un'unica famiglia SQLModel, più i modelli solo-API (login, token, serie, messaggi). La fonte da cui migra Alembic. |
| `migrations/` | Alembic: `env.py`, `upgrade()` e le revisioni. Vedi [`database/`](../database/README.it.md#cambiare-lo-schema). |
| `security.py` | Hashing e verifica delle password. Senza framework. |
| `errors.py` | `NotFound`, `Conflict`, `InvalidData` — il vocabolario che sollevano i service. |
| `repository/` | SQL. Un modulo per tabella. |
| `services/` | Decisioni di dominio. Un modulo per area. |

### `repository/` — tabelle e query, nient'altro

| Modulo | Copre |
|---|---|
| `utenti.py` | `utenti`. `get_credentials_by_email` è l'unica proiezione che include `password_hash`. |
| `nodi.py` | `nodi`, compreso `register_if_absent` per il percorso di ingest. |
| `arnie.py` | `arnie`, e `STATO`: ogni arnia con il nome del nodo e l'ultima lettura. `update` usa un sentinella `UNSET` così `attiva` viene toccata solo se passata esplicitamente. |
| `letture.py` | `letture`. `insert` è l'unica INSERT a cui arrivano entrambi gli entry point; `series` mette in whitelist il nome della colonna. |
| `attivita.py` | `log_attivita`, con update e delete limitati al proprietario. |
| `accessi.py` | `utenti_arnie` — la tabella delle associazioni. |

### `services/` — decisioni

| Modulo | Copre |
|---|---|
| `auth.py` | Autenticazione e la scala dei permessi `read < write < admin`. |
| `utenti.py` | Ciclo di vita degli account, incluso il rifiuto di disattivare se stessi. |
| `arnie.py` | Le arnie, e chi può vedere quali. |
| `letture.py` | Le letture, la finestra di default di un anno, la validazione dei limiti. |
| `attivita.py` | Il log attività. |
| `accessi.py` | Concessione e revoca dell'accesso a un'arnia. |
| `ingest.py` | Il percorso MQTT: registra il nodo, risolve o crea l'arnia, archivia la lettura. |

## Regole dei livelli

La stratificazione è il motivo per cui questo package esiste, e vale la pena dirla
chiaramente:

- **`repository/` = tabelle e query**, scritte sui modelli di `models.py`. Nessuna
  decisione, nessuna validazione, nessun errore oltre a quelli del database. Ogni
  funzione prende una `session` come primo argomento, fa flush di ciò che scrive e
  restituisce dizionari semplici — mai un'istanza di modello legata alla sessione.
- **`services/` = decisioni di Meshbee.** Chiamano il repository e sollevano
  `errors.NotFound` / `Conflict` / `InvalidData`. **Mai `HTTPException`** — un service
  non sa di essere chiamato via HTTP, e lo stesso codice lo chiama l'handler MQTT.
- **Entry point e script** validano l'input, chiamano *un solo* service e traducono il
  risultato in quello che il loro protocollo prevede (uno status code, una riga di log).

Quindi: la logica nuova va in un service; l'SQL nuovo in un repository; una rotta nuova o
un topic nuovo sono una chiamata sottile a un service che esiste già. **Se compare
dell'SQL in `api/`, `mqtt_handler/` o `scripts/`, è finito nel posto sbagliato.**

## Ciclo di vita della sessione

**La transazione è del chiamante.** Service e repository ricevono una sessione e non ne
aprono mai una.

```python
with get_session() as session:           # un blocco == una transazione
    utenti_service.create_utente(session, user)
```

`get_session()` apre una sessione SQLModel sull'engine condiviso e in uscita fa
**commit se l'uscita è pulita, rollback e rilancio in caso di eccezione**, restituendo
sempre la connessione al pool.

Un service che ha bisogno che la violazione di un vincolo *significhi* qualcosa
racchiude la scrittura in `integrity_errors()`, indicando l'errore di dominio per ogni
tipo:

```python
with integrity_errors(unique=Conflict("Email già registrata")):
    utenti.update(session, id_utente, updates)
```

Le violazioni non mappate — un CHECK, per esempio — si propagano invariate. I service
non importano mai il driver.

Due conseguenze da tenere a mente:

- **Più chiamate a service dentro un blocco sono un'unica unità atomica.** È il
  meccanismo da usare quando due scritture devono avvenire entrambe o nessuna.
- **Uscire in silenzio invece di sollevare un'eccezione fa commit di una scrittura
  parziale.** È per questo che `ingest.register_node_and_resolve_arnia` solleva
  `NotFound` invece di restituire `None` — un return silenzioso avrebbe reso permanente
  la registrazione del nodo appena fatta.

Il pool viene aperto da ogni processo all'avvio con la propria dimensione:
`init_db_pool(settings, maxconn=...)` — 20 per l'API, 10 per l'handler, 2 per il seed.
Il pool è il `QueuePool` di SQLAlchemy, che è thread-safe: le rotte dell'API sono `def`
semplici e girano nel threadpool di FastAPI. La libreria non sceglie mai la propria configurazione: le impostazioni le riceve sempre
dall'esterno.

## Configurazione

`CoreSettings` contiene **solo** ciò che serve a ogni processo — il database:

| Variabile | Tipo | Default |
|---|---|---|
| `DB_HOST` | str | `localhost` (da compose: `postgres`) |
| `DB_PORT` | int | `5432` |
| `DB_NAME` | str | `beehive_iot` |
| `DB_USER` | str | `beehive_user` |
| `DB_PASSWORD` | secret | **obbligatoria** |

Ogni entry point la estende con i propri extra: `api/config.py` aggiunge i campi JWT e
CORS, `mqtt_handler/config.py` i campi `MQTT_*`, `scripts/seed.py` le due password
iniziali.

**Metti un campo nuovo nella classe più stretta che ne ha bisogno.** Un campo
obbligatorio aggiunto a `CoreSettings` deve essere presente nell'ambiente di *ogni*
servizio in `docker-compose.yml`, altrimenti quel servizio va in crash all'import — al
container `seed`, per esempio, non viene mai data `JWT_SECRET_KEY` perché non se ne fa
niente.

I segreti sono `SecretStr`, così non finiscono in una riga di log o in un traceback; si
leggono con `.get_secret_value()`. `get_core_settings()` è `lru_cache`ata — la suite di
test svuota quella cache fra un test e l'altro, ed è quello che rende le impostazioni
testabili.

## Validazione

I limiti sono validati dai modelli in `models.py`, con i valori di `limits.py`:

| Campo | Intervallo | Dove altro |
|---|---|---|
| `temperatura` | da −50 a 100 °C | CHECK `valid_temperatura`, contratto MQTT |
| `umidita` | da 0 a 100 % | CHECK `valid_umidita`, contratto MQTT |
| `peso` | ≥ 0 kg | CHECK `valid_peso`, contratto MQTT |
| `latitudine` | da −90 a 90 | CHECK `valid_latitudine` |
| `longitudine` | da −180 a 180 | CHECK `valid_longitudine` |
| password | minimo 8 caratteri, massimo **72 byte** | — |
| `ruolo` | `user`, `admin` | CHECK su `utenti.ruolo` |
| `permessi` | `read`, `write`, `admin` | CHECK su `utenti_arnie.permessi` |
| `tipo_attivita` | 8 valori | CHECK su `log_attivita.tipo_attivita` |

**Ogni limite e insieme di valori è dichiarato una volta sola, in `limits.py`.** I
validatori sulle forme API, i vincoli CHECK sulle tabelle (entrambi in `models.py`) e le parole chiave JSON Schema in
`mqtt_handler/contract.py` leggono tutti le stesse costanti, quindi cambiare un numero
cambia tutti e tre — e il database segue con una migrazione (l'autogenerate non vede i
CHECK; vedi [`database/`](../database/README.it.md#cambiare-lo-schema)).
`tests/integration/core/test_schemas.py` verifica ancora contro un database reale che un
valore rifiutato qui sia rifiutato anche lì.

Altre due note sulla validazione:

- **`UserLogin.email` viene normalizzata ma non verificata nel formato.** Un'email
  malformata al login deve produrre un **401**, non un 422 — un errore di validazione
  direbbe a un attaccante quale dei due campi era sbagliato. `UserBase.email` (creazione
  di un account) *viene* verificata.
- **Il limite della password è di 72 byte, non 72 caratteri.** È di bcrypt, non nostro:
  tronca in silenzio oltre i 72 byte, quindi una password più lunga avrebbe caratteri che
  non fanno differenza. In UTF-8 un'emoji ne costa quattro.

## Sicurezza

`security.py` è volutamente minimo e non dipende da niente: bcrypt a **cost 12**,
`get_password_hash` e `verify_password`. La verifica restituisce `False` per *qualsiasi*
eccezione (un hash malformato nel database è un login fallito, non un 500).

Lo usano sia l'API sia `scripts/seed.py`, ed è per questo che un account creato dal seed
e uno creato dall'API admin sono indistinguibili.

## Sviluppo

Il package è montato in bind in ogni container, quindi una modifica è immediata per
l'API (uvicorn `--reload`) e richiede un riavvio per l'handler.

```bash
docker-compose exec api pytest tests/unit/core tests/integration/core
```

I test rispecchiano la struttura del sorgente: `meshbee_core/config.py` →
`tests/unit/core/test_config.py`. **Tutto ciò la cui sostanza è SQL va in
`tests/integration/`** — una sessione finta dimostra soltanto che abbiamo costruito
un'istruzione, non che l'istruzione sia giusta. Vedi [`tests/`](../tests/README.it.md).

## Trappole

- **Aggiungere un campo obbligatorio a `CoreSettings` può rompere servizi che non lo
  usano.** Vince la classe più stretta.
- **`nodi.ultimo_messaggio` la imposta solo `services/ingest.py`.** Significa "ultimo
  messaggio MQTT ricevuto", in ora del server; una lettura inserita in altro modo non
  deve toccarla — vedi [`database/`](../database/README.it.md#niente-viste-niente-trigger).
- **`repository/letture.py::series` mette in whitelist il nome della colonna.** È
  l'unico punto in cui un nome di colonna arriva da chi chiama, quindi viene confrontato
  con `SERIES_FIELDS` e solleva un errore per qualsiasi altra cosa. Non "semplificarlo"
  in una f-string.
- **`arnie.update` usa un sentinella `UNSET`, non `None`.** `None` è un valore
  legittimo da scrivere; il sentinella è il modo per tenere distinto "il chiamante non
  ha detto niente su questa colonna", ed è quello che impedisce a un update lato utente
  di dismettere un'arnia in silenzio.
- **Un nome di permesso sconosciuto solleva un'eccezione** invece di restituire `False`:
  un errore di battitura fallisce in chiusura invece di negare l'accesso a tutti senza
  dirlo.

## Collegamenti

- [`api/`](../api/README.it.md) — come questi errori diventano status code.
- [`mqtt_handler/`](../mqtt_handler/README.it.md) — l'altro chiamante, e `services/ingest.py`.
- [`database/`](../database/README.it.md) — le tabelle con cui parla il livello repository.
- [`tests/`](../tests/README.it.md) — i due livelli e dove va un test nuovo.
- [README](../README.it.md) principale — lo stack nel suo insieme.
