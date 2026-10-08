"""The /api/user/arnie/{id}/attivita CRUD endpoints."""

from datetime import datetime, timedelta

import pytest

NOW = datetime(2026, 6, 1, 12, 0, 0)


@pytest.fixture
def scrittore(utente_con_arnia):
    """A user who may log activities on an arnia: a collaborator."""
    return utente_con_arnia("collaborator")


# ============================================
# POST .../attivita
# ============================================


def test_creating_an_activity_returns_it(as_user, scrittore):
    """The INSERT ... RETURNING hands back the stored row."""
    utente, arnia = scrittore

    response = as_user(utente).post(
        f"/api/user/arnie/{arnia['id_arnia']}/attivita",
        json={
            "id_arnia": arnia["id_arnia"],
            "tipo_attivita": "ispezione",
            "descrizione": "Controllo covata",
        },
    )

    assert response.status_code == 200
    assert response.json()["tipo_attivita"] == "ispezione"
    assert response.json()["descrizione"] == "Controllo covata"
    assert response.json()["id_log"] is not None


def test_a_created_activity_is_attributed_to_its_author(as_user, scrittore, db):
    """id_utente comes from the token, not the body — authorship cannot be spoofed."""
    utente, arnia = scrittore

    body = (
        as_user(utente)
        .post(
            f"/api/user/arnie/{arnia['id_arnia']}/attivita",
            json={
                "id_arnia": arnia["id_arnia"],
                "tipo_attivita": "ispezione",
                "id_utente": 999,
            },
        )
        .json()
    )

    assert body["id_utente"] == utente["id_utente"]


def test_a_created_activity_belongs_to_the_arnia_in_the_path(
    as_user, scrittore, make_arnia
):
    """The path parameter wins over any id_arnia in the body."""
    utente, arnia = scrittore
    other = make_arnia()

    body = (
        as_user(utente)
        .post(
            f"/api/user/arnie/{arnia['id_arnia']}/attivita",
            json={"id_arnia": other["id_arnia"], "tipo_attivita": "ispezione"},
        )
        .json()
    )

    assert body["id_arnia"] == arnia["id_arnia"]


def test_a_created_activity_persists(as_user, scrittore, db):
    """The row is really committed to log_attivita within the request."""
    utente, arnia = scrittore

    as_user(utente).post(
        f"/api/user/arnie/{arnia['id_arnia']}/attivita",
        json={"id_arnia": arnia["id_arnia"], "tipo_attivita": "raccolta_miele"},
    )

    db.execute(
        "SELECT tipo_attivita FROM log_attivita WHERE id_arnia = %s",
        (arnia["id_arnia"],),
    )
    assert db.fetchone()["tipo_attivita"] == "raccolta_miele"


def test_creating_an_activity_stores_structured_data(as_user, scrittore):
    """`dati` is serialised to JSONB and comes back as an object."""
    utente, arnia = scrittore

    body = (
        as_user(utente)
        .post(
            f"/api/user/arnie/{arnia['id_arnia']}/attivita",
            json={
                "id_arnia": arnia["id_arnia"],
                "tipo_attivita": "trattamento",
                "dati": {"prodotto": "acido ossalico", "dosaggio_ml": 5},
            },
        )
        .json()
    )

    assert body["dati"] == {"prodotto": "acido ossalico", "dosaggio_ml": 5}


def test_creating_an_activity_defaults_the_timestamp_to_now(as_user, scrittore):
    """COALESCE(%s, CURRENT_TIMESTAMP) fills in the time when the client omits it."""
    utente, arnia = scrittore

    body = (
        as_user(utente)
        .post(
            f"/api/user/arnie/{arnia['id_arnia']}/attivita",
            json={"id_arnia": arnia["id_arnia"], "tipo_attivita": "ispezione"},
        )
        .json()
    )

    assert body["timestamp"] is not None


