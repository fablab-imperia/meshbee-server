// Pagers for two kinds of table. The main table pages on the server: each page
// is one request with `limit` and `offset`, and the API's X-Total-Count says how
// many rows there are. The small tables (silent nodes, an apiary's shares) page
// a list already loaded. Mixed into admin().

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
      if (this.pagers[name].server) await this.loadRows();
    },

    async setPageSize(name) {
      this.resetPage(name);
      if (this.pagers[name].server) await this.loadRows();
    },

    resetPage(name) {
      this.pagers[name].page = 1;
    },
  };
}
