# `database/` — schema PostgreSQL

*[English version](README.md)*

Lo schema, e le migrazioni che ci hanno portato qui. PostgreSQL 15, in esecuzione come
servizio `postgres`; i dati stanno nel volume `postgres_data`.

I nomi di dominio sono in italiano — `utenti`, `nodi`, `arnie`, `letture` — perché sono
il vocabolario del progetto, non una traduzione mancata.

## Contenuto

| Percorso | Cos'è |
|---|---|
| `init.sql` | Lo schema **attuale**. Montato su `/docker-entrypoint-initdb.d/init.sql`. |
| `migrate_v2.sql` | Dentro le coordinate, fuori gli allarmi. |
| `migrate_v3.sql` | Ricostruzione di `v_arnie_stato` con l'elenco completo delle colonne. |
| `migrate_v4.sql` | Rimozione della tabella `sensori` e delle viste inutilizzate. |
| `migrate_v5.sql` | Tensione della batteria del nodo: `letture.batteria`. |

**`init.sql` viene eseguito una volta sola, su un volume vuoto.** A ogni avvio
successivo PostgreSQL trova una directory dati già inizializzata e lo ignora del tutto —
è la cosa più sorprendente di questo setup, ed è trattata in
[Cambiare lo schema](#cambiare-lo-schema).

## Tabelle

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
| `ultimo_messaggio` | TIMESTAMP | **Scritta da un trigger. Non impostarla mai da Python** — vedi [Trigger](#trigger). |
| `attivo` | BOOLEAN | Soft delete. |
| `configurazione` | JSONB | Impostazioni specifiche del nodo. |

**Non esiste una tabella `sensori`.** L'identità del sensore vive su
`arnie.id_sensore_fisico`, e le letture hanno colonne fisse anziché righe generiche
`(sensore, valore)`. Una tabella `sensori` è esistita fino a `migrate_v4.sql`: era il
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

## Vista

**`v_arnie_stato` è l'unica vista**, e se lo merita: `arnie LEFT JOIN nodi` più cinque
sottoquery correlate per l'ultima `temperatura`, `umidita`, `peso`, `timestamp` e
`batteria` (in fondo, così una migrazione può accodarla). È
quello che restituisce `GET /api/user/arnie` — un elenco di arnie in cui ogni riga porta
già il proprio stato attuale.

Non esiste una `v_letture_recenti` e non esistono viste `v_serie_*`; sono esistite fino
a `migrate_v4.sql` e non sono mai state interrogate. Il motivo è strutturale: **una
vista non accetta parametri**. Leggere lo storico significa arnia + intervallo + LIMIT,
cioè `repository/letture.py::list_by_arnia` e `::series`. Una vista con finestra fissa a
7 giorni non li accetta, quindi incapsulerebbe tutto tranne la parte che conta.

## Trigger

Un solo trigger, `trigger_aggiorna_nodo`: `AFTER INSERT ON letture FOR EACH ROW`, che
imposta `nodi.ultimo_messaggio = NEW.timestamp`.

**`nodi.ultimo_messaggio` appartiene al database.** Scriverla da Python non serve a
niente — il trigger scatta dopo e ti sovrascrive. Registrare che un nodo si è fatto
sentire è compito della *lettura*, ed è per questo che `services/ingest.py` registra il
nodo senza toccare quella colonna.

Due difetti noti, entrambi tracciati nella
[issue #17](https://github.com/fablab-imperia/meshbee-server/issues/17):

- **Sorgente di orario sbagliata.** Copia il timestamp *dichiarato*, quindi un nodo con
  l'orologio sbagliato si segnala come fermo (o come se trasmettesse dal futuro).
  "Quando abbiamo sentito questo nodo l'ultima volta" dovrebbe essere ora del server.
- **`FOR EACH ROW` costa circa 55× sugli insert massivi.** Un backfill fa scattare una
  UPDATE per riga per un valore in cui conta solo l'ultima. `FOR EACH STATEMENT`
  risolverebbe.

## Cambiare lo schema

`init.sql` viene eseguito **solo quando la directory dati è vuota**. Lo stesso vale per
`POSTGRES_PASSWORD` — PostgreSQL la imposta all'inizializzazione e poi ignora la
variabile. E `postgres_data` sopravvive a `docker-compose down`, alle ricostruzioni e ai
riavvii.

Modificare `init.sql` su un'installazione già avviata quindi non cambia niente. Due
strade:

```bash
# Sviluppo: butta via i dati e riparti da zero.
docker-compose down -v && docker-compose up -d      # DISTRUGGE tutte le letture
```

```bash
# Con dati da tenere: scrivi una migrazione e applicala.
docker-compose exec -T postgres psql -U beehive_user -d beehive_iot < database/migrate_v5.sql
```

**Fai entrambe le cose**: una migrazione per le installazioni esistenti *e* la stessa
modifica in `init.sql`, che resta la descrizione di un database nuovo. Racchiudi una
migrazione in `BEGIN`/`COMMIT`, rendila idempotente e chiudila con una query che ne
verifichi il risultato — le quattro migrazioni esistenti fanno tutte e tre le cose.

`init.sql` non va alla deriva, perché la suite di test di integrazione elimina lo schema
e lo ricarica da questo file **a ogni esecuzione**. Un'istruzione che non compila più fa
fallire tutta la suite.

## Migrazioni

| File | Cosa ha fatto |
|---|---|
| `migrate_v2.sql` | Aggiunte `latitudine`/`longitudine` con i relativi CHECK; **rimosso del tutto il sistema di allarmi** (tabella `allarmi`, vista `v_allarmi_attivi`, funzione `controlla_soglie_allarmi`, trigger `trigger_controlla_allarmi`); ricostruita `v_arnie_stato` con le coordinate; create le viste `v_serie_*`. |
| `migrate_v3.sql` | Eliminata e ricreata `v_arnie_stato` con l'elenco completo e nell'ordine corretto — `CREATE OR REPLACE VIEW` non può riordinare né inserire colonne. |
| `migrate_v4.sql` | Eliminata la tabella `sensori` (con una guardia: solleva un errore se contiene righe) e le quattro viste inutilizzate (`v_serie_temperatura`, `v_serie_umidita`, `v_serie_peso`, `v_letture_recenti`). |
| `migrate_v5.sql` | Aggiunta `letture.batteria` (DECIMAL(4,3), CHECK 0..5) e accodata `ultima_batteria` a `v_arnie_stato`. |

Gli allarmi sono stati rimossi nella v2 e non torneranno in quella forma: le soglie
vanno dove si possono configurare per singola arnia, non scritte in un trigger.

## Dati di esempio

`init.sql` inserisce un nodo (`NODE001`, "Apiario Collina"), due arnie (`SENSOR01` /
`SENSOR02`) con coordinate e metadati, e quattro letture — quanto basta perché l'app
abbia qualcosa da disegnare su un'installazione nuova.

Account, associazioni e l'attività di esempio arrivano invece da `scripts/seed.py`,
perché servono hash bcrypt reali. Vedi il [README](../README.it.md#installazione)
principale.

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
SELECT * FROM v_arnie_stato;
SELECT id_arnia, count(*), max(timestamp) FROM letture GROUP BY id_arnia;
```

I test che toccano l'SQL stanno in `tests/integration/` — i test dei repository
verificano nomi di colonna, join e ordine dei parametri contro un database reale, e
`tests/integration/core/test_schemas.py` verifica che i limiti qui e i validatori in
`meshbee_core/schemas.py` siano ancora d'accordo. Vedi [`tests/`](../tests/README.it.md).

## Trappole

- **`init.sql` e `POSTGRES_PASSWORD` valgono solo su un volume nuovo.** Vedi
  [Cambiare lo schema](#cambiare-lo-schema).
- **Ogni CHECK qui è duplicato come validatore pydantic** in
  `meshbee_core/schemas.py`, senza niente che li colleghi. Se cambi uno cambia l'altro, e
  aggiungi un caso a `tests/integration/core/test_schemas.py`.
- **`ruolo` è `'user'`, `permessi` è `('read','write','admin')`.** I fake dei test
  accettano qualsiasi cosa; il database reale no.
- **Niente viene cancellato davvero.** Utenti, arnie e nodi hanno un flag
  `attivo`/`attiva`, e le letture restano quando la loro arnia viene dismessa.
  `ON DELETE CASCADE` è una rete di sicurezza, non un flusso di lavoro.
- **`nodi.ultimo_messaggio` è del trigger.** Vedi [Trigger](#trigger).

## Collegamenti

- [`meshbee_core/`](../meshbee_core/README.it.md) — `repository/`, l'unico codice che scrive SQL.
- [`api/`](../api/README.it.md) — gli endpoint a cui rispondono queste tabelle.
- [`mqtt_handler/`](../mqtt_handler/README.it.md) — quello che riempie `letture`.
- [`tests/`](../tests/README.it.md) — come `init.sql` viene tenuto onesto.
- [README](../README.it.md) principale — lo stack nel suo insieme.
