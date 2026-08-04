# 🐝 Meshbee Backend

[![Latest release](https://img.shields.io/github/v/release/fablab-imperia/meshbee-server?sort=semver)](https://github.com/fablab-imperia/meshbee-server/releases/latest)

This is the **backend** code for the [Meshbee project](https://github.com/fablab-imperia/meshbee). Implements FastAPI REST API, MQTT handler, Mosquitto broker and PostgreSQL, via Docker Compose.

Other parts of the Meshbee project include:

| Repository | What it is |
|---|---|
| **[meshbee](https://github.com/fablab-imperia/meshbee)**  | Umbrella repo: documentation, architecture and the versioned MQTT/API contract. |
| **[meshbee-firmware](https://github.com/fablab-imperia/meshbee-firmware)** | ESP32 firmware for the sensor and gateway nodes (Meshtastic + MQTT). |
| **[meshbee-server](https://github.com/fablab-imperia/meshbee-server)** (this one) | Backend: FastAPI REST API, MQTT handler, Mosquitto broker and PostgreSQL, via Docker Compose. |
| **[meshbee-app](https://github.com/fablab-imperia/meshbee-app)** | Mobile app in React Native / Expo — dashboards, charts and push alerts. |
| **[meshbee-hardware](https://github.com/fablab-imperia/meshbee-hardware)** | Hardware design: PCB schematics and 3D-printed enclosures. |

📖 **Documentation:** <https://fablab-imperia.github.io/meshbee/>

🛠️ **Built by:** [Fablab Imperia APS](https://www.fablabimperia.org)

## 📋 Indice

- [Panoramica](#panoramica)
- [Architettura](#architettura)
- [Requisiti](#requisiti)
- [Installazione](#installazione)
- [Configurazione](#configurazione)
- [Utilizzo](#utilizzo)
- [API Endpoints](#api-endpoints)
- [Formato Dati MQTT](#formato-dati-mqtt)
- [Database Schema](#database-schema)
- [Sviluppo](#sviluppo)

## 🎯 Panoramica

Sistema IoT completo per il monitoraggio di arnie che include:

- **Database PostgreSQL** per archiviare dati sensori e utenti
- **Broker MQTT** (Mosquitto) per ricevere dati dai dispositivi IoT
- **API RESTful** (FastAPI) per accesso ai dati da applicazioni
- **Sistema di autenticazione** con JWT tokens
- **Gestione allarmi** automatici basati su soglie configurabili
- **Multi-tenant** con gestione utenti e permessi

### Funzionalità Principali

✅ Ricezione dati in tempo reale tramite MQTT  
✅ Archiviazione storica di temperatura, umidità e peso  
✅ API RESTful complete con autenticazione JWT  
✅ Gestione utenti e permessi  
✅ Sistema di allarmi automatici  
✅ Log attività degli apicoltori  
✅ Ottimizzato per Raspberry Pi 4  
✅ Completamente dockerizzato  

## 🏗️ Architettura

Due processi Python scrivono e leggono lo **stesso** database, e condividono la
stessa logica importandola da `meshbee_core`.

```
   Nodi ESP32                                              App Mobile/Web
   (arnie)                                                    (client)
       │                                                          │
       │ MQTT                                                HTTPS │
       ▼                                                          ▼
┌──────────────┐      ┌─────────────────┐      ┌─────────────────────┐
│  Mosquitto   │─────▶│  MQTT Handler   │      │   FastAPI  (api/)   │
│    broker    │      │ (mqtt_handler/) │      │                     │
└──────────────┘      └────────┬────────┘      └──────────┬──────────┘
                               │                          │
                     import    │        ┌─────────────────┘  import
                               ▼        ▼
                        ┌────────────────────────┐
                        │     meshbee_core       │   ← libreria, non un servizio
                        │  services/  (logica)   │
                        │  repository/  (SQL)    │
                        └───────────┬────────────┘
                                    │
                                    ▼
                            ┌──────────────┐
                            │  PostgreSQL  │
                            └──────────────┘
```

### I due entry point

| Processo | Cosa fa |
|---|---|
| **`api/`** — FastAPI | Serve l'app mobile: login JWT, arnie, letture, log attività, endpoint admin. |
| **`mqtt_handler/`** — subscriber MQTT | Riceve le letture dei sensori dai nodi ESP32 via Mosquitto (topic `beehive/+/data`) e le salva. |

Restano **due processi separati**, due container, due comandi di avvio. Il
handler MQTT non chiama l'API via HTTP: parla al database attraverso la libreria
condivisa, esattamente come fa l'API.

### `meshbee_core` è una libreria, non un servizio

È il punto che si fraintende più spesso: `meshbee_core` **viene importato, non
distribuito**. Non c'è un container `meshbee-core`, non c'è una porta, non c'è
una chiamata di rete. Ciascuno dei due processi ne tiene una propria copia in
memoria; sono due istanze indipendenti dello stesso codice.

Il pacchetto è installato in modalità *editable* (`pip install -e .`, vedi
`pyproject.toml`) in entrambe le immagini, così l'import funziona allo stesso
modo nei container e nei test.

### Il confine fra i livelli

| Livello | Responsabilità |
|---|---|
| `meshbee_core/repository/` | Solo persistenza: tabelle e query. Nessuna regola di business. |
| `meshbee_core/services/` | La logica di Meshbee: validazione, permessi, provisioning dei nodi. Chiama il repository. |
| `api/`, `mqtt_handler/` | Sottili: validano l'input, chiamano **un** service, traducono l'esito. |

Regola sul ciclo di vita: **il cursore lo apre chi chiama**. Service e repository
lo ricevono come argomento e non lo creano mai — l'API ne apre uno per richiesta,
il handler MQTT uno per messaggio. Stessa funzione, due strategie diverse, perché
una richiesta HTTP e un messaggio MQTT hanno durate diverse.

Gli errori attraversano il confine tramite `meshbee_core/errors.py`
(`NotFound`, `Conflict`, `InvalidData`): i service non conoscono gli status code,
è `api/main.py` a tradurli in 404/409/400.

### Dove va il codice nuovo

- Nuova **logica di business** → un service in `meshbee_core/services/`.
- Nuova **query SQL** → una funzione nel repository corrispondente.
- Nuova **rotta HTTP** o nuova **sottoscrizione a un topic** → una chiamata
  sottile a un service che esiste già.

Se ti ritrovi a scrivere SQL dentro `api/` o `mqtt_handler/`, sta andando nel
posto sbagliato.

## 💻 Requisiti

### Hardware Minimo
- **Raspberry Pi 4** (2GB RAM) o equivalente
- **16GB** storage
- Connessione di rete

### Software
- Docker & Docker Compose
- (Opzionale) Git per clonare il repository
- (Opzionale) [mkcert](https://github.com/FiloSottile/mkcert) per il certificato HTTPS locale (`make certs`)

## 🚀 Installazione

### 1. Clona il Repository

```bash
git clone https://github.com/fablab-imperia/meshbee-server.git
cd meshbee-server
```

### 2. Crea File di Configurazione

```bash
cp .env.example .env
```

### 3. Modifica Configurazione

Edita il file `.env` e imposta valori sicuri per **tutte** le credenziali:

```bash
# IMPORTANTE: Cambia queste password!
POSTGRES_PASSWORD=tua-password-sicura        # password del database
JWT_SECRET_KEY=genera-chiave-con-openssl     # firma dei token JWT
MQTT_PASSWORD=tua-password-mqtt              # autenticazione broker/handler MQTT
ADMIN_PASSWORD=tua-password-admin           # utente admin creato al primo avvio
USER_PASSWORD=tua-password-utente           # utente di test creato al primo avvio
```

`ADMIN_PASSWORD` e `USER_PASSWORD` sono **obbligatorie e di almeno 8 caratteri**:
se mancano, il servizio `seed` si ferma con un errore esplicito invece di creare
account utilizzabili con password vuota.

Per generare una chiave JWT sicura:

```bash
openssl rand -hex 32
```

### 4. Genera il File Password per Mosquitto

Il broker richiede autenticazione (`allow_anonymous false`), quindi va generato
il file password a partire dalle credenziali in `.env`. **Senza questo passo il
container Mosquitto non si avvia.**

```bash
make mqtt-passwd
```

> Se in seguito cambi `MQTT_PASSWORD` nel `.env`, riesegui `make mqtt-passwd`.

### 5. (Opzionale) Abilita HTTPS

Lo stack include un proxy **Caddy** che espone l'API in HTTPS con un certificato
attendibile localmente. Genera il certificato una volta (richiede
[mkcert](https://github.com/FiloSottile/mkcert)):

```bash
make certs
```

Se salti questo passo, Caddy stampa un avviso ed esce: il resto dello stack e
l'HTTP su `:8000` continuano a funzionare.

### 6. Avvia i Servizi

```bash
docker-compose up -d      # oppure: make start
```

> **Scorciatoia:** `make setup` esegue in sequenza la copia di `.env`,
> `make mqtt-passwd` e l'avvio dei servizi (esclusi i certificati HTTPS).

### 7. Verifica il Funzionamento

```bash
# Verifica che tutti i container siano in esecuzione
docker-compose ps

# Controlla i log
docker-compose logs -f
```

- **HTTP**:  <http://localhost:8000/docs>
- **HTTPS**: <https://localhost:8443/docs> (se hai eseguito `make certs`)

> Il container `meshbee-seed` crea gli utenti iniziali e poi termina: vederlo
> come `Exited (0)` è normale, non è un errore.

## ⚙️ Configurazione

### Variabili d'Ambiente

Tutte le configurazioni sono nel file `.env`:

| Variabile | Descrizione | Default |
|-----------|-------------|---------|
| `POSTGRES_PASSWORD` | Password database | CHANGE_ME_IN_DOT_ENV |
| `JWT_SECRET_KEY` | Chiave per firmare JWT | (generare!) |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Durata token accesso | 30 |
| `MQTT_BROKER` | Host broker MQTT | mosquitto |
| `MQTT_PORT` | Porta MQTT | 1883 |

### Database Iniziale

Il database viene inizializzato automaticamente con:
- Schema completo
- Utente admin (email: `admin@beehive.local`, password: `YOUR_ADMIN_PASSWORD`)
- Utente test (email: `utente@test.local`, password: `YOUR_USER_PASSWORD`)
- Dati di esempio

**⚠️ IMPORTANTE:** Cambiare le password di default in produzione!

### Configurazione Soglie Allarmi

Le soglie possono essere configurate per ogni arnia tramite il campo `configurazione` (JSONB):

```json
{
  "soglia_temperatura_max": 38.0,
  "soglia_temperatura_min": 30.0,
  "soglia_umidita_max": 80.0,
  "soglia_umidita_min": 40.0,
  "soglia_peso_min": 25.0
}
```

## 📱 Utilizzo

### Test del Sistema

#### 1. Test API (Health Check)

```bash
curl http://localhost:8000/health
```

#### 2. Login

```bash
curl -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "email": "utente@test.local",
    "password": "YOUR_USER_PASSWORD"
  }'
```

Risposta:
```json
{
  "access_token": "eyJ0eXAiOiJKV1QiLCJhbGc...",
  "refresh_token": "eyJ0eXAiOiJKV1QiLCJhbGc...",
  "token_type": "bearer"
}
```

#### 3. Chiamata API Autenticata

```bash
TOKEN="<access_token_ricevuto>"

curl http://localhost:8000/api/user/arnie \
  -H "Authorization: Bearer $TOKEN"
```

### Test MQTT

```bash
# Usando mosquitto_pub
mosquitto_pub -h localhost -t "beehive/NODE001/data" -m '{
  "id_nodo": "NODE001",
  "id_sensore": "SENSOR01",
  "temperatura": 34.5,
  "umidita": 65.0,
  "peso": 42.5
}'
```

## 📡 API Endpoints

### Autenticazione

| Method | Endpoint | Descrizione | Auth |
|--------|----------|-------------|------|
| POST | `/api/auth/login` | Login utente | No |
| GET | `/api/auth/me` | Info utente corrente | Sì |

### Endpoints Utente

| Method | Endpoint | Descrizione | Auth |
|--------|----------|-------------|------|
| GET | `/api/user/arnie` | Lista arnie utente | User |
| GET | `/api/user/arnie/{id}/letture` | Letture arnia | User |
| GET | `/api/user/arnie/{id}/attivita` | Attività arnia | User |
| POST | `/api/user/arnie/{id}/attivita` | Aggiungi attività | User |
| GET | `/api/user/arnie/{id}/allarmi` | Allarmi arnia | User |

### Endpoints Admin

| Method | Endpoint | Descrizione | Auth |
|--------|----------|-------------|------|
| GET | `/api/admin/utenti` | Lista tutti utenti | Admin |
| POST | `/api/admin/utenti` | Crea utente | Admin |
| PUT | `/api/admin/utenti/{id}` | Aggiorna utente | Admin |
| GET | `/api/admin/nodi` | Lista nodi | Admin |
| GET | `/api/admin/arnie` | Lista arnie | Admin |
| POST | `/api/admin/arnie` | Crea arnia | Admin |
| POST | `/api/admin/utenti-arnie` | Associa utente-arnia | Admin |
| GET | `/api/admin/letture` | Tutte le letture | Admin |
| GET | `/api/admin/attivita` | Tutte le attività | Admin |

### Documentazione Interattiva

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

## 📨 Formato Dati MQTT

### Topic Pattern

```
beehive/{ID_NODO}/data
```

Esempi:
- `beehive/NODE001/data`
- `beehive/APIARY_SOUTH/data`

### Payload JSON

```json
{
  "id_nodo": "NODE001",
  "id_sensore": "SENSOR01",
  "timestamp": "2024-02-01T12:00:00",
  "temperatura": 34.5,
  "umidita": 65.0,
  "peso": 42.350,
  "dati_raw": {
    "batteria": 3.8,
    "segnale": -65
  }
}
```

### Campi

| Campo | Tipo | Obbligatorio | Descrizione |
|-------|------|--------------|-------------|
| `id_nodo` | string | Sì | ID univoco del nodo trasmettitore |
| `id_sensore` | string | No | ID sensore (per multi-sensore) |
| `timestamp` | ISO 8601 | No | Timestamp lettura (default: ora corrente) |
| `temperatura` | float | No | Temperatura in °C |
| `umidita` | float | No | Umidità relativa % |
| `peso` | float | No | Peso in kg |
| `dati_raw` | object | No | Altri dati in formato libero |

## 🗄️ Database Schema

### Tabelle Principali

**utenti**
- Gestione utenti e autenticazione
- Ruoli: `user`, `admin`

**nodi**
- Dispositivi IoT trasmettitori
- Tracking ultimo messaggio ricevuto

**arnie**
- Arnie monitorate
- Associazione nodo-sensore
- Metadati configurabili

**letture**
- Dati telemetrici (temperatura, umidità, peso)
- Indicizzato per query temporali efficienti

**log_attivita**
- Registro interventi apicoltore
- Tipi: ispezione, trattamento, raccolta, etc.

**utenti_arnie**
- Associazione many-to-many utenti-arnie
- Gestione permessi (read, write, admin)

**token_sessione**
- Prevista per i refresh token revocabili, **non ancora usata da alcun codice**:
  i refresh token oggi sono JWT stateless e non vengono salvati.
- Non rimuoverla: è la forma corretta per la funzione quando verrà implementata (issue #16).

### Viste Utili

- `v_letture_recenti` - Letture ultimi 7 giorni
- `v_arnie_stato` - Arnie con ultime letture
- `v_allarmi_attivi` - Allarmi non risolti

## 🔧 Sviluppo

### Struttura Directory

```
meshbee-server/
├── meshbee_core/           # Libreria condivisa (importata dai due entry point)
│   ├── config.py          # CoreSettings: solo i campi del database
│   ├── db.py              # Pool di connessioni + get_db_cursor
│   ├── schemas.py         # Modelli Pydantic
│   ├── security.py        # Hashing password (bcrypt)
│   ├── errors.py          # NotFound / Conflict / InvalidData
│   ├── repository/        # Solo SQL: utenti, nodi, arnie, letture, attivita, accessi
│   └── services/          # Logica di business, incluso ingest.py (percorso MQTT)
├── api/                    # Entry point FastAPI
│   ├── main.py            # Rotte sottili (nessun SQL)
│   ├── auth.py            # JWT e dipendenze FastAPI
│   ├── config.py          # Settings(CoreSettings) + JWT/CORS
│   ├── Dockerfile
│   ├── requirements.txt
│   └── requirements-dev.txt
├── mqtt_handler/           # Entry point MQTT
│   ├── handler.py         # Callback sottile (nessun SQL)
│   ├── payload.py         # Decodifica del messaggio dei nodi
│   ├── config.py          # Settings(CoreSettings) + MQTT_*
│   ├── Dockerfile
│   └── requirements.txt
├── scripts/                # Script one-shot (non fanno parte dei servizi)
│   └── seed.py            # Utenti iniziali — idempotente, nessun SQL
├── tests/                  # Test suite (pytest)
│   ├── conftest.py        # Fixture condivise
│   ├── unit/              # Logica pura, senza database
│   │   ├── api/  core/  mqtt_handler/
│   └── integration/       # Query SQL su postgres-test
│       ├── api/  core/
│       └── test_ingest_parity.py   # API e MQTT scrivono righe equivalenti
├── database/              # Schema database
│   └── init.sql
├── mosquitto/             # Configurazione MQTT
│   └── config/
│       └── mosquitto.conf
├── pyproject.toml         # Pacchetto meshbee-core
├── pytest.ini
├── docker-compose.yml
├── .env.example
└── README.md
```

I due `Dockerfile` usano la **radice del repository** come build context (non
`./api` o `./mqtt_handler`): entrambe le immagini devono poter copiare
`meshbee_core/` e installarlo.

### Comandi Utili

```bash
# Riavvia tutti i servizi
docker-compose restart

# Riavvia solo l'API
docker-compose restart api

# Visualizza log in tempo reale
docker-compose logs -f api

# Accedi al database
docker-compose exec postgres psql -U beehive_user -d beehive_iot

# Backup database
docker-compose exec postgres pg_dump -U beehive_user beehive_iot > backup.sql

# Ripristina database
docker-compose exec -T postgres psql -U beehive_user beehive_iot < backup.sql

# Ferma tutto e rimuovi volumi (ATTENZIONE: cancella i dati!)
docker-compose down -v
```

### Test

I test sono scritti con [pytest](https://docs.pytest.org/) e vivono in `tests/`,
nella radice del repository. Coprono **entrambi** gli entry point e la libreria
condivisa, e girano tutti **dentro il container** `api`: l'immagine ha già tutte
le dipendenze, e `api/`, `mqtt_handler/`, `meshbee_core/` e `tests/` sono montate
in `/app`, quindi le modifiche sono subito visibili senza ricostruire nulla.

La suite è divisa in due livelli:

| Livello | Cosa verifica | Database |
|---|---|---|
| `tests/unit/` | logica pura: configurazione, validatori, JWT, password, permessi, parsing dei payload MQTT | no |
| `tests/integration/` | le query SQL vere: nomi colonne, join, vincoli dello schema | sì |

Dentro ciascun livello i file rispecchiano la struttura del codice
(`unit/api/`, `unit/core/`, `unit/mqtt_handler/`, …), così ogni modulo ha il suo
file di test nella posizione corrispondente.

Un test merita una menzione a parte:
`tests/integration/test_ingest_parity.py` verifica che **la stessa lettura,
arrivata via API e via MQTT, produca righe identiche** in `letture`. È la
regressione che l'estrazione di `meshbee_core` esiste per prevenire: prima
ciascun percorso aveva la sua copia della INSERT.

I test di integrazione usano il servizio `postgres-test`, un database usa-e-getta
con i dati in tmpfs. Va avviato una volta (non parte con un normale `up`):

```bash
docker-compose --profile test up -d postgres-test
```

Lo schema viene ricaricato da `database/init.sql` **a ogni esecuzione** della suite
e ogni test gira in una transazione che viene annullata: il database è sempre pulito
e i test non si influenzano a vicenda.

```bash
# Intera suite
docker-compose exec api pytest

# Solo i test che non richiedono il database
docker-compose exec api pytest -m "not integration"

# Solo i test di integrazione
docker-compose exec api pytest -m integration

# Un solo file
docker-compose exec api pytest tests/unit/core/test_config.py

# Una sola funzione (node id: file::funzione)
docker-compose exec api pytest tests/unit/core/test_config.py::test_database_url_escapes_special_characters

# Un caso di un test parametrizzato
docker-compose exec api pytest "tests/unit/api/test_config.py::test_missing_secret_fails_loudly[DB_PASSWORD]"

# Tutti i test il cui nome contiene una stringa
docker-compose exec api pytest -k database_url

# Solo il test di parità fra i due percorsi di scrittura
docker-compose exec api pytest tests/integration/test_ingest_parity.py

# Output verboso, fermati al primo fallimento
docker-compose exec api pytest -v -x
```

I percorsi sono relativi a `/app`, che corrisponde alla radice del repository.
Per comodità `make test` esegue l'intera suite; per tutto il resto si usa
direttamente `pytest` con i suoi argomenti.

I file di test sono separati per modulo e rispecchiano la struttura del codice
(`meshbee_core/config.py` → `tests/unit/core/test_config.py`): la suite cresce in
modo incrementale aggiungendo nuovi file, senza toccare quelli esistenti.

> **Nota:** dopo aver aggiunto una dipendenza in `api/requirements-dev.txt` serve
> ricostruire l'immagine, perché il bind mount copre solo il codice:
>
> ```bash
> docker-compose build api && docker-compose up -d api
> ```

### Sviluppo Locale

Per sviluppare senza Docker:

Tutti i comandi si eseguono dalla **radice del repository**: è lì che vivono
`pyproject.toml` e i pacchetti importabili.

```bash
# Setup Python environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
# oppure: venv\Scripts\activate  # Windows

# Installa le dipendenze dei due entry point
pip install -r api/requirements.txt -r api/requirements-dev.txt
pip install -r mqtt_handler/requirements.txt

# Installa la libreria condivisa in modalità editable.
# Senza questo passo `import meshbee_core` non risolve.
pip install -e .

# Configura variabili d'ambiente
export DB_HOST=localhost
export MQTT_BROKER=localhost
# ... altre variabili

# Avvia API
uvicorn api.main:app --reload

# Avvia MQTT handler (in un altro terminale)
python -m mqtt_handler
```

Le stesse operazioni sono automatizzate da `make dev-setup`, `make dev-api` e
`make dev-mqtt`.

### HTTPS locale (proxy Caddy)

L'ambiente di sviluppo è già isolato: ogni servizio gira nel proprio container
con le dipendenze fissate in `requirements.txt`, quindi sull'host serve solo
Docker. In più, lo stack include un proxy **Caddy** che espone l'API in
**HTTPS** con un certificato attendibile localmente, così problemi legati a
`Secure` cookie, mixed-content e URL assoluti emergono già in sviluppo.

Genera il certificato una volta (richiede [mkcert](https://github.com/FiloSottile/mkcert),
su macOS: `brew install mkcert`):

```bash
make certs   # = ./caddy/make-certs.sh
```

Poi avvia (o riavvia) lo stack come al solito:

```bash
make start   # oppure: docker-compose up -d
```

- **HTTPS**: <https://localhost:8443/docs>
- **HTTP**:  <http://localhost:8000/docs>

Se i certificati non ci sono, il container Caddy stampa le istruzioni ed esce
senza errori: il resto dello stack e l'HTTP su `:8000` continuano a funzionare.
La configurazione del proxy è in [`caddy/Caddyfile`](caddy/Caddyfile).

## 🔒 Sicurezza

### Best Practices

1. **Cambia le password di default** nel file `.env`
2. **Genera una chiave JWT sicura**: `openssl rand -hex 32`
3. **Usa HTTPS** in produzione (nginx con SSL)
4. **Abilita autenticazione MQTT** modificando `mosquitto.conf`
5. **Limita accesso rete** con firewall
6. **Backup regolari** del database

### Autenticazione MQTT (Opzionale)

Per abilitare autenticazione MQTT:

```bash
# Crea file password
docker-compose exec mosquitto mosquitto_passwd -c /mosquitto/config/passwd username

# Modifica mosquitto.conf
# allow_anonymous false
# password_file /mosquitto/config/passwd
```

## 🐛 Troubleshooting

### Il database non si inizializza

```bash
# Rimuovi volumi e ricrea
docker-compose down -v
docker-compose up -d
```

### MQTT handler non riceve messaggi

```bash
# Verifica che Mosquitto sia attivo
docker-compose logs mosquitto

# Test con mosquitto_sub
docker-compose exec mosquitto mosquitto_sub -t "beehive/#" -v
```

### API non risponde

```bash
# Verifica log
docker-compose logs api

# Verifica connessione database
docker-compose exec api python -c "from database import init_db_pool; init_db_pool()"
```

### Errore "Out of memory" su Raspberry Pi

Riduci i worker di uvicorn e le connessioni DB:

```yaml
# In docker-compose.yml, servizio api
command: uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1
```

## 📄 Licenza

Questo progetto è rilasciato sotto [licenza APGL-3.0](LICENSE).

## 👥 Versioning & contributing

Contributi, issues e feature requests sono benvenuti!

Releases follow [![SemVer 2.0.0](https://img.shields.io/badge/SemVer-2.0.0-blue.svg)](https://semver.org/spec/v2.0.0.html).

Commits follow [![Conventional Commits 1.0.0](https://img.shields.io/badge/Conventional%20Commits-1.0.0-blue.svg)](https://www.conventionalcommits.org/en/v1.0.0/).

See [CONTRIBUTING](https://github.com/fablab-imperia/.github/blob/main/CONTRIBUTING.md)
and the [compatibility matrix](https://fablab-imperia.github.io/meshbee/contract/compatibility/).

## 📞 Supporto

Per domande o problemi, apri una issue su GitHub.

---

**Fatto con ❤️ per gli apicoltori** 🐝
