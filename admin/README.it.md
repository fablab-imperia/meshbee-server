# `admin/` — pagina admin

*[English version](README.md)*

Una piccola **pagina statica per gli amministratori**, servita dall'API su `/admin/`
([#41](https://github.com/fablab-imperia/meshbee-server/issues/41)). Copre:

- una panoramica: conteggi e i nodi attivi silenziosi da 24 ore;
- utenti, nodi, arnie e apiari: elencare, creare, modificare e disattivare;
- assegnare il proprietario di un nodo e spostare un'arnia in un altro apiario del suo
  proprietario;
- reimpostare una password;
- letture, come tabella o come grafici, e attività;
- con chi è condiviso un apiario;
- letture a mano: inserirne una, correggerne una, eliminarle una alla volta o come
  selezione
  ([#42](https://github.com/fablab-imperia/meshbee-server/issues/42),
  [#21](https://github.com/fablab-imperia/meshbee-server/issues/21)).

Swagger UI su `/docs` resta il ripiego completo.

È **un client dell'API, non una seconda API**:

- Fa il login con `/api/auth/login`, rifiuta un account non admin dopo `/api/auth/me` e
  da lì chiama le stesse rotte di qualsiasi altro client, con il bearer token.
- Non aggiunge rotte, né sessioni né logica. Soft delete, hash delle password,
  trasferimento dei nodi e validazione avvengono nei service, e su un 4xx la pagina
  mostra il `detail` dell'API.
- Legge gli elenchi di valori (`ruolo`, i ruoli sugli apiari, `tipo_attivita`) da
  `/openapi.json`, così restano dichiarati una sola volta, in `meshbee_core/limits.py`.

## Contenuto

| File | Cos'è |
|---|---|
| `index.html` | Il markup, con i binding di [Alpine.js](https://alpinejs.dev). |
| `resources.js` | `RESOURCES`: per ogni scheda, la rotta, le colonne, i campi dei form e le azioni sulle righe. Una nuova operazione admin di solito è una voce qui. |
| `admin.js` | Il nucleo dell'unico componente Alpine: login, richieste, la tabella e il form generico guidati da `RESOURCES`. `admin()` vi unisce i file di funzionalità qui sotto. |
| `overview.js`, `charts.js`, `shares.js`, `pagination.js`, `url.js` | Una funzionalità ciascuno, con il proprio stato: la scheda Panoramica, i grafici delle letture, il pannello di condivisione di un apiario, la paginazione sotto ogni tabella e la vista tenuta nell'URL. Una nuova funzionalità con stato proprio ha un file come questi, non altri rami in `admin.js`. |
| `admin.css` | Il poco che [Pico CSS](https://picocss.com) non copre. |
| `vendor/` | Alpine.js e Pico CSS, **inclusi nel repo** con la versione nel nome del file. Per aggiornarli vedi [Trappole](#trappole). |

## Come viene servita

La pagina non ha un server suo. `api/main.py` monta questa directory su `/admin` con
`StaticFiles` (`ADMIN_DIR`), così la pagina condivide l'origine dell'API. Per questo
chiama `/api/...` e `/openapi.json` come semplici percorsi e non le servono né CORS né
un URL dell'API.

- In sviluppo `docker-compose.yml` monta `./admin` nel container `api`, così una
  modifica si vede alla richiesta successiva. Nessun riavvio, e `--reload` non c'entra.
- `api/Dockerfile` copia `admin/` nell'immagine, accanto ad `api/`.
- Senza il proxy Caddy la pagina è su <http://localhost:8000/admin/>. Con
  [`make certs`](../README.it.md#https-locale) è anche su <https://localhost:8443/admin/>.

## Funzionalità

- **Un'arnia scelta nelle schede letture o attività** fa passare l'elenco alla rotta
  `/api/user/arnie/{id_arnia}/…` dell'arnia. È la rotta con i filtri per data, e gli
  admin ne superano i controlli.
- **Eliminare le letture di un'arnia in un periodo:**
  1. Filtrare per arnia e date.
  2. Spuntare la casella dell'intestazione.
  3. Premere **Seleziona tutte**.
  4. Eliminare la selezione.

  La casella dell'intestazione copre solo la pagina mostrata. Seleziona tutte recupera
  in una richiesta ogni lettura che i filtri trovano, fino a 10000, il massimo che
  un'eliminazione multipla accetta.
- **La tabella principale è paginata sul server**, 25 righe per cominciare.
  - Ogni pagina è una richiesta con `limit` e `offset`, e
    [`X-Total-Count`](../api/README.it.md#paginazione) dimensiona la paginazione.
  - Cambiare pagina ricarica solo le righe.
  - Cambiare un filtro riporta a pagina 1. Aggiorna e un salvataggio mantengono la
    pagina.
  - Gli elenchi dietro le select e le celle leggibili (utenti, apiari, arnie, nodi) si
    caricano ancora interi, così i nodi silenziosi e le condivisioni di un apiario sono
    paginati nel browser.
- **Le Condivisioni di un apiario** usano le rotte del proprietario
  `/api/user/apiari/{id_apiario}/condivisioni`, che gli admin superano anch'esse. Non
  esistono copie admin. Lo stesso vale per **Sposta** di un'arnia, tramite
  `PUT /api/user/arnie/{id_arnia}/apiario`.
- **I grafici** caricano le proprie letture, perché la tabella ne contiene solo una
  pagina.
  - Disegnano le letture dell'arnia scelta nel periodo scelto (l'ultimo anno senza
    date), fino alle 10000 più recenti.
  - Sono SVG inline, senza librerie di grafici.
  - Un valore mancante interrompe la linea, così una misura che l'ingest ha messo a null
    appare come un buco.
- **La scheda Panoramica** si calcola dagli elenchi che ogni scheda carica già. Non fa
  richieste proprie.
- **L'hash dell'URL indica la vista**: la scheda, i suoi filtri, pagina e dimensione della
  tabella principale e il passaggio ai grafici. Per esempio:
  `#/letture?id_arnia=3&page=2&grafico=1`.
  - Ogni passo è una voce della cronologia, così Indietro lo annulla.
  - Un ricaricamento o un link copiato aprono la stessa vista dopo il login.
  - Sono una trentina di righe in `url.js`, senza librerie di routing. Le schede
    condividono una sola tabella, quindi template per rotta non avrebbero niente da
    contenere.
- **Il token sta in `sessionStorage`**, quindi sparisce chiudendo la scheda. Non c'è
  refresh ([#16](https://github.com/fablab-imperia/meshbee-server/issues/16)): quando il
  token scade, la richiesta successiva riceve un 401 e la pagina chiede di nuovo il
  login.

## Sviluppo

**Niente build e niente npm.** Si modificano i file e si ricarica il browser.

I controlli girano con il resto della suite:

```bash
docker-compose exec api pytest tests/unit/admin
```

`tests/unit/admin/test_admin_page.py` controlla tre cose:

- la pagina viene servita;
- ogni asset locale citato da `index.html` viene servito;
- nessun file della pagina inserisce markup (vedi [Trappole](#trappole)).

Il resto richiede un browser. Accedi con l'account admin di `.env`.

## Trappole

- **I dati arrivano nel DOM solo tramite `x-text`**, che li fa escape. I nomi li scrivono
  gli utenti; `x-html` o `innerHTML` permetterebbero a un nome di eseguire script con il
  token dell'admin. Il test fallisce con l'uno o l'altro, in `index.html` o in qualsiasi
  `*.js` di qui.
- **Aggiornare una libreria inclusa:** si sostituisce il file in `vendor/` e il suo
  riferimento in `index.html`. La versione nel nome del file è voluta: niente CDN, così
  la pagina funziona in una LAN senza internet. Il test degli asset trova un
  riferimento rimasto al vecchio nome.
- **Ogni paginazione è un unico `<template id="pager">`**, che `pager(name, count)` in
  `pagination.js` copia in ogni `<nav class="pager">`. Alpine percorre i figli del nav
  (ancora vuoti) prima che giri `init()` del componente, quindi `init()` inizializza da
  sé la copia con `Alpine.initTree`.
- **Il `viewBox` di un SVG va scritto letterale.** Il parser HTML porta in minuscolo un
  `:viewBox` con binding, e l'SVG lo ignora. I numeri dei grafici sono
  `CHART_W` × `CHART_H` in `charts.js`.
- **Una rotta che la pagina usa cambia con l'API.** Pagina e API viaggiano nella stessa
  immagine, quindi non girano mai in versioni diverse. Un cambio nella forma di una
  rotta richiede comunque di controllare questa pagina nella stessa PR.

## Collegamenti

- [`api/`](../api/README.it.md): le rotte che questa pagina chiama, e il mount che la
  serve.
- [`meshbee_core/`](../meshbee_core/README.it.md): dove vive ogni regola su cui la pagina
  si basa.
- [`tests/`](../tests/README.it.md): come eseguire la suite.
- [README](../README.it.md) principale: lo stack nel suo insieme.
