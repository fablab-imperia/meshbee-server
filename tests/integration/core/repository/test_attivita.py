"""Tests for the attivita repository (meshbee_core/repository/attivita.py).

`update` assembles its SET clause from caller-supplied names and JSON-encodes
one column on the way past, which is the part worth pinning against a real
database.
"""

from datetime import datetime

import pytest

from meshbee_core.paging import Paging
from meshbee_core.repository import attivita

# A window wide enough for every fixture row. Datetimes, not strings: the API
# hands the repository parsed values, and psycopg 3 binds a str as VARCHAR,
# which Postgres will not compare with a timestamp.
EVER = (datetime(2000, 1, 1), datetime(2100, 1, 1))


def test_the_dati_column_is_stored_as_json(session, db, make_arnia, make_utente):
    """`dati` is JSONB: it goes in encoded and comes back as a dict."""
    arnia, utente = make_arnia(), make_utente()

    row = attivita.insert(
        session,
        id_utente=utente["id_utente"],
        id_arnia=arnia["id_arnia"],
        timestamp=None,
        tipo_attivita="ispezione",
        descrizione="Controllo",
        dati={"telaini_miele": 8, "covata_presente": True},
    )

    assert row["dati"] == {"telaini_miele": 8, "covata_presente": True}


def test_updating_dati_re_encodes_it(
    session, db, make_arnia, make_utente, make_attivita
):
    """
    The update path JSON-encodes `dati` too, not just the insert.

    Passing the dict straight through would store a Python repr with single
    quotes, which is not valid JSON.
    """
    arnia, utente = make_arnia(), make_utente()
    logged = make_attivita(arnia, utente)

    updated = attivita.update(
        session, logged["id_log"], {"dati": {"regina_vista": True}}
    )

    assert updated["dati"] == {"regina_vista": True}


def test_other_columns_update_without_encoding(
    session, db, make_arnia, make_utente, make_attivita
):
    """Only `dati` gets the JSON treatment."""
    arnia, utente = make_arnia(), make_utente()
    logged = make_attivita(arnia, utente, descrizione="Prima")

    updated = attivita.update(session, logged["id_log"], {"descrizione": "Dopo"})

    assert updated["descrizione"] == "Dopo"


def test_an_unknown_column_is_refused(
    session, db, make_arnia, make_utente, make_attivita
):
    """
    The whitelist guards the assembled SET clause.

    Notably it blocks `id_utente` and `id_arnia`: the update comes from a PATCH
    body, so without this a user could reassign their entry to another hive.
    """
    arnia, utente = make_arnia(), make_utente()
    logged = make_attivita(arnia, utente)

    with pytest.raises(ValueError, match="non aggiornabili"):
        attivita.update(session, logged["id_log"], {"id_arnia": 999})


def test_ownership_requires_both_the_arnia_and_the_user(
    session, db, make_arnia, make_utente, make_attivita
):
    """Either mismatch means not found, which the service turns into a 404."""
    arnia, other_arnia = make_arnia(), make_arnia()
    utente, other_utente = make_utente(), make_utente()
    logged = make_attivita(arnia, utente)

    assert attivita.find_owned(
        session, logged["id_log"], arnia["id_arnia"], utente["id_utente"]
    )
    assert (
        attivita.find_owned(
            session, logged["id_log"], other_arnia["id_arnia"], utente["id_utente"]
        )
        is None
    )
    assert (
        attivita.find_owned(
            session, logged["id_log"], arnia["id_arnia"], other_utente["id_utente"]
        )
        is None
    )


def test_deleting_is_scoped_the_same_way(
    session, db, make_arnia, make_utente, make_attivita
):
    """Someone else's entry survives a delete aimed at it."""
    arnia, utente = make_arnia(), make_utente()
    other = make_utente()
    logged = make_attivita(arnia, utente)

    assert (
        attivita.delete_owned(
            session, logged["id_log"], arnia["id_arnia"], other["id_utente"]
        )
        is None
    )
    assert attivita.find_owned(
        session, logged["id_log"], arnia["id_arnia"], utente["id_utente"]
    )


def test_the_type_filter_narrows_the_list(
    session, db, make_arnia, make_utente, make_attivita
):
    """The optional filter appends a clause rather than replacing the query."""
    arnia, utente = make_arnia(), make_utente()
    make_attivita(arnia, utente, tipo_attivita="ispezione")
    make_attivita(arnia, utente, tipo_attivita="raccolta_miele")

    rows = attivita.list_by_arnia(
        session, arnia["id_arnia"], *EVER, Paging(limit=10), "raccolta_miele"
    ).items

    assert [r["tipo_attivita"] for r in rows] == ["raccolta_miele"]


def test_without_a_filter_every_type_is_returned(
    session, db, make_arnia, make_utente, make_attivita
):
    """The clause really is optional."""
    arnia, utente = make_arnia(), make_utente()
    make_attivita(arnia, utente, tipo_attivita="ispezione")
    make_attivita(arnia, utente, tipo_attivita="raccolta_miele")

    rows = attivita.list_by_arnia(
        session, arnia["id_arnia"], *EVER, Paging(limit=10)
    ).items

    assert len(rows) == 2
