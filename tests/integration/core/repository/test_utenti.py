"""Tests for the utenti repository (meshbee_core/repository/utenti.py).

Focused on `update`, whose SET clause is assembled from caller-supplied column
names, and on the projection that must never carry password_hash.
"""

import pytest

from meshbee_core.repository import utenti


def test_the_public_projection_never_carries_the_password_hash(
    session, db, make_utente
):
    """
    Responses are built straight from these rows.

    The column is simply absent from the projection rather than stripped later,
    so a new endpoint returning a user row cannot leak it by forgetting to.
    """
    utente = make_utente()

    row = utenti.get_by_email(session, utente["email"])

    assert "password_hash" not in row
    assert "password_hash" not in utenti.list_all(session)[0]
    assert "password_hash" not in utenti.update(
        session, utente["id_utente"], {"nome": "X"}
    )


def test_the_login_projection_does_carry_it(session, db, make_utente):
    """Authentication is the one caller that needs the hash."""
    utente = make_utente(password_hash="hashed-value")

    assert (
        utenti.get_credentials_by_email(session, utente["email"])["password_hash"]
        == "hashed-value"
    )


def test_only_the_named_columns_change(session, db, make_utente):
    """A partial update leaves everything it was not given alone."""
    utente = make_utente(nome="Giulia", cognome="Rossi")

    updated = utenti.update(session, utente["id_utente"], {"nome": "Marta"})

    assert updated["nome"] == "Marta"
    assert updated["cognome"] == "Rossi"
    assert updated["email"] == utente["email"]


def test_an_unknown_column_is_refused(session, db, make_utente):
    """
    The whitelist is what keeps the assembled SET clause safe.

    Callers pass fixed names today, so this is a programming error rather than
    reachable input — but the clause is built by string formatting.
    """
    utente = make_utente()

    with pytest.raises(ValueError, match="non aggiornabili"):
        utenti.update(session, utente["id_utente"], {"password_hash": "injected"})


def test_password_hash_cannot_be_set_through_the_generic_update(
    session, db, make_utente
):
    """Passwords go through set_password_hash, which hashes on the way in."""
    utente = make_utente(password_hash="original")

    with pytest.raises(ValueError):
        utenti.update(session, utente["id_utente"], {"password_hash": "plaintext"})

    assert (
        utenti.get_credentials_by_email(session, utente["email"])["password_hash"]
        == "original"
    )


def test_deactivating_stamps_the_date_when_asked(session, db, make_utente):
    """The service asks for the stamp; the repository does not decide."""
    utente = make_utente()

    utenti.update(
        session, utente["id_utente"], {"attivo": False}, stamp_disattivazione=True
    )

    db.execute(
        "SELECT data_disattivazione FROM utenti WHERE id_utente = %s",
        (utente["id_utente"],),
    )
    assert db.fetchone()["data_disattivazione"] is not None


def test_an_ordinary_update_does_not_stamp_the_date(session, db, make_utente):
    """Renaming someone must not look like a deactivation."""
    utente = make_utente()

    utenti.update(session, utente["id_utente"], {"nome": "Marta"})

    db.execute(
        "SELECT data_disattivazione FROM utenti WHERE id_utente = %s",
        (utente["id_utente"],),
    )
    assert db.fetchone()["data_disattivazione"] is None


def test_updating_a_missing_user_returns_nothing(session, db):
    """The caller turns this into a 404."""
    assert utenti.update(session, 999999, {"nome": "X"}) is None


def test_the_last_access_stamp_is_refreshed(session, db, make_utente):
    """Recorded on a successful login, and nowhere else."""
    utente = make_utente()
    assert utente["ultimo_accesso"] is None

    utenti.touch_ultimo_accesso(session, utente["id_utente"])

    db.execute(
        "SELECT ultimo_accesso FROM utenti WHERE id_utente = %s", (utente["id_utente"],)
    )
    assert db.fetchone()["ultimo_accesso"] is not None
