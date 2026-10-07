# `database/` — schema PostgreSQL

*[English version](README.md)*

Cosa c'è nel database, e come cambia. PostgreSQL 15, in esecuzione come servizio
`postgres`; i dati stanno nel volume `postgres_data`.

Questa directory contiene solo documentazione. Lo schema è definito in Python, in
[`meshbee_core/models.py`](../meshbee_core/models.py), con limiti e insiemi di valori in
[`meshbee_core/limits.py`](../meshbee_core/limits.py); le migrazioni che portano un
database fin lì sono revisioni Alembic in
[`meshbee_core/migrations/versions/`](../meshbee_core/migrations/versions/).

I nomi di dominio sono in italiano — `utenti`, `nodi`, `arnie`, `letture` — perché sono
il vocabolario del progetto, non una traduzione mancata.

## Contenuto

| Percorso | Cos'è |
|---|---|
| `meshbee_core/models.py` | Lo schema **attuale**, come classi tabella SQLModel. L'unica fonte. |
| `meshbee_core/limits.py` | Limiti e insiemi di valori da cui sono costruiti i vincoli CHECK. |
| `meshbee_core/migrations/` | Alembic: `env.py`, e un file per revisione in `versions/`. |
| `scripts/migrate.py` | Ciò che esegue il servizio compose `migrate`: `upgrade head`, poi esce. |
| `alembic.ini` (radice del repo) | Solo per la CLI `alembic`, quando si scrive una revisione. |

**Lo schema viene applicato dal servizio `migrate`, a ogni avvio.** Parte prima di
`api`, `mqtt-handler` e `seed`, che aspettano tutti che esca con 0, e non fa niente se
il database è già all'ultima revisione. Vedi [Cambiare lo schema](#cambiare-lo-schema).

## Tabelle

Una tabella e le risposte API costruite da essa condividono un'unica dichiarazione in
[`meshbee_core/models.py`](../meshbee_core/models.py), quindi ogni colonna che una
risposta richiede è NOT NULL anche qui (revisione `0002`). Le tabelle qui sotto danno il
resto dei dettagli.

### `utenti` — gli account

| Colonna | Tipo | Note |
|---|---|---|
| `id_utente` | SERIAL | PK |
| `email` | VARCHAR(255) | UNIQUE NOT NULL. Normalizzata (trim, minuscolo) dall'applicazione. |
| `password_hash` | VARCHAR(255) | bcrypt, cost 12. |
| `nome`, `cognome` | VARCHAR(100) | NOT NULL |
| `ruolo` | VARCHAR(20) | CHECK `('user','admin')`, default `user`. |
| `data_creazione`, `data_attivazione`, `data_disattivazione`, `ultimo_accesso` | TIMESTAMP | CHECK: la disattivazione non può precedere l'attivazione. |
| `attivo` | BOOLEAN | default true. Gli account si **disattivano**, non si cancellano. |

`ruolo` è `'user'`, **non** `'utente'` — l'unica cucitura italiano/inglese nei dati, e
una fonte affidabile di INSERT falliti.

### `nodi` — i trasmettitori

| Colonna | Tipo | Note |
|---|---|---|
| `id_nodo` | VARCHAR(50) | PK — l'id con cui pubblica il firmware. |
| `nome_nodo`, `descrizione`, `posizione` | | Testo libero. |
| `data_registrazione` | TIMESTAMP | |
| `ultimo_messaggio` | TIMESTAMP | Quando è stato **ricevuto** l'ultimo messaggio MQTT; la imposta `services/ingest.py` — vedi [Niente viste, niente trigger](#niente-viste-niente-trigger). |
| `attivo` | BOOLEAN | Soft delete. |
| `configurazione` | JSONB | Impostazioni specifiche del nodo. |

**Non esiste una tabella `sensori`.** L'identità del sensore vive su
`arnie.id_sensore_fisico`, e le letture hanno colonne fisse anziché righe generiche
`(sensore, valore)`. Una tabella `sensori` è esistita fino al vecchio `migrate_v4.sql` scritto a mano: era il
modello alternativo, mai collegato ad `arnie` né letto da alcuna query.

### `arnie`

| Colonna | Tipo | Note |
|---|---|---|
| `id_arnia` | SERIAL | PK |
| `id_nodo` | VARCHAR(50) | FK → `nodi` ON DELETE CASCADE. |
| `id_sensore_fisico` | VARCHAR(50) | NOT NULL. **UNIQUE insieme a `id_nodo`** — quella coppia è il modo in cui l'ingest risolve una lettura sull'arnia. |
| `nome_arnia`, `descrizione`, `posizione` | | Testo libero. |
| `latitudine`, `longitudine` | DECIMAL(9,6) | Gradi decimali, opzionali. CHECK −90..90 e −180..180. |
| `data_installazione`, `data_rimozione` | TIMESTAMP | |
| `attiva` | BOOLEAN | Soft delete — le letture restano. |
| `metadati` | JSONB | Razza e anno della regina, colore dell'arnia, quello che l'apicoltore vuole tracciare. |

