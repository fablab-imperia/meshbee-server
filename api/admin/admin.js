// Meshbee admin page: a thin client over the /api/admin routes.
//
// Every decision (soft deletes, password hashing, node transfers, validation)
// stays in the API; the page only lists, fills forms and shows the API's own
// error messages. Data reaches the DOM only through x-text, which escapes it.
//
// This file is the core: login, requests, the table and the generic form, all
// driven by RESOURCES (resources.js). Each feature with state of its own lives
// in a mixin file (overview.js, charts.js, shares.js, pagination.js) that
// admin() merges in.

const TOKEN_KEY = "meshbee-admin-token";

// One Alpine component, assembled from the core and the feature mixins.
// Property descriptors, not a spread: a spread would freeze the getters.
function admin() {
  const component = {};
  for (const part of [adminCore(), overviewMixin(), chartsMixin(), sharesMixin(), paginationMixin()]) {
    Object.defineProperties(component, Object.getOwnPropertyDescriptors(part));
  }
  return component;
}

function adminCore() {
  return {
    resources: RESOURCES,
    token: null,
    me: null,
    login: { email: "", password: "" },
    tab: "panoramica",
    // The main table's page, and how many rows match its filters in all.
    rows: [],
    total: 0,
    filters: {},
    loading: false,
    error: "",
    notice: "",
    // The open form or confirmation: { title, method, path, fields, values, note, body },
    // or a panel: { kind, title }.
    dialog: null,
    dialogError: "",
    // Keys of the rows ticked for a bulk delete.
    selected: [],
    // Value lists read from the API's own OpenAPI document, so the enums are
    // declared once, in meshbee_core/limits.py.
    enums: { ruoli: [], ruoliApiario: [], tipiAttivita: [] },
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
      let res;
      try {
        res = await fetch("/api/auth/login", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(this.login),
        });
      } catch {
        this.error = UNREACHABLE;
        return;
      }
      if (!res.ok) {
        // A 503 (database down) says so; only a 401 is about the credentials.
        const data = await res.json().catch(() => null);
        this.error = res.status === 401 ? "Credenziali non valide" : describeError(res.status, data);
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
      if (!(await this.loadEnums())) return;
      await this.select(this.tab);
    },

    // One request; returns the parsed body, or null after showing the error.
    async api(method, path, body, onError = (m) => (this.error = m)) {
      const answer = await this.request(method, path, body, onError);
      return answer && answer.data;
    },

    // One page of a list route: its rows, and X-Total-Count (sent because the
    // path carries `limit`); null after showing the error.
    async list(path, onError = (m) => (this.error = m)) {
      const answer = await this.request("GET", path, undefined, onError);
      if (!answer) return null;
      const total = Number(answer.res.headers.get("X-Total-Count"));
      return { rows: answer.data, total: Number.isNaN(total) ? answer.data.length : total };
    },

    // Returns { res, data }, or null after showing the error.
    async request(method, path, body, onError) {
      let res;
      try {
        res = await fetch(path, {
          method,
          headers: {
            Authorization: `Bearer ${this.token}`,
            ...(body === undefined ? {} : { "Content-Type": "application/json" }),
          },
          body: body === undefined ? undefined : JSON.stringify(body),
        });
      } catch {
        onError(UNREACHABLE);
        return null;
      }
      if (res.status === 401) {
        this.signOut("Sessione scaduta: accedi di nuovo");
        return null;
      }
      const data = await res.json().catch(() => null);
      if (!res.ok) {
        onError(describeError(res.status, data));
        return null;
      }
      return { res, data };
    },

    // Returns false after showing the error: without the enums the forms
    // would offer empty selects.
    async loadEnums() {
      try {
        const res = await fetch("/openapi.json");
        if (!res.ok) throw new Error(`Errore ${res.status}`);
        const schemas = (await res.json()).components.schemas;
        this.enums.ruoli = schemas.UserCreate.properties.ruolo.enum;
        this.enums.ruoliApiario = schemas.CondivisioneCreate.properties.ruolo.enum;
        this.enums.tipiAttivita = schemas.AttivitaCreate.properties.tipo_attivita.enum;
        return true;
      } catch (e) {
        this.signOut(`Impossibile leggere /openapi.json: ${e.message}`);
        return false;
      }
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
      // The old tab's rows would render under the new tab's key: all undefined,
      // so duplicate keys, and the x-for breaks.
      this.rows = [];
      this.total = 0;
      this.tab = tab;
      this.filters = {};
      for (const f of this.resource.filters || []) this.filters[f.name] = f.value ?? "";
      this.notice = "";
      this.showChart = false; // charts.js
      this.resetPage("main"); // pagination.js
      await this.refresh();
    },

    // A filter changed: a different list, so back to its first page. A plain
    // refresh (Aggiorna, or after a save) keeps the page.
    async applyFilters() {
      this.resetPage("main");
      await this.refresh();
    },

    // The lookups, then the main table's page. Aggiorna, and after a save.
    async refresh() {
      this.loading = true;
      this.error = "";
      this.selected = [];
      try {
        await this.loadLookups();
        await this.loadRows();
      } finally {
        this.loading = false;
      }
    },

    // The current page of the tab's list route, as pagers.main sets it. A page
    // change calls this alone: the lookups stay as they are.
    async loadRows() {
      if (this.resource.view) return;
      this.loading = true;
      try {
        const { limit, offset } = this.window("main"); // pagination.js
        const page = await this.list(this.listPath(limit, offset));
        this.rows = page ? page.rows : [];
        this.total = page ? page.total : 0;
        // A delete can empty the last page: step back to the new last one.
        if (page && this.rows.length === 0 && this.total > 0 && offset > 0) {
          this.pagers.main.page = this.pageCount("main", this.total);
          await this.loadRows();
          return;
        }
        if (this.chartShown) await this.loadChart(); // charts.js
      } finally {
        this.loading = false;
      }
    },

    // The tab's list route with its filters, and a window of it.
    listPath(limit, offset) {
      const r = this.resource;
      const path = typeof r.path === "function" ? r.path(this.filters) : r.path;
      const query = new URLSearchParams();
      for (const f of r.filters || []) {
        const value = this.filters[f.name];
        if (f.name === "id_arnia" || value === "" || value == null) continue;
        if (f.scoped && !this.filters.id_arnia) continue;
        query.set(f.name, value);
      }
      query.set("limit", limit);
      query.set("offset", offset);
      return `${path}?${query}`;
    },

    filterShown(f) {
      return !f.scoped || !!this.filters.id_arnia;
    },

    actionsFor(row) {
      return this.resource.actions.filter((a) => !a.when || a.when(row));
    },

    openCreate() {
      const r = this.resource;
      const values = r.createDefaults ? r.createDefaults(this.filters, this.lookups) : {};
      this.openForm(`Nuovo: ${r.label}`, "POST", r.createPath || r.path, r.create, values, r.createNote);
    },

    // Bulk selection, by key, so it survives a page change. The header
    // checkbox covers the page shown; selectAllMatching() every matching row.
    isSelected(row) {
      return this.selected.includes(row[this.resource.key]);
    },

    toggle(row) {
      const key = row[this.resource.key];
      this.selected = this.isSelected(row) ? this.selected.filter((k) => k !== key) : [...this.selected, key];
    },

    get allSelected() {
      return this.rows.length > 0 && this.rows.every((row) => this.isSelected(row));
    },

    toggleAll(on) {
      const keys = this.rows.map((row) => row[this.resource.key]);
      this.selected = on
        ? [...new Set([...this.selected, ...keys])]
        : this.selected.filter((k) => !keys.includes(k));
    },

    // Every row the filters match, not just the page shown: one request at the
    // route's largest page, which is also the most a bulk delete takes.
    async selectAllMatching() {
      const page = await this.list(this.listPath(this.resource.bulkDelete.max, 0));
      if (!page) return;
      this.selected = page.rows.map((row) => row[this.resource.key]);
      if (page.total > page.rows.length) {
        this.notice = `Selezionate le prime ${page.rows.length} di ${page.total}: elimina e ripeti per le altre.`;
      }
    },

    deleteSelected() {
      const b = this.resource.bulkDelete;
      const n = this.selected.length;
      this.openForm("Elimina selezionate", "POST", b.path, [], {}, `Eliminare ${n} elementi? Non si può annullare.`, {
        [b.body]: this.selected,
      });
    },

    async run(action, row) {
      if (action.panel) {
        await this[action.panel](row);
        return;
      }
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
      this.dialog.partial = !!action.partial;
      // Some option lists depend on the row (apiariProprietario).
      this.dialog.row = row;
    },

    openForm(title, method, path, fields, values, note = "", body = undefined) {
      const form = {};
      for (const f of fields) {
        const v = values[f.name];
        if (f.type === "checkbox") form[f.name] = !!v;
        else if (f.type === "json") form[f.name] = v == null ? "" : JSON.stringify(v, null, 2);
        // The input takes whole seconds at most: "2026-10-08T10:54:09".
        else if (f.type === "datetime-local") form[f.name] = v == null ? "" : String(v).slice(0, 19);
        else form[f.name] = v == null ? "" : String(v);
      }
      this.dialogError = "";
      // `initial` is what a partial form compares against.
      this.dialog = { title, method, path, fields, values: form, initial: { ...form }, note, body };
    },

    async submit() {
      const d = this.dialog;
      const body = {};
      for (const f of d.fields) {
        const raw = d.values[f.name];
        if (d.partial && raw === d.initial[f.name]) continue;
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
      const payload = d.fields.length ? body : d.body;
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
        case "ruoliApiario":
          return this.enums.ruoliApiario.map((v) => ({ value: v, label: v }));
        case "tipiAttivita":
          return this.enums.tipiAttivita.map((v) => ({ value: v, label: v }));
        case "utenti":
          return l.utenti.map((u) => ({ value: String(u.id_utente), label: `${u.email} (${u.nome} ${u.cognome})` }));
        case "apiari":
          return l.apiari.map((a) => ({ value: String(a.id_apiario), label: `${a.nome_apiario} — ${this.userName(a.id_utente_proprietario)}` }));
        // The apiaries of the dialog row's owner: where a hive can move.
        case "apiariProprietario": {
          const row = this.dialog && this.dialog.row;
          const current = row && l.apiari.find((a) => a.id_apiario === row.id_apiario);
          if (!current) return [];
          return l.apiari
            .filter((a) => a.id_utente_proprietario === current.id_utente_proprietario)
            .map((a) => ({ value: String(a.id_apiario), label: a.nome_apiario }));
        }
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
      if (r.key === "id_lettura") return `lettura ${row.id_lettura} delle ${this.cell(row, { name: "timestamp", fmt: "date" })}`;
      // A hive row also carries its apiary's name: the hive's own comes first.
      return row.email || row.nome_arnia || row.nome_apiario || row.nome_nodo || row[r.key];
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

// A fetch that rejects: no answer at all, not an error status.
const UNREACHABLE = "Server non raggiungibile";

// FastAPI answers `detail` as a string, or as a list of field errors (422).
function describeError(status, data) {
  const detail = data && data.detail;
  if (Array.isArray(detail)) {
    return detail.map((e) => `${e.loc.slice(1).join(".")}: ${e.msg}`).join("; ");
  }
  return detail || `Errore ${status}`;
}
