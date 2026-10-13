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
| `main.py` | L'applicazione: lifespan, CORS, traduzione degli errori e tutte le 62 rotte, e le pagine `/reset-password` e `/invite`. |
| `auth.py` | Emissione e verifica dei JWT, e le dipendenze FastAPI che proteggono le rotte. |
| `mail.py` | `get_mailer` e `send_later`: le email fuori dal percorso della richiesta — vedi [Configurazione](#configurazione). |
| `ratelimit.py` | Limiti alle richieste, in memoria: per indirizzo client sulla rotta di password dimenticata ([Reimpostare la password](#reimpostare-la-password)), per utente sulla condivisione. |
| `paging.py` | I parametri opzionali `limit`/`offset` delle rotte di elenco, e il loro header `X-Total-Count` — vedi [Paginazione](#paginazione). |
| `config.py` | `Settings(CoreSettings)` — JWT, metadati dell'API e CORS sopra ai campi del database. |
| `openapi.json` | Il contratto API generato. **Committato** — vedi [Contratto OpenAPI](#contratto-openapi). |
| `Dockerfile` | Immagine del servizio `api` (e di `seed`). Il contesto di build è la root del repo. |
| `requirements.txt` | Dipendenze di runtime. |
| `requirements-dev.txt` | Dipendenze di test — nella stessa immagine, così un solo container esegue la suite. |

## Endpoint

62 operazioni. La colonna `Auth` dice cosa deve portare una richiesta:

- **nessuna** — pubblico.
- **utente** — un bearer token valido di un account attivo (`get_current_active_user`).
- **admin** — quanto sopra *più* `ruolo = 'admin'` (`get_current_admin_user`).
- **utente + viewer / collaborator / manager / owner** — quanto sopra *più* almeno
  quell'accesso all'apiario dell'arnia (o all'apiario stesso): esserne proprietario, o
  un ruolo condiviso dal proprietario. Vedi
  [Autenticazione e autorizzazione](#autenticazione-e-autorizzazione). Gli admin passano
  il controllo comunque.

**Paginata** marca una rotta di elenco che accetta `limit` e `offset` — vedi [Paginazione](#paginazione).

### Autenticazione

| Metodo | Percorso | Auth | Scopo |
|---|---|---|---|
| POST | `/api/auth/login` | nessuna | Scambia email + password per un access e un refresh token. |
| POST | `/api/auth/refresh` | nessuna | Scambia un refresh token per un nuovo access e refresh token; il vecchio è consumato. |
| POST | `/api/auth/logout` | nessuna | Revoca un refresh token. Risponde sempre 200. |
| POST | `/api/auth/password/forgot` | nessuna | Invia per email un link monouso per reimpostare la password. Sempre 202 con lo stesso corpo; 429 oltre il limite per IP; 503 senza email. Vedi [Reimpostare la password](#reimpostare-la-password). |
| POST | `/api/auth/invite/accept` | nessuna | Crea un account da un invito a un apiario (`token`, `nome`, `cognome`, `password`) e lo collega: restituisce i token del login. Un solo 400 per link sconosciuto, scaduto, usato o ritirato. Vedi [Inviti](#inviti). |
| POST | `/api/auth/password/reset` | nessuna | Imposta una nuova password con il token ricevuto per email. Un solo 400 per token sconosciuto, scaduto o già usato. |
| GET | `/api/auth/me` | utente | L'account autenticato. |

### Utente

Tutto quello sotto `/api/user/arnie/{id_arnia}` e `/api/user/apiari/{id_apiario}` è protetto
sull'accesso del chiamante all'apiario di quell'arnia, o a quell'apiario.

| Metodo | Percorso | Auth | Scopo |
|---|---|---|---|
| GET | `/api/user/arnie` | utente | Le arnie degli apiari di cui il chiamante è proprietario o che gli sono condivisi, ciascuna con l'ultima lettura, il suo apiario e `accesso` (l'accesso del chiamante). `id_apiario` opzionale la restringe a un apiario. **Paginata**. |
| GET | `/api/user/arnie/{id_arnia}` | utente + viewer | Una singola arnia con l'ultima lettura. |
| PUT | `/api/user/arnie/{id_arnia}` | utente + manager | Rinomina/riposiziona un'arnia. `attiva` (dismetterla) vale solo per il proprietario. |
| PUT | `/api/user/arnie/{id_arnia}/apiario` | utente + owner | Sposta l'arnia in un altro apiario del suo proprietario. Chi può vederla segue l'apiario. |
| GET | `/api/user/arnie/{id_arnia}/letture` | utente + viewer | Letture. `data_inizio`, `data_fine`, `limit` (1–10000, default 1000). **Paginata**. |
| GET | `/api/user/arnie/{id_arnia}/letture/temperatura` | utente + viewer | Solo `{timestamp, temperatura}` — dimensionato per i grafici. |
| GET | `/api/user/arnie/{id_arnia}/letture/umidita` | utente + viewer | Solo `{timestamp, umidita}`. |
| GET | `/api/user/arnie/{id_arnia}/letture/peso` | utente + viewer | Solo `{timestamp, peso}`. |
| GET | `/api/user/arnie/{id_arnia}/letture/batteria` | utente + viewer | Solo `{timestamp, batteria}` — tensione della batteria del nodo. |
| GET | `/api/user/arnie/{id_arnia}/attivita` | utente + viewer | Log attività. `data_inizio`, `data_fine`, `tipo_attivita`, `limit` (1–1000, default 100). **Paginata**. |
| POST | `/api/user/arnie/{id_arnia}/attivita` | utente + collaborator | Registra un'attività. |
| PATCH | `/api/user/arnie/{id_arnia}/attivita/{id_log}` | utente + collaborator | Modifica un'attività — **solo le proprie**. |
| DELETE | `/api/user/arnie/{id_arnia}/attivita/{id_log}` | utente + collaborator | Elimina un'attività — **solo le proprie**. |
| PUT | `/api/user/password` | utente | Cambia la propria password. Richiede `current_password`. |
| GET | `/api/user/apiari` | utente | Gli apiari di cui il chiamante è proprietario (prima quello predefinito), poi quelli condivisi con lui, ciascuno con `accesso`. **Paginata**. |
| POST | `/api/user/apiari` | utente | Crea un apiario del chiamante. |
| GET | `/api/user/apiari/{id_apiario}` | utente + viewer | Un singolo apiario. |
| PUT | `/api/user/apiari/{id_apiario}` | utente + manager | Lo modifica — anche quello predefinito. |
| DELETE | `/api/user/apiari/{id_apiario}` | utente + owner | Lo elimina, con le sue condivisioni. **409** per quello predefinito, e finché contiene arnie attive. |
| GET | `/api/user/apiari/{id_apiario}/condivisioni` | utente + owner | Con chi è condiviso, e con quale ruolo: condivisioni attive (`stato: attiva`, con `id_utente`) e inviti in attesa (`stato: in_attesa`, con `id_invito`), per email. **Paginata**. |
| POST | `/api/user/apiari/{id_apiario}/condivisioni` | utente + owner | Lo condivide con un'`email`, come `viewer` (default), `collaborator` o `manager`. Un'email senza account riceve un invito in attesa. La risposta (`id_apiario`, `email`, `ruolo`) è la stessa in entrambi i casi. Con l'email attiva, un account riceve un avviso e un invito un link per registrarsi. Condividerlo di nuovo cambia il ruolo. **429** oltre `SHARE_MAX_PER_HOUR`. |
| PUT | `/api/user/apiari/{id_apiario}/condivisioni/{id_utente}` | utente + owner | Cambia il ruolo di quell'utente. |
| DELETE | `/api/user/apiari/{id_apiario}/condivisioni/{id_utente}` | utente + owner | Smette di condividerlo con quell'utente. |
| PUT | `/api/user/apiari/{id_apiario}/inviti/{id_invito}` | utente + owner | Cambia il ruolo di un invito in attesa. |
| POST | `/api/user/apiari/{id_apiario}/inviti/{id_invito}/reinvia` | utente + owner | Invia di nuovo l'invito con un link nuovo; il vecchio smette di funzionare. 202; **429** oltre `INVITE_MAX_PER_DAY`; **503** senza email. |
| DELETE | `/api/user/apiari/{id_apiario}/inviti/{id_invito}` | utente + owner | Ritira un invito in attesa. Se nessun altro apiario aspetta quell'email, il suo link smette di funzionare. |

I quattro endpoint di serie esistono perché a un grafico servono due colonne su una riga di
nove; scartano le righe in cui il campo è NULL. L'elenco dei campi accettati è una
whitelist in `meshbee_core/repository/letture.py`, non un'interpolazione di stringhe.

### Admin

| Metodo | Percorso | Auth | Scopo |
|---|---|---|---|
| GET | `/api/admin/utenti` | admin | Tutti gli account. **Paginata**. |
| POST | `/api/admin/utenti` | admin | Crea un account. |
| PUT | `/api/admin/utenti/{id_utente}` | admin | Aggiorna un account. |
| DELETE | `/api/admin/utenti/{id_utente}` | admin | Disattiva (soft delete). **Non puoi disattivare te stesso.** |
| PUT | `/api/admin/utenti/{id_utente}/password` | admin | Reimposta la password di qualcuno — senza `current_password`. |
| GET | `/api/admin/nodi` | admin | Tutti i nodi. **Paginata**. |
| POST | `/api/admin/nodi` | admin | Registra un nodo. |
| GET | `/api/admin/nodi/{id_nodo}` | admin | Un singolo nodo. |
| PUT | `/api/admin/nodi/{id_nodo}` | admin | Aggiorna un nodo (il body è un `NodoCreate` completo). |
| DELETE | `/api/admin/nodi/{id_nodo}` | admin | Disattiva. Arnie e letture restano. |
| PUT | `/api/admin/nodi/{id_nodo}/proprietario` | admin | Assegna il nodo a un utente (`id_utente`), lo trasferisce, o lo libera (`null`). Le sue arnie passano nell'apiario predefinito del nuovo proprietario. |
| GET | `/api/admin/arnie` | admin | Tutte le arnie, comprese quelle dismesse. `id_apiario` opzionale. **Paginata**. |
| POST | `/api/admin/arnie` | admin | Crea un'arnia. Finisce nell'apiario predefinito del proprietario del nodo, o in `id_apiario` se è di quel proprietario; l'arnia di un nodo non assegnato non è assegnata. |
| GET | `/api/admin/arnie/{id_arnia}` | admin | Una singola arnia con l'ultima lettura. |
| PUT | `/api/admin/arnie/{id_arnia}` | admin | Aggiorna un'arnia — **`attiva` compresa**, a differenza della rotta utente. |
| DELETE | `/api/admin/arnie/{id_arnia}` | admin | Disattiva. Le letture storiche restano. |
| GET | `/api/admin/apiari` | admin | Gli apiari di tutti gli utenti. `id_utente` opzionale. **Paginata**. |
| POST | `/api/admin/apiari` | admin | Crea un apiario per l'utente indicato in `id_utente_proprietario`. |
| GET | `/api/admin/apiari/{id_apiario}` | admin | L'apiario di un utente qualsiasi. |
| PUT | `/api/admin/apiari/{id_apiario}` | admin | Modifica l'apiario di un utente qualsiasi. |
| DELETE | `/api/admin/apiari/{id_apiario}` | admin | Elimina l'apiario di un utente qualsiasi, con le regole del proprietario (**409** come sopra). |
| GET | `/api/admin/letture` | admin | Tutte le letture. `limit` 1–10000, default 1000. **Paginata**. |
| POST | `/api/admin/letture` | admin | Inserisce una lettura a mano — backfill e test. |
| PATCH | `/api/admin/letture/{id_lettura}` | admin | Corregge una lettura: cambiano solo i campi inviati, una misura inviata come `null` viene cancellata, `timestamp` no. Arnia e nodo non si modificano. **404** se non esiste. |
| DELETE | `/api/admin/letture/{id_lettura}` | admin | Elimina una lettura (eliminazione vera). **404** se non esiste. |
| POST | `/api/admin/letture/elimina` | admin | Elimina letture in blocco: `{"id_letture": [...]}`, da 1 a 10000 id. Gli id inesistenti vengono saltati; il messaggio dice quante ne sono state eliminate. Si scelgono con i filtri per arnia e data di `GET /api/user/arnie/{id_arnia}/letture`. |
| GET | `/api/admin/attivita` | admin | Tutte le attività. `limit` 1–1000, default 100. **Paginata**. |

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

## Paginazione

Le 11 rotte marcate **Paginata** qui sopra accettano `limit` e `offset`
([api/paging.py](paging.py)). Sono entrambi opzionali, e una richiesta senza nessuno dei
due riceve esattamente quello che la rotta restituiva prima della paginazione: l'elenco
intero, o le `limit` letture e attività più recenti.

| Parametro | Significato |
|---|---|
| `offset` | Righe da saltare, ≥ 0, default 0. |
| `limit` | Righe da restituire al massimo. Letture e attività mantengono default e massimo (sopra); gli altri elenchi sono interi per default, al massimo 1000 per pagina. |

Una richiesta con uno dei due parametri riceve anche **`X-Total-Count`**: la dimensione
dell'intero elenco, filtri applicati. Costa una query COUNT, ed è per questo che una
richiesta senza parametri di paginazione non la paga. CORS espone l'header, così un
browser su un'altra origine può leggerlo. Il corpo resta in ogni caso il semplice
elenco JSON. `openapi.json` dichiara l'header nella risposta 200 di ogni rotta paginata.

```http
GET /api/admin/utenti?limit=25&offset=50

200 OK
X-Total-Count: 132

[ ... ]
```

Ogni ordinamento paginato termina su una colonna unica (l'id, o l'email per le
condivisioni), così pagine consecutive non ripetono né saltano righe con lo stesso
timestamp o nome. Un offset oltre la fine è una pagina vuota, sempre con il suo totale.
Le serie per i grafici (`/letture/{grandezza}`) non sono paginate: la finestra di date e
`limit` le limitano già.

## Autenticazione e autorizzazione

Il login restituisce due JWT firmati HS256 con `JWT_SECRET_KEY`. Il claim che
identifica il chiamante è `sub` (l'email); la riga dell'utente viene riletta dal
database a **ogni** richiesta, quindi disattivare un account ha effetto immediato senza
aspettare la scadenza del token. Un refresh token porta anche un `jti` univoco. Il refresh non si fida
del suo `sub`: trova l'utente tramite la riga del token in `token_sessione`, quindi
cambiare l'email dell'account non lo rompe.

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

La condivisione risponde allo stesso modo che l'email abbia un account o no
([#40](https://github.com/fablab-imperia/meshbee-server/issues/40)): un'email
sconosciuta riceve un **invito in attesa** (`inviti_apiari`), che diventa una
condivisione appena viene creato un account con quell'email, o un account esistente la
prende. L'elenco delle condivisioni mostra quali voci sono in attesa, così il
proprietario si accorge di un indirizzo sbagliato. Quello che impedisce di usarlo per
provare indirizzi in massa è il limite per utente, `SHARE_MAX_PER_HOUR` (30 di default,
in memoria come quello del reset). Le voci identificano le persone solo con l'email
scritta dal proprietario: nessun nome.

Tre cose da sapere sui token:

- **Un refresh token funziona una volta sola.** Ognuno di quelli emessi da login o
  refresh è registrato in `token_sessione` (come SHA-256, mai il token in chiaro).
  - `/api/auth/refresh` lo consuma e risponde con una nuova coppia; il client deve
    conservare il nuovo refresh token.
  - Ripresentare un token già consumato o chiuso col logout vuol dire che ne esiste una
    copia, quindi **tutte le sessioni di quell'account vengono revocate** e l'utente
    rifà il login.
  - **Un client deve avere un solo refresh in corso.** Anche due refresh con lo stesso
    token nello stesso momento contano come riuso: uno vince, l'altro viene rifiutato e
    disconnette l'utente ovunque. Quando più richieste ricevono un 401 insieme, devono
    aspettare tutte lo stesso refresh.
  - Il refresh risponde con lo stesso 401 per un token sconosciuto, scaduto, consumato o
    revocato e per un account disattivato.
  - Refresh e logout ricevono il refresh token nel body e nessun header `Authorization`,
    perché a quel punto l'access token di solito è scaduto.
- **Cosa revoca un refresh token:** il logout, la disattivazione dell'account (`PUT`
  con `attivo: false`, o `DELETE`) e una nuova password (`PUT /api/user/password`, o il
  reset dell'admin). Gli access token restano stateless: funzionano finché non scadono
  dopo `ACCESS_TOKEN_EXPIRE_MINUTES`. L'eccezione è un account disattivato, perché
  `get_current_user` rilegge l'utente a ogni richiesta.
  ([#16](https://github.com/fablab-imperia/meshbee-server/issues/16))
- **Un database irraggiungibile non è un errore di credenziali.** `authenticate_user`
  trasforma qualsiasi `SQLAlchemyError` in **503** invece di lasciarla arrivare al 401,
  così un database giù non somiglia mai a una password sbagliata.

Il login risponde con lo stesso 401 per email sconosciuta, password sbagliata e account
disattivato — una sola risposta per ogni modo di fallire, così l'endpoint non può essere
usato per enumerare le email registrate.

## Reimpostare la password

Chi ha dimenticato la password chiede un link su `/reset-password` (collegata dal login
admin), o dall'app tramite `POST /api/auth/password/forgot`
([#54](https://github.com/fablab-imperia/meshbee-server/issues/54)). La logica è in
`meshbee_core/services/password_reset.py`, sopra la tabella `token_monouso`.

- **Stessa risposta per ogni indirizzo.** `forgot` risponde 202 con lo stesso corpo sia
  che l'account esista, sia disattivato o abbia raggiunto il suo limite. Solo un account
  attivo riceve qualcosa, dopo la risposta.
- **Il token** è di 256 bit casuali (non un JWT), monouso, e vale
  `PASSWORD_RESET_EXPIRE_MINUTES`. Se ne salva solo lo SHA-256. Una nuova richiesta
  consuma il link precedente dell'account, e un reset li consuma tutti.
- **Il link** è `{PUBLIC_BASE_URL}/reset-password#token=…`. Il token sta nel frammento,
  quindi non arriva mai nei log dell'API o di Caddy e non viene mai inviato come Referer.
  La pagina lo toglie dalla barra degli indirizzi appena letto. Il link non viene mai
  costruito dall'`Host` della richiesta, che il chiamante controlla.
- **Un reset disconnette ogni dispositivo**: revoca tutti i refresh token dell'account,
  come ogni nuova password. Gli access token già emessi restano validi finché non
  scadono (`ACCESS_TOKEN_EXPIRE_MINUTES`).
- **Avvisi**: un reset riuscito, e un cambio tramite `PUT /api/user/password`, mandano
  all'account un breve avviso "la tua password è stata cambiata" quando l'email è attiva.
- **Limiti**: al massimo `PASSWORD_RESET_MAX_PER_ACCOUNT` email per account all'ora,
  contate nel database. Al massimo `PASSWORD_RESET_MAX_PER_IP` richieste per indirizzo
  client all'ora, contate in memoria (`ratelimit.py`), quindi per processo dell'API e
  azzerate da un riavvio.
- **Senza email** (`SMTP_HOST` o `PUBLIC_BASE_URL` non impostate), `forgot` risponde 503
  e dice di rivolgersi a un amministratore; `PUT /api/admin/utenti/{id}/password`
  funziona come prima. Un link inviato prima di spegnere l'email funziona ancora.

Né il token né il link finiscono mai nei log.

## Inviti

Condividere un apiario con un'email senza account salva un invito in attesa (#40). Con
l'email attiva, la persona invitata riceve anche un link per creare il suo account
([#55](https://github.com/fablab-imperia/meshbee-server/issues/55)). La logica è in
`meshbee_core/services/invitations.py`, sopra `inviti_apiari` e `token_monouso`.

- **Ci si registra solo su invito.** `POST /api/auth/invite/accept` crea un account con
  ruolo `user` per l'indirizzo a cui è arrivato l'invito; la persona non può sceglierne un
  altro. Ogni apiario condiviso con quell'indirizzo diventa suo subito, e viene collegata.
  Non c'è registrazione aperta
  ([#62](https://github.com/fablab-imperia/meshbee-server/issues/62)).
- **Il link** è `{PUBLIC_BASE_URL}/invite#token=…`, vale `INVITE_EXPIRE_DAYS` e si usa
  una volta. Funziona come quello del reset: 256 bit casuali, se ne salva solo lo
  SHA-256, e il token resta nel frammento. Non compare mai nella risposta della
  condivisione, quindi lo ha solo la casella invitata. Un link per indirizzo: invitare di
  nuovo, a qualsiasi apiario, o reinviare, lo sostituisce. Ritirare l'ultimo invito a un
  indirizzo lo annulla.
- **Un account esistente** riceve invece un avviso: "*mittente* ha condiviso con te
  l'apiario *nome* come *ruolo*", con un link a `PUBLIC_BASE_URL` quando è impostato.
  Solo una condivisione nuova lo invia: condividere di nuovo per cambiare il ruolo no.
- **Limiti**, così un utente non può consumare la quota giornaliera del provider e con
  essa i reset della password di tutti: al massimo `INVITE_MAX_PER_DAY` email di invito
  per utente, contate nel database, e `NOTICE_MAX_PER_DAY` avvisi, contati in memoria
  (gli avvisi non vengono salvati). Oltre l'uno o l'altro, la condivisione funziona e
  risponde come sempre (#40) ma non invia nulla, e il reinvio risponde 429.
  `SHARE_MAX_PER_HOUR` limita ogni richiesta di condivisione.
- **Senza email**, o senza `PUBLIC_BASE_URL` per i link degli inviti, la condivisione
  funziona come descritto in #40 e non invia nulla. Il reinvio risponde 503. Un invito
  diventa comunque una condivisione quando un admin crea l'account.

Le email non contengono dati del mittente oltre al suo nome e al nome dell'apiario,
ciascuno ridotto a una riga di al massimo 60 caratteri, così un nome scelto da un utente
non può portare un messaggio suo. Una condivisione è verso **un solo** indirizzo: una
lista come `a@x.org, b@y.org` è un 422, perché sarebbe un invito che raggiunge molte
persone oltre i limiti. Anche il mailer rifiuta tutto il resto.

## Traduzione degli errori

I service sollevano il vocabolario di `meshbee_core.errors` e non sanno nulla di HTTP.
Il context manager `db_operation` in `main.py` è l'unico punto in cui i due vocabolari
si incontrano:

| Sollevato | Diventa |
|---|---|
| `NotFound` | 404 |
| `Conflict` | 409 |
| `InvalidData` | 400 |
| `Unavailable` (il server di posta ha fallito) | 503 |
| `SQLAlchemyError` durante il login | 503 |
| qualsiasi altra cosa | 500 `Errore interno del server`, con l'errore vero nel log |

Il corpo del 500 resta volutamente vago: il testo dell'eccezione può nominare tabelle e
colonne.

## Pagina admin

`main.py` serve la pagina admin statica su `/admin/`: `StaticFiles` su
[`admin/`](../admin/README.it.md) nella root del repo (`ADMIN_DIR`). È un client delle
rotte qui sopra e non ne aggiunge di proprie. Cosa fa e come è fatta sta nel suo
README.

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
| `SMTP_HOST` | str | non impostata = email disattivata |
| `SMTP_PORT` | int | non impostata = 465 / 587 / 25 secondo `SMTP_SECURITY` |
| `SMTP_SECURITY` | `ssl` \| `starttls` \| `none` | `starttls` |
| `SMTP_USER` | str | non impostata = nessun login |
| `SMTP_PASSWORD` | secret | non impostata; obbligatoria con `SMTP_USER` |
| `SMTP_TIMEOUT` | float | `10` |
| `MAIL_FROM` | str | non impostata; obbligatoria con `SMTP_HOST` |
| `PUBLIC_BASE_URL` | str | non impostata; lo `/` finale viene tolto |
| `PASSWORD_RESET_EXPIRE_MINUTES` | int | `30` (al massimo 1440) |
| `PASSWORD_RESET_MAX_PER_ACCOUNT` | int | `3` all'ora |
| `PASSWORD_RESET_MAX_PER_IP` | int | `10` all'ora |
| `SHARE_MAX_PER_HOUR` | int | `30` richieste di condivisione per utente |
| `INVITE_EXPIRE_DAYS` | int | `7` (al massimo 30) |
| `INVITE_MAX_PER_DAY` | int | `20` email di invito per utente |
| `NOTICE_MAX_PER_DAY` | int | `20` avvisi di condivisione per utente |

`CORS_ORIGINS` è una lista, quindi dall'ambiente va passata in **JSON**, non come
stringa separata da virgole:

```bash
CORS_ORIGINS=["https://app.example.org","https://admin.example.org"]
```

`["*"]` con `allow_credentials=True` va bene in sviluppo ed è sbagliato in un
deployment pubblico — lì va ristretta.

Le impostazioni email sono spiegate nel
[README](../README.it.md#email-in-uscita) principale. Nel codice, `mail.py` fornisce
`get_mailer`, una dependency che vale `None` finché l'email è spenta (i test la
sostituiscono con un fake), e `send_later`, che mette in coda un messaggio sui
`BackgroundTasks`. Il messaggio parte dopo la risposta e, se l'invio fallisce, l'errore
finisce nel log e il client non lo vede mai.
`python -m scripts.send_test_mail <destinatario>` verifica una configurazione da capo a fondo.

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
- **L'immagine non contiene solo l'API.** Porta anche `admin/` (servita su `/admin/`),
  `mqtt_handler/`, `scripts/` e `tests/` più `paho-mqtt`, così l'intera suite — entrambi gli entry point compresi —
  gira in questo unico container. Per questo il contesto di build è la root del repo e
  non `api/`.
- **Il servizio `seed` usa questa stessa immagine**, con `python -m scripts.seed`.
- **Un `/health` che risponde 200 non dice niente.** Leggi `status` nel corpo.

## Collegamenti

- [`meshbee_core/`](../meshbee_core/README.it.md) — i service e gli schemi che ogni handler chiama.
- [`mqtt_handler/`](../mqtt_handler/README.it.md) — l'altro scrittore dello stesso database.
- [`admin/`](../admin/README.it.md) — la pagina admin che questa API serve su `/admin/`.
- [`tests/`](../tests/README.it.md) — come eseguire la suite e dove va un test nuovo.
- [`database/`](../database/README.it.md) — le tabelle dietro queste risposte.
- [README](../README.it.md) principale — lo stack nel suo insieme.