### `utenti_arnie` — chi può vedere quale arnia

| Colonna | Tipo | Note |
|---|---|---|
| `id` | SERIAL | PK |
| `id_utente`, `id_arnia` | INTEGER | FK, CASCADE. **UNIQUE insieme.** |
| `data_associazione`, `data_disassociazione` | TIMESTAMP | CHECK: la fine non può precedere l'inizio. |
| `permessi` | VARCHAR(20) | CHECK `('read','write','admin')`, default `read`. |
| `attivo` | BOOLEAN | La revoca è un flag, così resta lo storico. |

I permessi sono una scala: `read` < `write` < `admin`. Un account con `ruolo = 'admin'`
scavalca del tutto questa tabella.

### `letture` — la telemetria

| Colonna | Tipo | Note |
|---|---|---|
| `id_lettura` | BIGSERIAL | PK — `BIG` a ragion veduta: è la tabella che cresce. |
| `id_arnia` | INTEGER | FK → `arnie` CASCADE. |
| `id_nodo` | VARCHAR(50) | NOT NULL. Denormalizzata: quale nodo l'ha riportata, anche se l'arnia si sposta. |
| `timestamp` | TIMESTAMP | NOT NULL, default `CURRENT_TIMESTAMP`. **L'orologio del nodo**, quando ne manda uno. |
| `temperatura` | DECIMAL(5,2) | CHECK −50..100 |
| `umidita` | DECIMAL(5,2) | CHECK 0..100 |
| `peso` | DECIMAL(10,3) | CHECK ≥ 0 |
| `batteria` | DECIMAL(4,3) | CHECK 0..5. Tensione della batteria del nodo in V — la chiave nel payload è `bat`. |
| `dati_raw` | JSONB | Tutto il resto che il firmware vuole conservare. |

Tutte e quattro le misure sono nullable: un nodo che porta solo la bilancia è valido.
Indici: `id_arnia`, `timestamp DESC`, il composto `(id_arnia, timestamp DESC)` che usa
ogni query per i grafici, e `id_nodo`.

### `log_attivita` — cosa ha fatto l'apicoltore

| Colonna | Tipo | Note |
|---|---|---|
| `id_log` | BIGSERIAL | PK |
| `id_utente` | INTEGER | FK → `utenti` **ON DELETE SET NULL** — il record sopravvive all'account. |
| `id_arnia` | INTEGER | FK → `arnie` CASCADE. |
| `timestamp` | TIMESTAMP | Retrodatabile: l'ispezione si registra dopo essersi lavati le mani. |
| `tipo_attivita` | VARCHAR(50) | NOT NULL, CHECK su 8 valori: `ispezione`, `trattamento`, `raccolta_miele`, `nutrizione`, `sostituzione_regina`, `controllo_salute`, `manutenzione`, `altro`. |
| `descrizione` | TEXT | |
| `dati` | JSONB | Dettaglio strutturato — telaini di miele, covata presente, e così via. |

### `token_sessione` — inutilizzata, di proposito

