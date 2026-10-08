"""Authorization matrix over every endpoint in api/main.py.

One table, three sweeps: no credentials, a non-admin on admin routes, and a user
with no association on arnia-scoped routes. A gate that goes missing during the
refactor fails here, whatever else still works.

The two failure modes are deliberately distinct: **401** means "authenticate and
try again", **403** means "you are authenticated but not allowed".
"""

import pytest

# Reachable without a token and always 200. Login is public too, but answers 401
# on bad credentials, so it gets its own test below.
PUBLIC_OPEN = [
    ("get", "/", None),
    ("get", "/health", None),
]

# Admin-only: Depends(get_current_admin_user).
ADMIN_ONLY = [
    ("get", "/api/admin/utenti", None),
    (
        "post",
        "/api/admin/utenti",
        {"email": "n@b.org", "nome": "N", "cognome": "C", "password": "secret123"},
    ),
    ("put", "/api/admin/utenti/1", {}),
    ("delete", "/api/admin/utenti/1", None),
    ("put", "/api/admin/utenti/1/password", {"new_password": "secret123"}),
    ("get", "/api/admin/nodi", None),
    ("post", "/api/admin/nodi", {"id_nodo": "NODE-X"}),
    ("get", "/api/admin/nodi/NODE-X", None),
    ("put", "/api/admin/nodi/NODE-X", {"id_nodo": "NODE-X"}),
    ("delete", "/api/admin/nodi/NODE-X", None),
    ("put", "/api/admin/nodi/NODE-X/proprietario", {"id_utente": None}),
    ("get", "/api/admin/arnie", None),
    ("post", "/api/admin/arnie", {"id_nodo": "NODE-X", "id_sensore_fisico": "S1"}),
    ("get", "/api/admin/arnie/1", None),
    ("put", "/api/admin/arnie/1", {}),
    ("delete", "/api/admin/arnie/1", None),
    ("get", "/api/admin/letture", None),
    ("post", "/api/admin/letture", {"id_arnia": 1, "id_nodo": "NODE-X"}),
    ("delete", "/api/admin/letture/1", None),
    ("post", "/api/admin/letture/elimina", {"id_letture": [1]}),
    ("get", "/api/admin/attivita", None),
    ("get", "/api/admin/apiari", None),
    (
        "post",
        "/api/admin/apiari",
        {"nome_apiario": "Apiario X", "id_utente_proprietario": 1},
    ),
    ("get", "/api/admin/apiari/1", None),
    ("put", "/api/admin/apiari/1", {}),
    ("delete", "/api/admin/apiari/1", None),
]

# Authenticated but not scoped to a single arnia.
USER_GLOBAL = [
    ("get", "/api/auth/me", None),
    ("get", "/api/user/arnie", None),
    ("get", "/api/user/apiari", None),
    ("post", "/api/user/apiari", {"nome_apiario": "Apiario X"}),
    (
        "put",
        "/api/user/password",
        {"new_password": "secret123", "current_password": "old"},
    ),
]

# Scoped to {id_arnia}, guarded by check_user_arnia_access, with the least
# access that clears the gate. `{}` is substituted.
ARNIA_SCOPED = [
    ("get", "/api/user/arnie/{}", None, "viewer"),
    ("put", "/api/user/arnie/{}", {}, "manager"),
    ("get", "/api/user/arnie/{}/letture", None, "viewer"),
    ("get", "/api/user/arnie/{}/letture/temperatura", None, "viewer"),
    ("get", "/api/user/arnie/{}/letture/umidita", None, "viewer"),
    ("get", "/api/user/arnie/{}/letture/peso", None, "viewer"),
    ("get", "/api/user/arnie/{}/letture/batteria", None, "viewer"),
    ("get", "/api/user/arnie/{}/attivita", None, "viewer"),
    (
        "post",
        "/api/user/arnie/{}/attivita",
        {"id_arnia": 1, "tipo_attivita": "ispezione"},
        "collaborator",
    ),
    ("patch", "/api/user/arnie/{}/attivita/1", {}, "collaborator"),
    ("delete", "/api/user/arnie/{}/attivita/1", None, "collaborator"),
    ("put", "/api/user/arnie/{}/apiario", {"id_apiario": 1}, "owner"),
]

