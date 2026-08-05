"""Tests for the accessi repository (meshbee_core/repository/accessi.py).

The upsert revives and re-levels associations, which is easy to get subtly
wrong: a revoked association that comes back at the wrong permission level is a
silent authorization bug.
"""
from meshbee_core.repository import accessi


def test_a_grant_creates_an_active_association(db, make_utente, make_arnia):
    utente, arnia = make_utente(), make_arnia()

    accessi.upsert(db, utente["id_utente"], arnia["id_arnia"], "read")

    assert accessi.get_permesso(db, utente["id_utente"], arnia["id_arnia"])["permessi"] == "read"


def test_granting_again_changes_the_permission_level(db, make_utente, make_arnia):
    """UNIQUE(id_utente, id_arnia) means the second grant must update, not fail."""
    utente, arnia = make_utente(), make_arnia()
    accessi.upsert(db, utente["id_utente"], arnia["id_arnia"], "read")

    accessi.upsert(db, utente["id_utente"], arnia["id_arnia"], "admin")

    assert accessi.get_permesso(db, utente["id_utente"], arnia["id_arnia"])["permessi"] == "admin"


def test_a_revoked_association_is_invisible(db, make_utente, make_arnia):
    """Revoking is a soft delete, so the lookup has to filter on attivo."""
    utente, arnia = make_utente(), make_arnia()
    accessi.upsert(db, utente["id_utente"], arnia["id_arnia"], "write")

    accessi.deactivate(db, utente["id_utente"], arnia["id_arnia"])

    assert accessi.get_permesso(db, utente["id_utente"], arnia["id_arnia"]) is None


def test_granting_again_revives_a_revoked_association(db, make_utente, make_arnia):
    """
    Re-granting clears the revocation date as well as the flag.

    Leaving data_disassociazione set would leave a row that reads as both active
    and revoked.
    """
    utente, arnia = make_utente(), make_arnia()
    accessi.upsert(db, utente["id_utente"], arnia["id_arnia"], "write")
    accessi.deactivate(db, utente["id_utente"], arnia["id_arnia"])

    accessi.upsert(db, utente["id_utente"], arnia["id_arnia"], "read")

    assert accessi.get_permesso(db, utente["id_utente"], arnia["id_arnia"])["permessi"] == "read"
    db.execute(
        "SELECT data_disassociazione FROM utenti_arnie WHERE id_utente = %s AND id_arnia = %s",
        (utente["id_utente"], arnia["id_arnia"]),
    )
    assert db.fetchone()["data_disassociazione"] is None


def test_revoking_an_absent_association_reports_nothing(db, make_utente, make_arnia):
    """The service turns this into a 404 rather than a silent success."""
    utente, arnia = make_utente(), make_arnia()

    assert accessi.deactivate(db, utente["id_utente"], arnia["id_arnia"]) is None


def test_revoking_twice_reports_nothing_the_second_time(db, make_utente, make_arnia):
    """`attivo = true` is in the WHERE clause, so the second call matches no row."""
    utente, arnia = make_utente(), make_arnia()
    accessi.upsert(db, utente["id_utente"], arnia["id_arnia"], "read")

    assert accessi.deactivate(db, utente["id_utente"], arnia["id_arnia"]) is not None
    assert accessi.deactivate(db, utente["id_utente"], arnia["id_arnia"]) is None
