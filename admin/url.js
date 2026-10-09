// Where the admin is, kept in the URL hash: the tab, its filters, the main
// table's page and the charts toggle. Back and Forward step through it, a
// reload stays put and a copied link opens the same view. Mixed into admin().
//
//   #/letture?id_arnia=3&data_inizio=2026-10-01T00:00&page=2&size=50&grafico=1
//
// Only what differs from the tab's defaults is written, so a plain tab is #/nodi.

function urlMixin() {
  return {
    // The tab and query the hash names. An unknown tab is the first one, and
    // its query, meant for some other tab, is dropped.
    readUrl() {
      const [path, search = ""] = location.hash.replace(/^#\/?/, "").split("?");
      if (!Object.hasOwn(RESOURCES, path)) return { tab: Object.keys(RESOURCES)[0], query: new URLSearchParams() };
      return { tab: path, query: new URLSearchParams(search) };
    },

    // The hash for the state shown now.
    hashFor() {
      const query = new URLSearchParams();
      for (const f of this.resource.filters || []) {
        const value = this.filters[f.name] ?? "";
        // A cleared default is written empty, or a reload would bring it back.
        if (value !== (f.value ?? "")) query.set(f.name, value);
      }
      // The overview has no main table to page.
      const main = this.pagers.main; // pagination.js
      if (!this.resource.view && main.page > 1) query.set("page", main.page);
      if (!this.resource.view && main.size !== this.pageSizes[0]) query.set("size", main.size);
      if (this.chartShown) query.set("grafico", "1"); // charts.js
      const search = query.toString();
      return `#/${this.tab}${search ? `?${search}` : ""}`;
    },

    // A new history entry for each step, so Back undoes it. `replace` corrects
    // the entry instead: a hash that named an unknown tab, say.
    writeUrl(replace = false) {
      const hash = this.hashFor();
      if (hash === location.hash) return;
      if (replace) history.replaceState(null, "", hash);
      else history.pushState(null, "", hash);
    },

    // Back, Forward, or a hash typed in the address bar. popstate fires for
    // all three; a pushState of our own fires nothing.
    async followUrl() {
      if (!this.me) return;
      this.dialog = null;
      const { tab, query } = this.readUrl();
      await this.select(tab, query, true);
    },
  };
}
