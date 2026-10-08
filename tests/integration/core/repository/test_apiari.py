"""Tests for the apiari repository (meshbee_core/repository/apiari.py).

The weight is on visibility: access is granted per hive, so which apiari a user
can see is a query over `arnie` and `utenti_arnie`, and every condition in it is
an access rule.
"""

from meshbee_core.repository import apiari


def visible_ids(session, utente):
    return [
        a["id_apiario"] for a in apiari.list_for_utente(session, utente["id_utente"])
    ]


def test_a_user_sees_the_apiario_of_a_hive_they_are_associated_with(
    session, make_utente, make_apiario, make_arnia, grant_access
):
    utente, mine, other = make_utente(), make_apiario(), make_apiario()
    grant_access(utente["id_utente"], make_arnia(apiario=mine)["id_arnia"])
    make_arnia(apiario=other)

    assert visible_ids(session, utente) == [mine["id_apiario"]]
    assert apiari.is_visible_to(session, utente["id_utente"], mine["id_apiario"])
    assert not apiari.is_visible_to(session, utente["id_utente"], other["id_apiario"])


def test_two_hives_in_one_apiario_list_it_once(
    session, make_utente, make_apiario, make_arnia, grant_access
):
    """The join fans out per hive; the list must not."""
    utente, apiario = make_utente(), make_apiario()
    for _ in range(2):
        grant_access(utente["id_utente"], make_arnia(apiario=apiario)["id_arnia"])

    assert visible_ids(session, utente) == [apiario["id_apiario"]]


def test_a_revoked_association_hides_the_apiario(
    session, make_utente, make_apiario, make_arnia, grant_access
):
    utente, apiario = make_utente(), make_apiario()
    arnia = make_arnia(apiario=apiario)
    grant_access(utente["id_utente"], arnia["id_arnia"], attivo=False)

    assert visible_ids(session, utente) == []
    assert not apiari.is_visible_to(session, utente["id_utente"], apiario["id_apiario"])


def test_a_retired_hive_does_not_open_its_apiario(
    session, db, make_utente, make_apiario, make_arnia, grant_access
):
    """The same rule as the hive list: a retired hive is out of the user's view."""
    utente, apiario = make_utente(), make_apiario()
    arnia = make_arnia(apiario=apiario)
    grant_access(utente["id_utente"], arnia["id_arnia"])
    db.execute(
        "UPDATE arnie SET attiva = false WHERE id_arnia = %s", (arnia["id_arnia"],)
    )

    assert visible_ids(session, utente) == []


def test_a_retired_apiario_is_left_out_of_the_lists(
    session, make_utente, make_apiario, make_arnia, grant_access
):
    utente, apiario = make_utente(), make_apiario(attivo=False)
    grant_access(utente["id_utente"], make_arnia(apiario=apiario)["id_arnia"])

    assert visible_ids(session, utente) == []
    assert apiari.list_attivi(session) == []
    assert [a["id_apiario"] for a in apiari.list_all(session)] == [
        apiario["id_apiario"]
    ]


def test_only_active_hives_are_counted(session, db, make_apiario, make_arnia):
    """What stands between an apiary and its retirement."""
    apiario = make_apiario()
    make_arnia(apiario=apiario)
    retired = make_arnia(apiario=apiario)
    make_arnia()
    db.execute(
        "UPDATE arnie SET attiva = false WHERE id_arnia = %s", (retired["id_arnia"],)
    )

    assert apiari.count_arnie_attive(session, apiario["id_apiario"]) == 1


def test_switching_attivo_stamps_and_clears_the_removal_date(session, make_apiario):
    """A revived apiary must not keep the date of a removal that no longer holds."""
    apiario = make_apiario()

    retired = apiari.update(session, apiario["id_apiario"], attivo=False)
    assert retired["attivo"] is False
    assert retired["data_disattivazione"] is not None

    revived = apiari.update(session, apiario["id_apiario"], attivo=True)
    assert revived["attivo"] is True
    assert revived["data_disattivazione"] is None


def test_update_leaves_unmentioned_columns_alone(session, make_apiario):
    apiario = make_apiario(nome_apiario="Collina")

    updated = apiari.update(
        session, apiario["id_apiario"], posizione="Collina sud", nome_apiario=None
    )

    assert updated["nome_apiario"] == "Collina"
    assert updated["posizione"] == "Collina sud"


def test_deleting_the_owner_keeps_the_apiario(session, db, make_utente, make_apiario):
    """ON DELETE SET NULL: the owner is information, not something the apiary hangs on."""
    owner = make_utente()
    apiario = make_apiario(proprietario=owner)

    db.execute("DELETE FROM utenti WHERE id_utente = %s", (owner["id_utente"],))

    assert apiari.get(session, apiario["id_apiario"])["id_utente_proprietario"] is None
