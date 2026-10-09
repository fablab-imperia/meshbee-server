# `admin/` — admin page

*[Versione italiana](README.it.md)*

A small **static page for administrators**, served by the API at `/admin/`
([#41](https://github.com/fablab-imperia/meshbee-server/issues/41)). It covers:

- an overview: counts, and the active nodes silent for 24 hours;
- users, nodes, hives and apiaries: list, create, edit and deactivate;
- assigning a node's owner and moving a hive to another apiary of its owner;
- resetting a password;
- readings, as a table or as charts, and activities;
- who an apiary is shared with;
- readings by hand: insert one, correct one, delete one at a time or a selection
  ([#42](https://github.com/fablab-imperia/meshbee-server/issues/42),
  [#21](https://github.com/fablab-imperia/meshbee-server/issues/21)).

Swagger UI at `/docs` remains the full fallback.

It is **a client of the API, not a second one**:

- It logs in through `/api/auth/login`, refuses a non-admin account after
  `/api/auth/me`, and from then on calls the same routes as any other client with the
  bearer token.
- It adds no route, no session and no logic. Soft deletes, password hashing, node
  transfers and validation all happen in the services, and on a 4xx the page shows the
  API's own `detail`.
- It reads the value lists (`ruolo`, the apiary roles, `tipo_attivita`) from
  `/openapi.json`, so they stay declared once, in `meshbee_core/limits.py`.

## Contents

| File | What it is |
|---|---|
| `index.html` | The markup, with [Alpine.js](https://alpinejs.dev) bindings. |
| `resources.js` | `RESOURCES`: for each tab, its route, columns, form fields and row actions. A new admin operation is usually one entry here. |
| `admin.js` | The core of the one Alpine component: login, requests, the table and the generic form that `RESOURCES` drives. `admin()` merges the feature files below into it. |
| `overview.js`, `charts.js`, `shares.js`, `pagination.js`, `url.js` | One feature each, with its own state: the Panoramica tab, the readings charts, an apiary's sharing panel, the pager under each table, and the view kept in the URL. A new feature with state of its own gets a file like these, not more branches in `admin.js`. |
| `admin.css` | The little that [Pico CSS](https://picocss.com) does not cover. |
| `vendor/` | Alpine.js and Pico CSS, **vendored** with the version in the file name. See [Gotchas](#gotchas) for upgrading. |

## How it is served

The page has no server of its own. `api/main.py` mounts this directory at `/admin` with
`StaticFiles` (`ADMIN_DIR`), so the page shares the API's origin. That is why it calls
`/api/...` and `/openapi.json` as plain paths and needs no CORS setup or API URL.

- In development, `docker-compose.yml` bind-mounts `./admin` into the `api` container,
  so an edit shows on the next request. No restart, and `--reload` isn't involved.
- `api/Dockerfile` copies `admin/` into the image, next to `api/`.
- Without a Caddy proxy, the page is at <http://localhost:8000/admin/>. With
  [`make certs`](../README.md#local-https), it is also at <https://localhost:8443/admin/>.

## Features

- **A hive picked on the readings or activities tab** switches the list to the
  hive-scoped `/api/user/arnie/{id_arnia}/…` route. That is the route with the date
  filters, and admins pass its checks.
- **Deleting a hive's readings over a period:**
  1. Filter by hive and dates.
  2. Tick the header checkbox.
  3. Press **Seleziona tutte**.
  4. Delete the selection.

  The header checkbox covers only the page shown. Seleziona tutte fetches every reading
  the filters match in one request, up to 10000, which is the most a bulk delete takes.
- **The main table pages on the server**, 25 rows to start.
  - Each page is one request with `limit` and `offset`, and
    [`X-Total-Count`](../api/README.md#paging) sizes the pager.
  - A page change reloads only the rows.
  - Changing a filter goes back to page 1. Aggiorna and a save keep the page.
  - The lookups behind the selects and the readable cells (users, apiaries, hives,
    nodes) still load whole, so the silent nodes and an apiary's shares are paged in
    the browser.
- **An apiary's Condivisioni** use the owner's
  `/api/user/apiari/{id_apiario}/condivisioni` routes, which admins pass too. There are
  no admin copies of them. A hive's **Sposta** works the same way, through
  `PUT /api/user/arnie/{id_arnia}/apiario`.
- **The charts** load their own readings, since the table holds only one page.
  - They draw the picked hive's readings in the picked period (the last year without
    dates), up to the newest 10000.
  - They are inline SVG, with no chart library.
  - A missing value breaks the line, so a measurement the ingest nulled shows as a gap.
- **The Panoramica tab** is computed from the lists every tab already loads. It makes no
  request of its own.
- **The URL hash names the view**: the tab, its filters, the main table's page and size,
  and the charts toggle. For example: `#/letture?id_arnia=3&page=2&grafico=1`.
  - Each step is a history entry, so Back undoes it.
  - A reload or a copied link opens the same view after the login.
  - This is about thirty lines in `url.js`, with no router library. The tabs share one
    table, so per-route templates would have nothing to hold.
- **The token lives in `sessionStorage`**, so it is gone when the tab closes. There is no
  refresh ([#16](https://github.com/fablab-imperia/meshbee-server/issues/16)): when the
  token expires, the next request gets a 401 and the page asks for the login again.

## Development

**There is no build step and no npm.** Edit the files and reload the browser.

The checks run with the rest of the suite:

```bash
docker-compose exec api pytest tests/unit/admin
```

`tests/unit/admin/test_admin_page.py` checks three things:

- the page is served;
- every local asset `index.html` references is served;
- no page file inserts markup (see [Gotchas](#gotchas)).

Anything else needs a browser. Log in with the admin account from `.env`.

## Gotchas

- **Data reaches the DOM only through `x-text`**, which escapes it. Users type the
  names; `x-html` or `innerHTML` would let a name run script with the admin's token.
  The test fails on either, in `index.html` or in any `*.js` here.
- **Upgrading a vendored library:** replace the file under `vendor/` and its reference
  in `index.html`. The version in the file name is deliberate: no CDN, so the page
  works on a LAN with no internet. The asset test catches a reference left pointing at
  the old name.
- **Every pager is one `<template id="pager">`**, which `pager(name, count)` in
  `pagination.js` copies into each `<nav class="pager">`. Alpine walks the nav's
  (still empty) children before that component's `init()` runs, so `init()`
  initialises the copy itself with `Alpine.initTree`.
- **An SVG `viewBox` must be written literally.** The HTML parser lowercases a bound
  `:viewBox`, and SVG then ignores it. The charts' numbers are `CHART_W` × `CHART_H`
  in `charts.js`.
- **A route the page uses changes with the API.** The page and the API ship in one
  image, so they never run different versions. A change to a route's shape still means
  checking this page in the same PR.

## Related

- [`api/`](../api/README.md): the routes this page calls, and the mount that serves it.
- [`meshbee_core/`](../meshbee_core/README.md): where every rule the page relies on
  lives.
- [`tests/`](../tests/README.md): how to run the suite.
- Main [README](../README.md): the stack as a whole.
