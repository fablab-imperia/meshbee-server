// Meshbee admin page: a thin client over the /api/admin routes.
//
// Every decision (soft deletes, password hashing, node transfers, validation)
// stays in the API; this file only lists, fills forms and shows the API's own
// error messages. Data reaches the DOM only through x-text, which escapes it.

const TOKEN_KEY = "meshbee-admin-token";

const id = (value) => encodeURIComponent(value);

// Columns: `fmt` names a formatter in `cell()`. Fields: `options` names a
// list in `options()`; `readonly` fields are shown but not editable.
const RESOURCES = {
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
        label: "Elimina",
        method: "DELETE",
        path: (r) => `/api/admin/apiari/${id(r.id_apiario)}`,
        confirm: (r) => `Eliminare l'apiario ${r.nome_apiario} e le sue condivisioni?`,
        when: (r) => !r.predefinito,
      },
    ],
  },

  // Read-only. Picking a hive switches to its scoped route, the one that
  // accepts a date range; admins pass its access check.
  letture: {
    label: "Letture",
    path: (f) => (f.id_arnia ? `/api/user/arnie/${id(f.id_arnia)}/letture` : "/api/admin/letture"),
    key: "id_lettura",
    filters: [
      { name: "id_arnia", label: "Arnia", type: "select", options: "arnie" },
      { name: "data_inizio", label: "Dal", type: "datetime-local", scoped: true },
      { name: "data_fine", label: "Al", type: "datetime-local", scoped: true },
      { name: "limit", label: "Limite", type: "number", value: 100 },
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
    actions: [],
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
      { name: "limit", label: "Limite", type: "number", value: 100 },
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

function admin() {
  return {
    resources: RESOURCES,
    token: null,
    me: null,
    login: { email: "", password: "" },
    tab: "utenti",
    rows: [],
    filters: {},
    loading: false,
    error: "",
    notice: "",
    // The open form or confirmation: { title, method, path, fields, values, note }.
    dialog: null,
    dialogError: "",
    // Value lists read from the API's own OpenAPI document, so the enums are
    // declared once, in meshbee_core/limits.py.
    enums: { ruoli: [], tipiAttivita: [] },
    lookups: { utenti: [], apiari: [], arnie: [], nodi: [] },

    get resource() {
      return this.resources[this.tab];
    },

    async init() {
      try {
        this.token = sessionStorage.getItem(TOKEN_KEY);
      } catch {
        this.token = null;
      }
      if (this.token) await this.start();
    },

    async signIn() {
      this.error = "";
      const res = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(this.login),
      });
      if (!res.ok) {
        this.error = "Credenziali non valide";
        return;
      }
      this.token = (await res.json()).access_token;
      this.login.password = "";
      try {
        sessionStorage.setItem(TOKEN_KEY, this.token);
      } catch {
        // Kept in memory only: a reload asks for the login again.
      }
      await this.start();
    },

    signOut(message = "") {
      this.token = null;
      this.me = null;
      this.rows = [];
      this.dialog = null;
      this.error = message;
      try {
        sessionStorage.removeItem(TOKEN_KEY);
      } catch {
        // Nothing stored.
      }
    },

    async start() {
      const me = await this.api("GET", "/api/auth/me");
      if (!me) return;
      if (me.ruolo !== "admin") {
        this.signOut("Questo account non è un amministratore");
        return;
      }
      this.me = me;
      await this.loadEnums();
      await this.select(this.tab);
    },

    // One request; returns the parsed body, or null after showing the error.
    async api(method, path, body, onError = (m) => (this.error = m)) {
      const res = await fetch(path, {
        method,
        headers: {
          Authorization: `Bearer ${this.token}`,
          ...(body === undefined ? {} : { "Content-Type": "application/json" }),
        },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
      if (res.status === 401) {
        this.signOut("Sessione scaduta: accedi di nuovo");
        return null;
      }
      const data = await res.json().catch(() => null);
      if (!res.ok) {
        onError(describeError(res.status, data));
        return null;
      }
      return data;
    },

    async loadEnums() {
      const res = await fetch("/openapi.json");
      const schemas = (await res.json()).components.schemas;
      this.enums.ruoli = schemas.UserCreate.properties.ruolo.enum;
      this.enums.tipiAttivita = schemas.AttivitaCreate.properties.tipo_attivita.enum;
    },

    // The id → name lists behind the selects and the readable table cells.
    async loadLookups() {
      const [utenti, apiari, arnie, nodi] = await Promise.all([
        this.api("GET", "/api/admin/utenti"),
        this.api("GET", "/api/admin/apiari"),
        this.api("GET", "/api/admin/arnie"),
        this.api("GET", "/api/admin/nodi"),
      ]);
      this.lookups = {
        utenti: utenti || [],
        apiari: apiari || [],
        arnie: arnie || [],
        nodi: nodi || [],
      };
    },

    async select(tab) {
      this.tab = tab;
      this.filters = {};
      for (const f of this.resource.filters || []) this.filters[f.name] = f.value ?? "";
      this.notice = "";
      await this.refresh();
    },

    async refresh() {
      this.loading = true;
      this.error = "";
      await this.loadLookups();
      const r = this.resource;
      const path = typeof r.path === "function" ? r.path(this.filters) : r.path;
      const query = new URLSearchParams();
      for (const f of r.filters || []) {
        const value = this.filters[f.name];
        if (f.name === "id_arnia" || value === "" || value == null) continue;
        if (f.scoped && !this.filters.id_arnia) continue;
        query.set(f.name, value);
      }
      const qs = query.toString();
      this.rows = (await this.api("GET", qs ? `${path}?${qs}` : path)) || [];
      this.loading = false;
    },

    filterShown(f) {
      return !f.scoped || !!this.filters.id_arnia;
    },

    actionsFor(row) {
      return this.resource.actions.filter((a) => !a.when || a.when(row));
    },

    openCreate() {
      const r = this.resource;
      this.openForm(`Nuovo: ${r.label}`, "POST", r.path, r.create, {});
    },

    async run(action, row) {
      // A fieldless action (a delete) opens the same dialog, as a confirmation.
      if (!action.fields) {
        this.openForm(action.label, action.method, action.path(row), [], {}, action.confirm(row));
        return;
      }
      const values = {};
      if (!action.blank) {
        for (const f of action.fields) values[f.name] = row[f.from || f.name];
      }
      this.openForm(`${action.label}: ${this.rowLabel(row)}`, action.method, action.path(row), action.fields, values, action.note);
    },

    openForm(title, method, path, fields, values, note = "") {
      const form = {};
      for (const f of fields) {
        const v = values[f.name];
        if (f.type === "checkbox") form[f.name] = !!v;
        else if (f.type === "json") form[f.name] = v == null ? "" : JSON.stringify(v, null, 2);
        else form[f.name] = v == null ? "" : String(v);
      }
      this.dialogError = "";
      this.dialog = { title, method, path, fields, values: form, note };
    },

    async submit() {
      const d = this.dialog;
      const body = {};
      for (const f of d.fields) {
        const raw = d.values[f.name];
        if (f.type === "checkbox") body[f.name] = raw;
        else if (raw === "") body[f.name] = null;
        else if (f.type === "json") {
          try {
            body[f.name] = JSON.parse(raw);
          } catch {
            this.dialogError = `${f.label}: JSON non valido`;
            return;
          }
        } else body[f.name] = raw;
      }
      const payload = d.fields.length ? body : undefined;
      const data = await this.api(d.method, d.path, payload, (m) => (this.dialogError = m));
      if (data) {
        this.dialog = null;
        await this.done(data.message || "Salvato");
      }
    },

    async done(message) {
      await this.refresh();
      this.notice = message;
    },

    options(name) {
      const l = this.lookups;
      switch (name) {
        case "ruoli":
          return this.enums.ruoli.map((v) => ({ value: v, label: v }));
        case "tipiAttivita":
          return this.enums.tipiAttivita.map((v) => ({ value: v, label: v }));
        case "utenti":
          return l.utenti.map((u) => ({ value: String(u.id_utente), label: `${u.email} (${u.nome} ${u.cognome})` }));
        case "apiari":
          return l.apiari.map((a) => ({ value: String(a.id_apiario), label: `${a.nome_apiario} — ${this.userName(a.id_utente_proprietario)}` }));
        case "arnie":
          return l.arnie.map((a) => ({ value: String(a.id_arnia), label: `${a.id_arnia} · ${a.nome_arnia || a.id_sensore_fisico}` }));
        case "nodi":
          return l.nodi.map((n) => ({ value: n.id_nodo, label: n.nome_nodo ? `${n.id_nodo} · ${n.nome_nodo}` : n.id_nodo }));
        default:
          return [];
      }
    },

    userName(idUtente) {
      const u = this.lookups.utenti.find((x) => x.id_utente === idUtente);
      return u ? u.email : idUtente == null ? "—" : `#${idUtente}`;
    },

    rowLabel(row) {
      const r = this.resource;
      return row.email || row.nome_apiario || row.nome_arnia || row.nome_nodo || row[r.key];
    },

    cell(row, col) {
      const v = row[col.name];
      switch (col.fmt) {
        case "bool":
          return v ? "✓" : "✗";
        case "date":
          return v ? new Date(v).toLocaleString("it-IT") : "—";
        case "utente":
          return this.userName(v);
        case "apiario": {
          const a = this.lookups.apiari.find((x) => x.id_apiario === v);
          return a ? a.nome_apiario : v == null ? "non assegnata" : `#${v}`;
        }
        case "arnia": {
          const a = this.lookups.arnie.find((x) => x.id_arnia === v);
          return a && a.nome_arnia ? `${v} · ${a.nome_arnia}` : v;
        }
        default:
          return v == null ? "—" : v;
      }
    },
  };
}

// FastAPI answers `detail` as a string, or as a list of field errors (422).
function describeError(status, data) {
  const detail = data && data.detail;
  if (Array.isArray(detail)) {
    return detail.map((e) => `${e.loc.slice(1).join(".")}: ${e.msg}`).join("; ");
  }
  return detail || `Errore ${status}`;
}
