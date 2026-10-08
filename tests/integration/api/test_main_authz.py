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
    ("get", "/api/admin/arnie", None),
    ("post", "/api/admin/arnie", {"id_nodo": "NODE-X", "id_sensore_fisico": "S1"}),
    ("get", "/api/admin/arnie/1", None),
    ("put", "/api/admin/arnie/1", {}),
    ("delete", "/api/admin/arnie/1", None),
    (
        "post",
        "/api/admin/utenti-arnie",
        {"id_utente": 1, "id_arnia": 1, "permessi": "read"},
    ),
    ("delete", "/api/admin/utenti-arnie?id_utente=1&id_arnia=1", None),
    ("get", "/api/admin/letture", None),
    ("post", "/api/admin/letture", {"id_arnia": 1, "id_nodo": "NODE-X"}),
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

# Scoped to {id_arnia}: guarded by check_user_arnia_access. `{}` is substituted.
ARNIA_SCOPED = [
    ("get", "/api/user/arnie/{}", None),
    ("put", "/api/user/arnie/{}", {}),
    ("get", "/api/user/arnie/{}/letture", None),
    ("get", "/api/user/arnie/{}/letture/temperatura", None),
    ("get", "/api/user/arnie/{}/letture/umidita", None),
    ("get", "/api/user/arnie/{}/letture/peso", None),
    ("get", "/api/user/arnie/{}/letture/batteria", None),
    ("get", "/api/user/arnie/{}/attivita", None),
    (
        "post",
        "/api/user/arnie/{}/attivita",
        {"id_arnia": 1, "tipo_attivita": "ispezione"},
    ),
    ("patch", "/api/user/arnie/{}/attivita/1", {}),
    ("delete", "/api/user/arnie/{}/attivita/1", None),
    ("put", "/api/user/arnie/{}/apiario", {"id_apiario": 1}),
]

# Scoped to {id_apiario}: guarded by check_user_apiario_access, which admits only
# the apiary's owner (and admins). `{}` is substituted.
APIARIO_SCOPED = [
    ("get", "/api/user/apiari/{}", None),
    ("put", "/api/user/apiari/{}", {}),
    ("delete", "/api/user/apiari/{}", None),
]

PROTECTED = (
    ADMIN_ONLY
    + USER_GLOBAL
    + [(m, p.format(1), b) for m, p, b in ARNIA_SCOPED + APIARIO_SCOPED]
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
# Per-arnia access
# ============================================


@pytest.mark.parametrize("method, path, body", ARNIA_SCOPED, ids=ids(ARNIA_SCOPED))
def test_arnia_endpoints_reject_a_user_without_an_association(
    as_user, make_utente, make_arnia, method, path, body
):
    """A user with no row in utenti_arnie cannot touch the arnia."""
    arnia = make_arnia()
    response = call(
        as_user(make_utente()), method, path.format(arnia["id_arnia"]), body
    )

    assert response.status_code == 403


@pytest.mark.parametrize("method, path, body", ARNIA_SCOPED, ids=ids(ARNIA_SCOPED))
def test_arnia_endpoints_admit_an_associated_user(
    as_user, utente_con_arnia, method, path, body
):
    """An association with admin permission clears every per-arnia gate."""
    utente, arnia = utente_con_arnia("admin")
    response = call(as_user(utente), method, path.format(arnia["id_arnia"]), body)

    assert response.status_code != 403


def test_admins_reach_arnie_they_are_not_associated_with(
    as_user, make_utente, make_arnia
):
    """check_user_arnia_access short-circuits for admins, so no association is needed."""
    arnia = make_arnia()
    response = as_user(make_utente(ruolo="admin")).get(
        f"/api/user/arnie/{arnia['id_arnia']}"
    )

    assert response.status_code == 200


# ============================================
# Per-apiario access
# ============================================


@pytest.mark.parametrize("method, path, body", APIARIO_SCOPED, ids=ids(APIARIO_SCOPED))
def test_apiario_endpoints_reject_a_user_who_does_not_own_it(
    as_user, make_utente, make_apiario, method, path, body
):
    """Apiaries are personal: someone else's is off limits, whatever it holds."""
    apiario = make_apiario(make_utente())

    response = call(
        as_user(make_utente()), method, path.format(apiario["id_apiario"]), body
    )

    assert response.status_code == 403


@pytest.mark.parametrize("method, path, body", APIARIO_SCOPED, ids=ids(APIARIO_SCOPED))
def test_apiario_endpoints_admit_the_owner(
    as_user, make_utente, make_apiario, method, path, body
):
    utente = make_utente()
    apiario = make_apiario(utente)

    response = call(as_user(utente), method, path.format(apiario["id_apiario"]), body)

    assert response.status_code != 403


def test_admins_reach_apiari_they_do_not_own(as_user, make_utente, make_apiario):
    """check_user_apiario_access short-circuits for admins, like the arnia gate."""
    apiario = make_apiario(make_utente())

    response = as_user(make_utente(ruolo="admin")).get(
        f"/api/user/apiari/{apiario['id_apiario']}"
    )

    assert response.status_code == 200


# ============================================
# Write-permission gate
# ============================================


def test_creating_an_activity_requires_write_permission(as_user, utente_con_arnia):
    """Read-only access is not enough to log an activity."""
    utente, arnia = utente_con_arnia("read")

    response = as_user(utente).post(
        f"/api/user/arnie/{arnia['id_arnia']}/attivita",
        json={"id_arnia": arnia["id_arnia"], "tipo_attivita": "ispezione"},
    )

    assert response.status_code == 403


def test_updating_an_arnia_requires_write_permission(as_user, utente_con_arnia):
    """Read-only access cannot edit the arnia itself."""
    utente, arnia = utente_con_arnia("read")

    response = as_user(utente).put(
        f"/api/user/arnie/{arnia['id_arnia']}", json={"nome_arnia": "Nuovo nome"}
    )

    assert response.status_code == 403


@pytest.mark.parametrize("method", ["patch", "delete"])
def test_editing_an_activity_requires_write_permission(
    as_user, utente_con_arnia, db, method
):
    """
    Editing and deleting need "write", the same level creating one needs.

    A read-only collaborator must not be able to remove an activity they were
    never allowed to create — even one they authored while holding write access.
    """
    utente, arnia = utente_con_arnia("read")
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
def test_editing_an_activity_is_allowed_with_write_permission(
    as_user, utente_con_arnia, db, method
):
    """The same requests succeed once the association grants write."""
    utente, arnia = utente_con_arnia("write")
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
