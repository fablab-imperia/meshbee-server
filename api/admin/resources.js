// The admin page's tabs: per tab, the route, columns, form fields and row
// actions that admin.js drives. A new admin operation is usually one entry here.

const id = (value) => encodeURIComponent(value);

// Columns: `fmt` names a formatter in `cell()`. Fields: `options` names a
// list in `options()`; `readonly` fields are shown but not editable.
// `createPath` is where the create form posts when `path` is a function;
// `createDefaults` prefills it. `bulkDelete` makes rows selectable and names
// the route that deletes a selection. An action with `panel` names the method
// that opens its panel instead of a form; a `partial` action sends only the
// fields the admin changed.
// A tab with `view` has its own markup in index.html instead of the table.
const RESOURCES = {
  // Counts and silent nodes, all from the lookup lists: no request of its own.
  panoramica: {
    label: "Panoramica",
    view: "overview",
    actions: [],
  },

  utenti: {
    label: "Utenti",
    path: "/api/admin/utenti",
    key: "id_utente",
    columns: [
      { name: "id_utente", label: "ID" },
      { name: "email", label: "Email" },
      { name: "nome", label: "Nome" },
      { name: "cognome", label: "Cognome" },
      { name: "ruolo", label: "Ruolo" },
      { name: "attivo", label: "Attivo", fmt: "bool" },
      { name: "ultimo_accesso", label: "Ultimo accesso", fmt: "date" },
    ],
    create: [
      { name: "email", label: "Email", type: "email", required: true },
      { name: "nome", label: "Nome", required: true },
      { name: "cognome", label: "Cognome", required: true },
      { name: "password", label: "Password", type: "password", required: true },
      { name: "ruolo", label: "Ruolo", type: "select", options: "ruoli", required: true },
    ],
    actions: [
      {
        label: "Modifica",
        method: "PUT",
        path: (r) => `/api/admin/utenti/${id(r.id_utente)}`,
        fields: [
          { name: "email", label: "Email", type: "email", required: true },
          { name: "nome", label: "Nome", required: true },
          { name: "cognome", label: "Cognome", required: true },
          { name: "ruolo", label: "Ruolo", type: "select", options: "ruoli", required: true },
          { name: "attivo", label: "Attivo", type: "checkbox" },
        ],
      },
      {
        label: "Password",
        method: "PUT",
        path: (r) => `/api/admin/utenti/${id(r.id_utente)}/password`,
        fields: [
          { name: "new_password", label: "Nuova password", type: "password", required: true },
        ],
        blank: true,
      },
      {
        label: "Disattiva",
        method: "DELETE",
        path: (r) => `/api/admin/utenti/${id(r.id_utente)}`,
        confirm: (r) => `Disattivare l'utente ${r.email}?`,
        when: (r) => r.attivo,
      },
    ],
  },

  nodi: {
    label: "Nodi",
    path: "/api/admin/nodi",
    key: "id_nodo",
    columns: [
      { name: "id_nodo", label: "ID" },
      { name: "nome_nodo", label: "Nome" },
      { name: "posizione", label: "Posizione" },
      { name: "id_proprietario", label: "Proprietario", fmt: "utente" },
      { name: "attivo", label: "Attivo", fmt: "bool" },
      { name: "ultimo_messaggio", label: "Ultimo messaggio", fmt: "date" },
    ],
    create: [
      { name: "id_nodo", label: "ID nodo", required: true },
      { name: "nome_nodo", label: "Nome" },
      { name: "descrizione", label: "Descrizione", type: "textarea" },
      { name: "posizione", label: "Posizione" },
      { name: "configurazione", label: "Configurazione (JSON)", type: "json" },
    ],
    actions: [
      {
        label: "Modifica",
        method: "PUT",
        path: (r) => `/api/admin/nodi/${id(r.id_nodo)}`,
        // The route takes a full NodoCreate, id included.
        fields: [
          { name: "id_nodo", label: "ID nodo", readonly: true },
          { name: "nome_nodo", label: "Nome" },
          { name: "descrizione", label: "Descrizione", type: "textarea" },
          { name: "posizione", label: "Posizione" },
          { name: "configurazione", label: "Configurazione (JSON)", type: "json" },
        ],
      },
      {
        label: "Proprietario",
        method: "PUT",
        path: (r) => `/api/admin/nodi/${id(r.id_nodo)}/proprietario`,
        fields: [
          {
            name: "id_utente",
            label: "Proprietario (vuoto = non assegnato)",
            type: "select",
            options: "utenti",
            from: "id_proprietario",
          },
        ],
        note: "Le arnie del nodo passano all'apiario predefinito del nuovo proprietario.",
      },
      {
        label: "Disattiva",
        method: "DELETE",
        path: (r) => `/api/admin/nodi/${id(r.id_nodo)}`,
        confirm: (r) => `Disattivare il nodo ${r.id_nodo}? Arnie e letture restano.`,
        when: (r) => r.attivo,
      },
    ],
  },

  arnie: {
    label: "Arnie",
    path: "/api/admin/arnie",
    key: "id_arnia",
    filters: [{ name: "id_apiario", label: "Apiario", type: "select", options: "apiari" }],
    columns: [
      { name: "id_arnia", label: "ID" },
      { name: "nome_arnia", label: "Nome" },
      { name: "id_nodo", label: "Nodo" },
      { name: "id_sensore_fisico", label: "Sensore" },
      { name: "id_apiario", label: "Apiario", fmt: "apiario" },
      { name: "attiva", label: "Attiva", fmt: "bool" },
      { name: "ultima_temperatura", label: "°C" },
      { name: "ultima_umidita", label: "%" },
      { name: "ultimo_peso", label: "kg" },
      { name: "ultima_batteria", label: "V" },
      { name: "ultimo_aggiornamento", label: "Aggiornata", fmt: "date" },
    ],
    create: [
      { name: "id_nodo", label: "Nodo", type: "select", options: "nodi", required: true },
      { name: "id_sensore_fisico", label: "ID sensore fisico", required: true },
      { name: "nome_arnia", label: "Nome" },
      { name: "descrizione", label: "Descrizione", type: "textarea" },
      { name: "posizione", label: "Posizione" },
      { name: "latitudine", label: "Latitudine", type: "number" },
      { name: "longitudine", label: "Longitudine", type: "number" },
      {
        name: "id_apiario",
        label: "Apiario (vuoto = predefinito del proprietario del nodo)",
        type: "select",
        options: "apiari",
      },
      { name: "metadati", label: "Metadati (JSON)", type: "json" },
    ],
    actions: [
      {
        label: "Modifica",
        method: "PUT",
        path: (r) => `/api/admin/arnie/${id(r.id_arnia)}`,
        fields: [
          { name: "nome_arnia", label: "Nome" },
          { name: "descrizione", label: "Descrizione", type: "textarea" },
          { name: "posizione", label: "Posizione" },
          { name: "latitudine", label: "Latitudine", type: "number" },
          { name: "longitudine", label: "Longitudine", type: "number" },
          { name: "attiva", label: "Attiva", type: "checkbox" },
          { name: "metadati", label: "Metadati (JSON)", type: "json" },
        ],
      },
      {
        // The owner's route; admins pass its check. An unassigned hive has no
        // owner, so nowhere to move to: its node needs an owner first.
        label: "Sposta",
        method: "PUT",
        path: (r) => `/api/user/arnie/${id(r.id_arnia)}/apiario`,
        fields: [
          { name: "id_apiario", label: "Apiario", type: "select", options: "apiariProprietario", required: true },
        ],
        note: "Solo verso un apiario dello stesso proprietario. Chi vede l'arnia segue l'apiario.",
        when: (r) => r.id_apiario != null,
      },
      {
        label: "Disattiva",
        method: "DELETE",
        path: (r) => `/api/admin/arnie/${id(r.id_arnia)}`,
        confirm: (r) => `Disattivare l'arnia ${r.nome_arnia || r.id_arnia}? Le letture restano.`,
        when: (r) => r.attiva,
      },
    ],
  },

  apiari: {
    label: "Apiari",
    path: "/api/admin/apiari",
    key: "id_apiario",
    filters: [{ name: "id_utente", label: "Proprietario", type: "select", options: "utenti" }],
    columns: [
      { name: "id_apiario", label: "ID" },
      { name: "nome_apiario", label: "Nome" },
      { name: "id_utente_proprietario", label: "Proprietario", fmt: "utente" },
      { name: "predefinito", label: "Predefinito", fmt: "bool" },
      { name: "posizione", label: "Posizione" },
      { name: "data_creazione", label: "Creato", fmt: "date" },
    ],
    create: [
      {
        name: "id_utente_proprietario",
        label: "Proprietario",
        type: "select",
        options: "utenti",
        required: true,
      },
      { name: "nome_apiario", label: "Nome", required: true },
      { name: "descrizione", label: "Descrizione", type: "textarea" },
      { name: "posizione", label: "Posizione" },
      { name: "latitudine", label: "Latitudine", type: "number" },
      { name: "longitudine", label: "Longitudine", type: "number" },
      { name: "metadati", label: "Metadati (JSON)", type: "json" },
    ],
    actions: [
      {
        label: "Modifica",
        method: "PUT",
        path: (r) => `/api/admin/apiari/${id(r.id_apiario)}`,
        fields: [
          { name: "nome_apiario", label: "Nome", required: true },
          { name: "descrizione", label: "Descrizione", type: "textarea" },
          { name: "posizione", label: "Posizione" },
          { name: "latitudine", label: "Latitudine", type: "number" },
          { name: "longitudine", label: "Longitudine", type: "number" },
          { name: "metadati", label: "Metadati (JSON)", type: "json" },
        ],
      },
      {
        label: "Condivisioni",
        panel: "openShares",
      },
      {
        label: "Elimina",
        method: "DELETE",
        path: (r) => `/api/admin/apiari/${id(r.id_apiario)}`,
        confirm: (r) => `Eliminare l'apiario ${r.nome_apiario} e le sue condivisioni?`,
        when: (r) => !r.predefinito,
      },
    ],
  },

  // Picking a hive switches to its scoped route, the one that accepts a date
  // range; admins pass its access check. Filter, then delete the selection:
  // that is how a hive's readings over a period go.
  letture: {
    label: "Letture",
    path: (f) => (f.id_arnia ? `/api/user/arnie/${id(f.id_arnia)}/letture` : "/api/admin/letture"),
    createPath: "/api/admin/letture",
    // `max`: the most ids the route takes, and the largest page of the list routes.
    bulkDelete: { path: "/api/admin/letture/elimina", body: "id_letture", max: 10000 },
    // With a hive picked, the listed rows can also be drawn as charts.
    chart: true,
    key: "id_lettura",
    filters: [
      { name: "id_arnia", label: "Arnia", type: "select", options: "arnie" },
      { name: "data_inizio", label: "Dal", type: "datetime-local", scoped: true },
      { name: "data_fine", label: "Al", type: "datetime-local", scoped: true },
    ],
    columns: [
      { name: "timestamp", label: "Ora", fmt: "date" },
      { name: "id_arnia", label: "Arnia", fmt: "arnia" },
      { name: "id_nodo", label: "Nodo" },
      { name: "temperatura", label: "°C" },
      { name: "umidita", label: "%" },
      { name: "peso", label: "kg" },
      { name: "batteria", label: "V" },
    ],
    create: [
      { name: "id_arnia", label: "Arnia", type: "select", options: "arnie", required: true },
      { name: "id_nodo", label: "Nodo", type: "select", options: "nodi", required: true },
      { name: "timestamp", label: "Ora (vuoto = adesso)", type: "datetime-local" },
      { name: "temperatura", label: "Temperatura (°C)", type: "number" },
      { name: "umidita", label: "Umidità (%)", type: "number" },
      { name: "peso", label: "Peso (kg)", type: "number" },
      { name: "batteria", label: "Batteria (V)", type: "number" },
      { name: "dati_raw", label: "Dati grezzi (JSON)", type: "json" },
    ],
    // The hive picked in the filter, and its node.
    createDefaults: (f, lookups) => {
      const a = lookups.arnie.find((x) => String(x.id_arnia) === f.id_arnia);
      return a ? { id_arnia: a.id_arnia, id_nodo: a.id_nodo } : {};
    },
    createNote: "Un'arnia inesistente risponde 404: a differenza di MQTT, qui non viene creata.",
    actions: [
      {
        label: "Modifica",
        method: "PATCH",
        path: (r) => `/api/admin/letture/${id(r.id_lettura)}`,
        // Partial: an untouched timestamp keeps its microseconds, which the
        // datetime input cannot show. A measurement emptied is cleared.
        partial: true,
        fields: [
          { name: "timestamp", label: "Ora", type: "datetime-local", required: true },
          { name: "temperatura", label: "Temperatura (°C)", type: "number" },
          { name: "umidita", label: "Umidità (%)", type: "number" },
          { name: "peso", label: "Peso (kg)", type: "number" },
          { name: "batteria", label: "Batteria (V)", type: "number" },
          { name: "dati_raw", label: "Dati grezzi (JSON)", type: "json" },
        ],
        note: "Arnia e nodo non si modificano. Un valore svuotato viene cancellato.",
      },
      {
        label: "Elimina",
        method: "DELETE",
        path: (r) => `/api/admin/letture/${id(r.id_lettura)}`,
        confirm: (r) => `Eliminare la lettura delle ${new Date(r.timestamp).toLocaleString("it-IT")}? Non si può annullare.`,
      },
    ],
  },

  attivita: {
    label: "Attività",
    path: (f) => (f.id_arnia ? `/api/user/arnie/${id(f.id_arnia)}/attivita` : "/api/admin/attivita"),
    key: "id_log",
    filters: [
      { name: "id_arnia", label: "Arnia", type: "select", options: "arnie" },
      { name: "tipo_attivita", label: "Tipo", type: "select", options: "tipiAttivita", scoped: true },
      { name: "data_inizio", label: "Dal", type: "datetime-local", scoped: true },
      { name: "data_fine", label: "Al", type: "datetime-local", scoped: true },
    ],
    columns: [
      { name: "timestamp", label: "Ora", fmt: "date" },
      { name: "id_arnia", label: "Arnia", fmt: "arnia" },
      { name: "tipo_attivita", label: "Tipo" },
      { name: "descrizione", label: "Descrizione" },
      { name: "id_utente", label: "Utente", fmt: "utente" },
    ],
    actions: [],
  },
};
