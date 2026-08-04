"""Authorization matrix over every endpoint in api/main.py.

One table, three sweeps: no credentials, a non-admin on admin routes, and a user
with no association on arnia-scoped routes. A gate that goes missing during the
refactor fails here, whatever else still works.

Note on the unauthenticated status: FastAPI's HTTPBearer answers a missing
Authorization header with **403 "Not authenticated"**, not 401. That is the
framework default, asserted here as the current contract rather than endorsed.
"""
import pytest

# Every endpoint reachable without a token.
PUBLIC = [
    ("post", "/api/auth/login", {"email": "a@b.org", "password": "x"}),
    ("get", "/", None),
    ("get", "/health", None),
]

# Admin-only: Depends(get_current_admin_user).
ADMIN_ONLY = [
    ("get", "/api/admin/utenti", None),
    ("post", "/api/admin/utenti",
     {"email": "n@b.org", "nome": "N", "cognome": "C", "password": "secret123"}),
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
    ("post", "/api/admin/utenti-arnie", {"id_utente": 1, "id_arnia": 1, "permessi": "read"}),
    ("delete", "/api/admin/utenti-arnie?id_utente=1&id_arnia=1", None),
    ("get", "/api/admin/letture", None),
    ("post", "/api/admin/letture", {"id_arnia": 1, "id_nodo": "NODE-X"}),
    ("get", "/api/admin/attivita", None),
]

# Authenticated but not scoped to a single arnia.
USER_GLOBAL = [
    ("get", "/api/auth/me", None),
    ("get", "/api/user/arnie", None),
    ("put", "/api/user/password", {"new_password": "secret123", "current_password": "old"}),
]

# Scoped to {id_arnia}: guarded by check_user_arnia_access. `{}` is substituted.
ARNIA_SCOPED = [
    ("get", "/api/user/arnie/{}", None),
    ("put", "/api/user/arnie/{}", {}),
    ("get", "/api/user/arnie/{}/letture", None),
    ("get", "/api/user/arnie/{}/letture/temperatura", None),
    ("get", "/api/user/arnie/{}/letture/umidita", None),
    ("get", "/api/user/arnie/{}/letture/peso", None),
    ("get", "/api/user/arnie/{}/attivita", None),
    ("post", "/api/user/arnie/{}/attivita", {"id_arnia": 1, "tipo_attivita": "ispezione"}),
    ("patch", "/api/user/arnie/{}/attivita/1", {}),
    ("delete", "/api/user/arnie/{}/attivita/1", None),
]

PROTECTED = ADMIN_ONLY + USER_GLOBAL + [(m, p.format(1), b) for m, p, b in ARNIA_SCOPED]


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
    """Every non-public endpoint refuses a request with no Authorization header."""
    assert call(client, method, path, body).status_code == 403


@pytest.mark.parametrize("method, path, body", PUBLIC, ids=ids(PUBLIC))
def test_public_endpoints_do_not_require_a_token(client, method, path, body):
    """Login, root and health stay reachable without credentials."""
    assert call(client, method, path, body).status_code != 403


# ============================================
# Admin gate
# ============================================


@pytest.mark.parametrize("method, path, body", ADMIN_ONLY, ids=ids(ADMIN_ONLY))
def test_admin_endpoints_reject_a_regular_user(as_user, make_utente, method, path, body):
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
    response = call(as_user(make_utente()), method, path.format(arnia["id_arnia"]), body)

    assert response.status_code == 403


@pytest.mark.parametrize("method, path, body", ARNIA_SCOPED, ids=ids(ARNIA_SCOPED))
def test_arnia_endpoints_admit_an_associated_user(
    as_user, utente_con_arnia, method, path, body
):
    """An association with admin permission clears every per-arnia gate."""
    utente, arnia = utente_con_arnia("admin")
    response = call(as_user(utente), method, path.format(arnia["id_arnia"]), body)

    assert response.status_code != 403


def test_admins_reach_arnie_they_are_not_associated_with(as_user, make_utente, make_arnia):
    """check_user_arnia_access short-circuits for admins, so no association is needed."""
    arnia = make_arnia()
    response = as_user(make_utente(ruolo="admin")).get(f"/api/user/arnie/{arnia['id_arnia']}")

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
def test_editing_an_activity_only_requires_read_permission(
    as_user, utente_con_arnia, db, method
):
    """
    Known asymmetry: creating an activity needs "write", but editing or deleting
    one calls check_user_arnia_access without a permission argument, so it
    defaults to "read".

    A read-only collaborator can therefore delete activities they authored, which
    they were never allowed to create. Pinned so the inconsistency is visible.
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

    assert response.status_code == 200
