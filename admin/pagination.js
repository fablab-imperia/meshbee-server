// Pagers for two kinds of table. The main table pages on the server: each page
// is one request with `limit` and `offset`, and the API's X-Total-Count says how
// many rows there are. The small tables (silent nodes, an apiary's shares) page
// a list already loaded. Mixed into admin().
//
// index.html draws every pager the same way: a <nav x-data="pager(...)"> that
// fills itself from the one <template id="pager">.

const PAGE_SIZES = [25, 50, 100, 500];

function paginationMixin() {
  return {
    pageSizes: PAGE_SIZES,
    // One pager per table, by name: index.html's tables use "main", "silent"
    // and "shares". A `server` pager reloads its rows (loadRows) on a change.
    pagers: {
      main: { page: 1, size: PAGE_SIZES[0], server: true },
      silent: { page: 1, size: PAGE_SIZES[0] },
      shares: { page: 1, size: PAGE_SIZES[0] },
    },

    pageCount(name, count) {
      return Math.max(1, Math.ceil(count / this.pagers[name].size));
    },

    // The page asked for, kept in range: a delete or a new filter can shrink
    // the list under it.
    currentPage(name, count) {
      return Math.min(this.pagers[name].page, this.pageCount(name, count));
    },

    // One page of a list already loaded.
    paged(name, list) {
      const size = this.pagers[name].size;
      const start = (this.currentPage(name, list.length) - 1) * size;
      return list.slice(start, start + size);
    },

    // The `limit` and `offset` a server pager asks the API for.
    window(name) {
      const p = this.pagers[name];
      return { limit: p.size, offset: (p.page - 1) * p.size };
    },

    async goTo(name, count, page) {
      this.pagers[name].page = Math.min(Math.max(1, page), this.pageCount(name, count));
      await this.reloadPage(name);
    },

    async setPageSize(name) {
      this.resetPage(name);
      await this.reloadPage(name);
    },

    // A server pager's new page: one more step in the URL (url.js), then its rows.
    async reloadPage(name) {
      if (!this.pagers[name].server) return;
      this.writeUrl();
      await this.loadRows();
    },

    resetPage(name) {
      this.pagers[name].page = 1;
    },

    // A page and size as the URL gives them: strings, maybe missing or bogus.
    // A page past the end is left for loadRows to step back from.
    setPager(name, page, size) {
      const p = this.pagers[name];
      p.page = Math.max(1, Number.parseInt(page, 10) || 1);
      p.size = this.pageSizes.includes(Number(size)) ? Number(size) : this.pageSizes[0];
    },
  };
}

// One pager's controls. `name` picks the pager, `count` reads how many items
// its list holds. The markup is index.html's <template id="pager">; anything
// it names that isn't here resolves on admin().
document.addEventListener("alpine:init", () => {
  Alpine.data("pager", (name, count) => ({
    pager: name,
    get count() {
      return count();
    },
    get page() {
      return this.currentPage(name, this.count);
    },
    get pages() {
      return this.pageCount(name, this.count);
    },
    // A list that fits on the smallest page needs no pager.
    get needed() {
      return this.count > this.pageSizes[0];
    },
    // Alpine runs this after walking the nav's (then empty) children, so the
    // copy is initialised here; Alpine marks each node, none twice.
    init() {
      const controls = [...document.getElementById("pager").content.cloneNode(true).children];
      this.$el.append(...controls);
      for (const el of controls) Alpine.initTree(el);
    },
  }));
});