# Scoped to {id_apiario}, guarded by check_user_apiario_access, likewise.
APIARIO_SCOPED = [
    ("get", "/api/user/apiari/{}", None, "viewer"),
    ("put", "/api/user/apiari/{}", {}, "manager"),
    ("delete", "/api/user/apiari/{}", None, "owner"),
    ("get", "/api/user/apiari/{}/condivisioni", None, "owner"),
    ("post", "/api/user/apiari/{}/condivisioni", {"email": "x@y.org"}, "owner"),
    ("put", "/api/user/apiari/{}/condivisioni/1", {"ruolo": "viewer"}, "owner"),
    ("delete", "/api/user/apiari/{}/condivisioni/1", None, "owner"),
]

# From no access at all to owning: each level allows everything the one
# before it does (see ROLE_ACTIONS in meshbee_core/services/auth.py).
LEVELS = [None, "viewer", "collaborator", "manager", "owner"]

PROTECTED = (
    ADMIN_ONLY
    + USER_GLOBAL
    + [(m, p.format(1), b) for m, p, b, _ in ARNIA_SCOPED + APIARIO_SCOPED]
)


def call(client, method, path, body):
    """Issue the request, sending `body` as JSON when the endpoint takes one."""
    return getattr(client, method)(path, **({"json": body} if body is not None else {}))


def ids(rows):
    return [f"{m.upper()} {p}" for m, p, _ in rows]


# ============================================
# No credentials
# ============================================


@pytest.mark.parametrize("method, path, body", PROTECTED, ids=ids(PROTECTED))
def test_protected_endpoints_reject_anonymous_requests(client, method, path, body):
    """Every non-public endpoint answers 401 to a request with no Authorization header."""
    assert call(client, method, path, body).status_code == 401


def test_an_anonymous_request_advertises_how_to_authenticate(client):
    """401 carries WWW-Authenticate, so a client knows which scheme to use."""
    response = client.get("/api/auth/me")

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


@pytest.mark.parametrize(
    "header",
    ["Basic dXNlcjpwYXNz", "Bearer", "nonsense", "Token abc123"],
)
def test_a_non_bearer_authorization_header_is_unauthorized(client, header):
    """A header that is not a Bearer token is treated as no credentials at all."""
    response = client.get("/api/auth/me", headers={"Authorization": header})

    assert response.status_code == 401


@pytest.mark.parametrize("method, path, body", PUBLIC_OPEN, ids=ids(PUBLIC_OPEN))
def test_public_endpoints_do_not_require_a_token(client, method, path, body):
    """Root and health stay reachable without credentials."""
    assert call(client, method, path, body).status_code == 200


