"""The /api/user/arnie endpoints: listing, detail and update."""

import pytest

# ============================================
# GET /api/user/arnie
# ============================================


def test_listing_returns_only_the_arnie_the_user_can_reach(
    as_user, utente_con_arnia, make_arnia, make_utente
):
    """Owned or shared through their apiary; anyone else's stays invisible."""
    utente, shared = utente_con_arnia("viewer")
    owned = make_arnia(apiario=utente)
    make_arnia()  # unassigned
    make_arnia(apiario=make_utente())  # someone else's, not shared

    body = as_user(utente).get("/api/user/arnie").json()

    assert {(a["id_arnia"], a["accesso"]) for a in body} == {
        (shared["id_arnia"], "viewer"),
        (owned["id_arnia"], "owner"),
    }


def test_revoking_a_share_hides_its_hives(as_user, utente_con_arnia, db):
    utente, _ = utente_con_arnia("manager")
    db.execute("DELETE FROM utenti_apiari WHERE id_utente = %s", (utente["id_utente"],))

    assert as_user(utente).get("/api/user/arnie").json() == []


def test_listing_excludes_deactivated_arnie(as_user, utente_con_arnia, db):
    """`vs.attiva = true`: an arnia taken out of service drops off the list."""
    utente, arnia = utente_con_arnia("viewer")
    db.execute(
        "UPDATE arnie SET attiva = false WHERE id_arnia = %s", (arnia["id_arnia"],)
    )

    assert as_user(utente).get("/api/user/arnie").json() == []


def test_admins_see_every_active_arnia(as_user, make_utente, make_arnia):
    """The admin branch skips utenti_arnie entirely."""
    first, second = make_arnia(), make_arnia()

    body = as_user(make_utente(ruolo="admin")).get("/api/user/arnie").json()

    assert {a["id_arnia"] for a in body} == {first["id_arnia"], second["id_arnia"]}


def test_listing_carries_the_latest_readings(as_user, utente_con_arnia, make_lettura):
    """The hive list surfaces the most recent values alongside the arnia."""
    utente, arnia = utente_con_arnia("viewer")
    make_lettura(
        arnia, temperatura="35.5", umidita="60.0", peso="42.250", batteria="3.85"
    )

    row = as_user(utente).get("/api/user/arnie").json()[0]

    assert float(row["ultima_temperatura"]) == 35.5
    assert float(row["ultima_umidita"]) == 60.0
    assert float(row["ultimo_peso"]) == 42.25
    assert float(row["ultima_batteria"]) == 3.85
    assert row["ultimo_aggiornamento"] is not None


def test_listing_is_empty_for_a_user_with_no_arnie(as_user, make_utente):
    """No associations means an empty list, not an error."""
    response = as_user(make_utente()).get("/api/user/arnie")

    assert response.status_code == 200
    assert response.json() == []


# ============================================
# GET /api/user/arnie/{id_arnia}
# ============================================


def test_detail_returns_the_arnia(as_user, utente_con_arnia):
    """A read association is enough to fetch the detail view."""
    utente, arnia = utente_con_arnia("viewer")

    response = as_user(utente).get(f"/api/user/arnie/{arnia['id_arnia']}")

    assert response.status_code == 200
    assert response.json()["id_arnia"] == arnia["id_arnia"]
    assert response.json()["nome_arnia"] == arnia["nome_arnia"]


def test_detail_of_a_missing_arnia_is_404_for_an_admin(as_user, make_utente):
    """
    Only admins can reach the 404: for anyone else check_user_arnia_access
    fails first, so a non-existent arnia is indistinguishable from a forbidden
    one — which is the safer answer anyway.
    """
    response = as_user(make_utente(ruolo="admin")).get("/api/user/arnie/999999")

    assert response.status_code == 404


# ============================================
# PUT /api/user/arnie/{id_arnia}
# ============================================


def test_update_changes_the_named_fields(as_user, utente_con_arnia):
    """A manager can rename and reposition the arnia."""
    utente, arnia = utente_con_arnia("manager")

    response = as_user(utente).put(
        f"/api/user/arnie/{arnia['id_arnia']}",
        json={"nome_arnia": "Arnia Gamma", "posizione": "Fila 2"},
    )

    assert response.status_code == 200
    assert response.json()["nome_arnia"] == "Arnia Gamma"
    assert response.json()["posizione"] == "Fila 2"


def test_update_persists(as_user, utente_con_arnia, db):
    """The UPDATE is really written, not just echoed back."""
    utente, arnia = utente_con_arnia("manager")

    as_user(utente).put(
        f"/api/user/arnie/{arnia['id_arnia']}", json={"nome_arnia": "Arnia Gamma"}
    )

    db.execute("SELECT nome_arnia FROM arnie WHERE id_arnia = %s", (arnia["id_arnia"],))
    assert db.fetchone()["nome_arnia"] == "Arnia Gamma"


def test_update_leaves_unmentioned_fields_alone(as_user, utente_con_arnia, db):
    """COALESCE means omitting a field keeps its stored value rather than nulling it."""
    utente, arnia = utente_con_arnia("manager")
    db.execute(
        "UPDATE arnie SET descrizione = %s WHERE id_arnia = %s",
        ("Regina ligustica", arnia["id_arnia"]),
    )

    response = as_user(utente).put(
        f"/api/user/arnie/{arnia['id_arnia']}", json={"nome_arnia": "Arnia Gamma"}
    )

    assert response.json()["descrizione"] == "Regina ligustica"


def test_update_can_set_coordinates(as_user, utente_con_arnia):
    """Coordinates round-trip through the Decimal columns."""
    utente, arnia = utente_con_arnia("manager")

    response = as_user(utente).put(
        f"/api/user/arnie/{arnia['id_arnia']}",
        json={"latitudine": "45.464200", "longitudine": "9.190000"},
    )

    assert float(response.json()["latitudine"]) == 45.4642
    assert float(response.json()["longitudine"]) == 9.19


@pytest.mark.parametrize(
    "payload",
    [
        {"latitudine": "91"},
        {"latitudine": "-91"},
        {"longitudine": "181"},
        {"longitudine": "-181"},
    ],
)
def test_update_rejects_out_of_range_coordinates(as_user, utente_con_arnia, payload):
    """ArniaUpdate bounds are enforced at the edge, before the UPDATE runs."""
    utente, arnia = utente_con_arnia("manager")

    response = as_user(utente).put(f"/api/user/arnie/{arnia['id_arnia']}", json=payload)

    assert response.status_code == 422


def test_a_manager_cannot_retire_an_arnia(as_user, utente_con_arnia, db):
    """
    Retiring is the owner's call: for a manager `attiva` is ignored, so the
    edit goes through and the hive stays in service.
    """
    utente, arnia = utente_con_arnia("manager")

    as_user(utente).put(f"/api/user/arnie/{arnia['id_arnia']}", json={"attiva": False})

    db.execute("SELECT attiva FROM arnie WHERE id_arnia = %s", (arnia["id_arnia"],))
    assert db.fetchone()["attiva"] is True


def test_the_owner_can_retire_their_arnia(as_user, utente_con_arnia, db):
    utente, arnia = utente_con_arnia("owner")

    response = as_user(utente).put(
        f"/api/user/arnie/{arnia['id_arnia']}", json={"attiva": False}
    )

    assert response.status_code == 200
    db.execute("SELECT attiva FROM arnie WHERE id_arnia = %s", (arnia["id_arnia"],))
    assert db.fetchone()["attiva"] is False