def test_an_unsupported_activity_type_is_rejected(as_user, scrittore):
    """
    An unknown tipo_attivita is a validation error, not a server fault.

    The TipoAttivita literal rejects it at the edge, so the CHECK constraint in
    the database is never reached and the client is told which field was wrong.
    """
    utente, arnia = scrittore

    response = as_user(utente).post(
        f"/api/user/arnie/{arnia['id_arnia']}/attivita",
        json={"id_arnia": arnia["id_arnia"], "tipo_attivita": "festa_delle_api"},
    )

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"][-1] == "tipo_attivita"


def test_an_unsupported_activity_type_is_rejected_on_update(
    as_user, scrittore, make_attivita
):
    """The same constraint applies when editing an existing activity."""
    utente, arnia = scrittore
    attivita = make_attivita(arnia, utente)

    response = as_user(utente).patch(
        f"/api/user/arnie/{arnia['id_arnia']}/attivita/{attivita['id_log']}",
        json={"tipo_attivita": "festa_delle_api"},
    )

    assert response.status_code == 422


# ============================================
# GET .../attivita
# ============================================


def test_activities_are_returned_newest_first(as_user, scrittore, make_attivita):
    """ORDER BY timestamp DESC."""
    utente, arnia = scrittore
    for hours in (2, 1, 0):
        make_attivita(arnia, utente, timestamp=NOW - timedelta(hours=hours))

    body = as_user(utente).get(f"/api/user/arnie/{arnia['id_arnia']}/attivita").json()

    timestamps = [row["timestamp"] for row in body]
    assert timestamps == sorted(timestamps, reverse=True)


def test_activities_are_scoped_to_the_arnia(
    as_user, scrittore, make_arnia, make_attivita
):
    """Another arnia's log never leaks in."""
    utente, arnia = scrittore
    other = make_arnia(apiario=utente)
    make_attivita(arnia, utente)
    make_attivita(other, utente)

    body = as_user(utente).get(f"/api/user/arnie/{arnia['id_arnia']}/attivita").json()

    assert {row["id_arnia"] for row in body} == {arnia["id_arnia"]}


def test_activities_can_be_filtered_by_type(as_user, scrittore, make_attivita):
    """The optional tipo_attivita filter is appended to the WHERE clause."""
    utente, arnia = scrittore
    make_attivita(arnia, utente, tipo_attivita="ispezione")
    make_attivita(arnia, utente, tipo_attivita="raccolta_miele")

    body = (
        as_user(utente)
        .get(
            f"/api/user/arnie/{arnia['id_arnia']}/attivita",
            params={"tipo_attivita": "ispezione"},
        )
        .json()
    )

    assert [row["tipo_attivita"] for row in body] == ["ispezione"]


def test_activities_include_every_selected_column(as_user, scrittore, make_attivita):
    """The SELECT lists columns by name."""
    utente, arnia = scrittore
    make_attivita(arnia, utente)

    row = as_user(utente).get(f"/api/user/arnie/{arnia['id_arnia']}/attivita").json()[0]

    assert set(row) == {
        "id_log",
        "id_utente",
        "id_arnia",
        "timestamp",
        "tipo_attivita",
        "descrizione",
        "dati",
    }


def test_activities_respect_the_limit(as_user, scrittore, make_attivita):
    """LIMIT caps the log listing."""
    utente, arnia = scrittore
    for _ in range(3):
        make_attivita(arnia, utente)

    body = (
        as_user(utente)
        .get(f"/api/user/arnie/{arnia['id_arnia']}/attivita", params={"limit": 2})
        .json()
    )

    assert len(body) == 2


@pytest.mark.parametrize("limit", [0, 1001])
def test_activities_reject_an_out_of_range_limit(as_user, scrittore, limit):
    """The Query bounds here are 1..1000, tighter than for readings."""
    utente, arnia = scrittore

    response = as_user(utente).get(
        f"/api/user/arnie/{arnia['id_arnia']}/attivita", params={"limit": limit}
    )

    assert response.status_code == 422


# ============================================
# PATCH .../attivita/{id_log}
# ============================================