def test_login_is_reachable_without_a_token(client):
    """
    Login runs its handler rather than being turned away for lack of a token.

    It answers 401 here because the account does not exist — the detail is what
    distinguishes "bad credentials" from "authenticate first".
    """
    response = client.post(
        "/api/auth/login", json={"email": "nobody@example.org", "password": "secret123"}
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Email o password non corretti"


# ============================================
# Admin gate
# ============================================


@pytest.mark.parametrize("method, path, body", ADMIN_ONLY, ids=ids(ADMIN_ONLY))
def test_admin_endpoints_reject_a_regular_user(
    as_user, make_utente, method, path, body
):
    """A logged-in non-admin is refused by get_current_admin_user."""
    response = call(as_user(make_utente(ruolo="user")), method, path, body)

    assert response.status_code == 403
    assert "admin" in response.json()["detail"]


@pytest.mark.parametrize("method, path, body", ADMIN_ONLY, ids=ids(ADMIN_ONLY))
def test_admin_endpoints_admit_an_admin(as_user, make_utente, method, path, body):
    """An admin clears the gate — whatever the endpoint then does, it is not a 403."""
    response = call(as_user(make_utente(ruolo="admin")), method, path, body)

    assert response.status_code != 403


# ============================================
# Per-arnia and per-apiario access
# ============================================


def scoped(rows):
    """(method, path, body, minimum, level) for every route at every level."""
    return [(m, p, b, minimum, level) for m, p, b, minimum in rows for level in LEVELS]


def scoped_ids(rows):
    return [f"{m.upper()} {p} as {level}" for m, p, _, _, level in rows]


def reaching(utente_con_arnia, make_utente, make_arnia, level):
    """A user who reaches a hive and its apiary at `level` (None: not at all)."""
    if level is None:
        return make_utente(), make_arnia(apiario=make_utente())
    return utente_con_arnia(level)


def expected_allowed(level, minimum):
    return level is not None and LEVELS.index(level) >= LEVELS.index(minimum)


ARNIA_CASES = scoped(ARNIA_SCOPED)
APIARIO_CASES = scoped(APIARIO_SCOPED)


@pytest.mark.parametrize(
    "method, path, body, minimum, level", ARNIA_CASES, ids=scoped_ids(ARNIA_CASES)
)
def test_arnia_endpoints_admit_exactly_their_minimum_access_and_above(
    as_user,
    utente_con_arnia,
    make_utente,
    make_arnia,
    method,
    path,
    body,
    minimum,
    level,
):
    """
    Below the route's minimum: 403. At or above it: anything but 403. This
    is what pins each route to the action it checks.
    """
    utente, arnia = reaching(utente_con_arnia, make_utente, make_arnia, level)

    response = call(as_user(utente), method, path.format(arnia["id_arnia"]), body)

    assert (response.status_code != 403) is expected_allowed(level, minimum)


@pytest.mark.parametrize(
    "method, path, body, minimum, level", APIARIO_CASES, ids=scoped_ids(APIARIO_CASES)
)
def test_apiario_endpoints_admit_exactly_their_minimum_access_and_above(
    as_user,
    utente_con_arnia,
    make_utente,
    make_arnia,
    method,
    path,
    body,
    minimum,
    level,
):
    utente, arnia = reaching(utente_con_arnia, make_utente, make_arnia, level)

    response = call(as_user(utente), method, path.format(arnia["id_apiario"]), body)

    assert (response.status_code != 403) is expected_allowed(level, minimum)


@pytest.mark.parametrize(
    "method, path, body, minimum",
    ARNIA_SCOPED,
    ids=[f"{m.upper()} {p}" for m, p, _, _ in ARNIA_SCOPED],
)
def test_admins_reach_every_arnia_endpoint_without_owning_or_a_share(
    as_user, make_utente, make_arnia, method, path, body, minimum
):
    """Even on an unassigned hive, which nobody else can reach."""
    arnia = make_arnia()

    response = call(
        as_user(make_utente(ruolo="admin")),
        method,
        path.format(arnia["id_arnia"]),
        body,
    )

    assert response.status_code != 403


@pytest.mark.parametrize(
    "method, path, body, minimum",
    APIARIO_SCOPED,
    ids=[f"{m.upper()} {p}" for m, p, _, _ in APIARIO_SCOPED],
)
def test_admins_reach_every_apiario_endpoint_without_owning_or_a_share(
    as_user, make_utente, make_apiario, method, path, body, minimum
):
    apiario = make_apiario(make_utente())

    response = call(
        as_user(make_utente(ruolo="admin")),
        method,
        path.format(apiario["id_apiario"]),
        body,
    )

    assert response.status_code != 403


# ============================================
# Activities: own entries only
# ============================================


@pytest.mark.parametrize("method", ["patch", "delete"])
def test_editing_an_activity_needs_the_level_creating_one_needs(
    as_user, utente_con_arnia, db, method
):
    """
    A viewer must not remove an activity they were never allowed to create —
    even one they authored while they were a collaborator.
    """
    utente, arnia = utente_con_arnia("viewer")
    db.execute(
        """
        INSERT INTO log_attivita (id_utente, id_arnia, tipo_attivita)
        VALUES (%s, %s, 'ispezione') RETURNING id_log
        """,
        (utente["id_utente"], arnia["id_arnia"]),
    )
    id_log = db.fetchone()["id_log"]

    path = f"/api/user/arnie/{arnia['id_arnia']}/attivita/{id_log}"
    response = getattr(as_user(utente), method)(
        path, **({"json": {"descrizione": "modificata"}} if method == "patch" else {})
    )

    assert response.status_code == 403


@pytest.mark.parametrize("method", ["patch", "delete"])
def test_editing_an_activity_is_allowed_to_a_collaborator(
    as_user, utente_con_arnia, db, method
):
    """The same requests succeed for a collaborator."""
    utente, arnia = utente_con_arnia("collaborator")
    db.execute(
        """
        INSERT INTO log_attivita (id_utente, id_arnia, tipo_attivita)
        VALUES (%s, %s, 'ispezione') RETURNING id_log
        """,
        (utente["id_utente"], arnia["id_arnia"]),
    )
    id_log = db.fetchone()["id_log"]

    path = f"/api/user/arnie/{arnia['id_arnia']}/attivita/{id_log}"
    response = getattr(as_user(utente), method)(
        path, **({"json": {"descrizione": "modificata"}} if method == "patch" else {})
    )

    assert response.status_code == 200