I refresh token sono **JWT stateless** e non esiste un endpoint `/api/auth/refresh`,
quindi niente nell'applicazione legge o scrive questa tabella. Resta perché ha la forma
giusta per la funzionalità quando arriverà (revoca, `ip_address`, `user_agent`):
[issue #16](https://github.com/fablab-imperia/meshbee-server/issues/16).

## Niente viste, niente trigger

**Il database non contiene logica**: nessuna vista, nessun trigger, nessuna funzione
nostra. `tests/integration/test_migrations.py` fallisce se una migrazione ne lascia
qualcuna. Quello che stava qui ora sta in `meshbee_core`, dove è dichiarato una volta
sola e testato come il resto del codice:

- **L'elenco delle arnie con le ultime letture** era la vista `v_arnie_stato`. Ora è
  `repository/arnie.py::STATO`: `arnie LEFT JOIN nodi` più un'unica sottoquery
  `LATERAL` per l'ultima lettura, così ogni valore "ultimo" viene dalla stessa riga. È
  quello che restituisce `GET /api/user/arnie`.
- **`nodi.ultimo_messaggio`** veniva impostata da `trigger_aggiorna_nodo` a ogni insert
  in `letture`, con l'ora *dichiarata* dalla lettura e una UPDATE per riga
  ([issue #17](https://github.com/fablab-imperia/meshbee-server/issues/17)). Ora la
  imposta `services/ingest.py`, una volta per messaggio MQTT, con l'ora in cui è stato
  **ricevuto**. Un nodo con l'orologio sbagliato, o la riproduzione di letture
  accumulate, non può più farla tornare indietro, e un insert massivo in `letture` non
  tocca più `nodi`. Conta solo un messaggio del nodo: una lettura inserita dall'API, o
  quelle di esempio del seed, non la toccano.

Entrambi sono stati eliminati dalla revisione `0003`; il suo downgrade li ricrea.

Non sono mai esistite nemmeno viste `v_letture_recenti` o `v_serie_*` che valesse la
pena tenere — sono esistite fino al vecchio `migrate_v4.sql` e non sono mai state
interrogate. **Una vista non accetta parametri**, e leggere lo storico significa
arnia + intervallo + LIMIT, cioè `repository/letture.py::list_by_arnia` e `::series`.

## Cambiare lo schema

Modifica i modelli, poi genera una revisione dalla differenza:

```bash
# 1. Modifica meshbee_core/models.py (o una costante in limits.py).
# 2. Genera la revisione, contro un database all'ultima revisione:
docker-compose exec api alembic revision --autogenerate -m "add x to letture"
# 3. Leggi il nuovo file in meshbee_core/migrations/versions/ e completalo (sotto).
# 4. Applicala — o riavvia lo stack, che esegue prima `migrate`:
docker-compose run --rm migrate
```

**L'autogenerate non vede i vincoli CHECK.** Confronta tabelle, colonne, tipi,
nullabilità, indici e chiavi esterne; un limite cambiato in `limits.py` produce una
revisione vuota. Scrivi a mano la modifica del vincolo
(`op.drop_constraint` + `op.create_check_constraint`), con i valori **letterali**:
una revisione è storia e non deve importare `limits.py`, altrimenti rieseguirla dopo la
modifica successiva costruirebbe lo schema sbagliato. `tests/integration/test_migrations.py`
costruisce lo schema nei due modi — `create_all()` dai modelli e `upgrade head` dalle
revisioni — e fallisce, stampando le due definizioni, se qualcosa differisce.

Nemmeno viste, trigger e funzioni vengono confrontati — e non ce ne devono essere: la logica sta in `meshbee_core`.

### Installazioni esistenti

Un'installazione creata prima di Alembic ha le tabelle ma non `alembic_version`, e
`migrate` si rifiuta di toccarla. Se aveva applicate tutte le migrazioni scritte a mano
fino a `migrate_v5.sql`, è esattamente alla revisione di partenza — marcala una volta:

```bash
docker-compose exec postgres pg_dump -U beehive_user beehive_iot > backup.sql   # prima
docker-compose run --rm migrate alembic stamp 0001
docker-compose up -d
```

Un'installazione più vecchia della v5 deve prima applicare i `database/migrate_v*.sql`
mancanti; si trovano nella cronologia git prima del passaggio ad Alembic.

### Volumi nuovi

`POSTGRES_PASSWORD` vale ancora **solo quando la directory dati è vuota** — PostgreSQL
la imposta all'inizializzazione e poi ignora la variabile — e `postgres_data`
sopravvive a `docker-compose down`, alle ricostruzioni e ai riavvii. Per ripartire da
zero in sviluppo:

```bash
docker-compose down -v && docker-compose up -d      # DISTRUGGE tutte le letture
```

## Migrazioni

| Revisione | Cosa ha fatto |
|---|---|
| `0001` | Partenza: lo schema come l'hanno lasciato le migrazioni scritte a mano. |
| `0002` | NOT NULL sulle 16 colonne che l'API restituisce come obbligatorie. Prima riempie i NULL esistenti — i flag a **false**, `ruolo` a `user`, `permessi` a `read` con l'associazione disattivata, le date dalla migliore informazione presente nella riga — e **si ferma senza cambiare niente** se una chiave esterna è NULL (un'arnia senza nodo, una lettura senza arnia), perché quelle non si possono riempire. |
| `0003` | Eliminati `trigger_aggiorna_nodo`, la sua funzione e `v_arnie_stato`: la loro logica è passata a `services/ingest.py` e `repository/arnie.py` (#17). |

Prima di Alembic lo schema cambiava con script scritti a mano, applicati con `psql`;
sono nella cronologia git:

| File | Cosa ha fatto |
|---|---|
| `migrate_v2.sql` | Aggiunte `latitudine`/`longitudine` con i relativi CHECK; **rimosso del tutto il sistema di allarmi** (tabella `allarmi`, vista `v_allarmi_attivi`, funzione `controlla_soglie_allarmi`, trigger `trigger_controlla_allarmi`); ricostruita `v_arnie_stato` con le coordinate; create le viste `v_serie_*`. |
| `migrate_v3.sql` | Eliminata e ricreata `v_arnie_stato` con l'elenco completo e nell'ordine corretto — `CREATE OR REPLACE VIEW` non può riordinare né inserire colonne. |
| `migrate_v4.sql` | Eliminata la tabella `sensori` (con una guardia: solleva un errore se contiene righe) e le quattro viste inutilizzate (`v_serie_temperatura`, `v_serie_umidita`, `v_serie_peso`, `v_letture_recenti`). |
| `migrate_v5.sql` | Aggiunta `letture.batteria` (DECIMAL(4,3), CHECK 0..5) e accodata `ultima_batteria` a `v_arnie_stato`. |

Gli allarmi sono stati rimossi nella v2 e non torneranno in quella forma: le soglie
vanno dove si possono configurare per singola arnia, non scritte in un trigger.

## Dati di esempio

Le revisioni non portano dati. Su un'installazione senza nessuna arnia,
`scripts/seed.py` crea un nodo (`NODE001`, "Apiario Collina"), due arnie (`SENSOR01` /
`SENSOR02`) con coordinate e metadati, e quattro letture — quanto basta perché l'app
abbia qualcosa da disegnare. Appena esiste un'arnia qualsiasi non li tocca più, quindi
cancellare i dati di esempio non li fa ricomparire.

Il seed crea anche gli account, le associazioni e un'attività di esempio. Vedi il
[README](../README.it.md#installazione) principale.

## Sviluppo

```bash
docker-compose exec postgres psql -U beehive_user -d beehive_iot      # oppure: make db-shell
make db-backup                                                        # → backups/backup_<timestamp>.sql
make db-restore FILE=backups/backup_20260805_120000.sql
```

Utili una volta dentro:

```sql
\dt                                  -- le tabelle
\d+ letture                          -- una tabella, vincoli compresi
SELECT id_arnia, count(*), max(timestamp) FROM letture GROUP BY id_arnia;
```

```bash
docker-compose exec api alembic current      # a che revisione è il database
docker-compose exec api alembic history      # la catena
docker-compose exec api alembic check        # l'autogenerate troverebbe qualcosa?
```

I test che toccano l'SQL stanno in `tests/integration/` — i test dei repository
verificano nomi di colonna, join e ordine dei parametri contro un database reale,
`test_migrations.py` che le revisioni corrispondano ai modelli, e
`tests/integration/core/test_schemas.py` che il database e le forme API in `meshbee_core/models.py`
rifiutino gli stessi valori. Il database di test viene costruito con `upgrade head` a
ogni esecuzione. Vedi [`tests/`](../tests/README.it.md).

## Trappole

- **L'autogenerate non vede le modifiche ai CHECK.** Un nuovo limite in `limits.py`
  richiede una modifica del vincolo scritta a mano nella revisione; `test_migrations.py`
  fallisce finché non c'è.
- **Un'installazione precedente ad Alembic va marcata una volta.** Fino ad allora
  `migrate` la rifiuta, e quindi `api` e `mqtt-handler` non partono. Vedi
  [Installazioni esistenti](#installazioni-esistenti).
- **`POSTGRES_PASSWORD` vale solo su un volume nuovo.** Vedi [Volumi nuovi](#volumi-nuovi).
- **`ruolo` è `'user'`, `permessi` è `('read','write','admin')`.** I fake dei test
  accettano qualsiasi cosa; il database reale no.
- **Niente viene cancellato davvero.** Utenti, arnie e nodi hanno un flag
  `attivo`/`attiva`, e le letture restano quando la loro arnia viene dismessa.
  `ON DELETE CASCADE` è una rete di sicurezza, non un flusso di lavoro.
- **`nodi.ultimo_messaggio` è l'ora di ricezione, e la imposta solo MQTT.** Una lettura inviata dall'API non la tocca. Vedi [Niente viste, niente trigger](#niente-viste-niente-trigger).

## Collegamenti

- [`meshbee_core/`](../meshbee_core/README.it.md) — `repository/`, l'unico codice che scrive SQL.
- [`api/`](../api/README.it.md) — gli endpoint a cui rispondono queste tabelle.
- [`mqtt_handler/`](../mqtt_handler/README.it.md) — quello che riempie `letture`.
- [`tests/`](../tests/README.it.md) — come le migrazioni vengono tenute oneste.
- [README](../README.it.md) principale — lo stack nel suo insieme.