def test_updating_an_activity_changes_the_named_fields(
    as_user, scrittore, make_attivita
):
    """A partial update rewrites only what was sent."""
    utente, arnia = scrittore
    attivita = make_attivita(arnia, utente, descrizione="Prima nota")

    response = as_user(utente).patch(
        f"/api/user/arnie/{arnia['id_arnia']}/attivita/{attivita['id_log']}",
        json={"descrizione": "Nota corretta"},
    )

    assert response.status_code == 200
    assert response.json()["descrizione"] == "Nota corretta"
    assert response.json()["tipo_attivita"] == attivita["tipo_attivita"]


def test_updating_an_activity_persists(as_user, scrittore, make_attivita, db):
    """The dynamic UPDATE really writes."""
    utente, arnia = scrittore
    attivita = make_attivita(arnia, utente)

    as_user(utente).patch(
        f"/api/user/arnie/{arnia['id_arnia']}/attivita/{attivita['id_log']}",
        json={"descrizione": "Nota corretta"},
    )

    db.execute(
        "SELECT descrizione FROM log_attivita WHERE id_log = %s", (attivita["id_log"],)
    )
    assert db.fetchone()["descrizione"] == "Nota corretta"


def test_updating_with_an_empty_body_returns_the_activity_unchanged(
    as_user, scrittore, make_attivita
):
    """No fields to set short-circuits to a plain read rather than building an empty UPDATE."""
    utente, arnia = scrittore
    attivita = make_attivita(arnia, utente, descrizione="Invariata")

    response = as_user(utente).patch(
        f"/api/user/arnie/{arnia['id_arnia']}/attivita/{attivita['id_log']}", json={}
    )

    assert response.status_code == 200
    assert response.json()["descrizione"] == "Invariata"


def test_a_user_cannot_update_someone_elses_activity(
    as_user, scrittore, make_utente, make_attivita
):
    """The ownership check includes id_utente, so another author's row is a 404."""
    utente, arnia = scrittore
    attivita = make_attivita(arnia, make_utente())

    response = as_user(utente).patch(
        f"/api/user/arnie/{arnia['id_arnia']}/attivita/{attivita['id_log']}",
        json={"descrizione": "Non mia"},
    )

    assert response.status_code == 404


def test_updating_a_missing_activity_is_404(as_user, scrittore):
    """An id_log that does not exist is not found."""
    utente, arnia = scrittore

    response = as_user(utente).patch(
        f"/api/user/arnie/{arnia['id_arnia']}/attivita/999999",
        json={"descrizione": "x"},
    )

    assert response.status_code == 404


# ============================================
# DELETE .../attivita/{id_log}
# ============================================


def test_deleting_an_activity_removes_it(as_user, scrittore, make_attivita, db):
    """The DELETE ... RETURNING confirms a row was actually removed."""
    utente, arnia = scrittore
    attivita = make_attivita(arnia, utente)

    response = as_user(utente).delete(
        f"/api/user/arnie/{arnia['id_arnia']}/attivita/{attivita['id_log']}"
    )

    assert response.status_code == 200
    db.execute("SELECT 1 FROM log_attivita WHERE id_log = %s", (attivita["id_log"],))
    assert db.fetchone() is None


def test_a_user_cannot_delete_someone_elses_activity(
    as_user, scrittore, make_utente, make_attivita, db
):
    """Another author's row is a 404 and stays in the table."""
    utente, arnia = scrittore
    attivita = make_attivita(arnia, make_utente())

    response = as_user(utente).delete(
        f"/api/user/arnie/{arnia['id_arnia']}/attivita/{attivita['id_log']}"
    )

    assert response.status_code == 404
    db.execute("SELECT 1 FROM log_attivita WHERE id_log = %s", (attivita["id_log"],))
    assert db.fetchone() is not None


def test_deleting_a_missing_activity_is_404(as_user, scrittore):
    """Nothing to delete is not found."""
    utente, arnia = scrittore

    response = as_user(utente).delete(
        f"/api/user/arnie/{arnia['id_arnia']}/attivita/999999"
    )

    assert response.status_code == 404
