// Pages over a list already loaded. The API's list routes take a `limit` but no
// offset, so the page loads what it shows today (every user, node, hive and
// apiary; readings and activities up to "Limite") and pages it here.
// Mixed into admin().

const PAGE_SIZES = [25, 50, 100, 500];

function paginationMixin() {
  return {
    pageSizes: PAGE_SIZES,
    // One pager per table, by name: index.html's tables use "main", "silent"
    // and "shares".
    pagers: {
      main: { page: 1, size: PAGE_SIZES[0] },
      silent: { page: 1, size: PAGE_SIZES[0] },
      shares: { page: 1, size: PAGE_SIZES[0] },
    },

    pageCount(name, list) {
      return Math.max(1, Math.ceil(list.length / this.pagers[name].size));
    },

    // The page asked for, kept in range: a delete or a new filter can shrink
    // the list under it.
    currentPage(name, list) {
      return Math.min(this.pagers[name].page, this.pageCount(name, list));
    },

    paged(name, list) {
      const size = this.pagers[name].size;
      const start = (this.currentPage(name, list) - 1) * size;
      return list.slice(start, start + size);
    },

    goTo(name, list, page) {
      this.pagers[name].page = Math.min(Math.max(1, page), this.pageCount(name, list));
    },

    resetPage(name) {
      this.pagers[name].page = 1;
    },
  };
}
