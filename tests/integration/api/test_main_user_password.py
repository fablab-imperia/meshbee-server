"""PUT /api/user/password — a user changing their own password."""
import bcrypt
import pytest

NEW_PASSWORD = "una-nuova-password"


@pytest.fixture
def utente(make_utente, password_hash):
    """An active user whose stored hash matches `known_password`."""
    return make_utente(password_hash=password_hash)


def stored_hash(db, utente):
    db.execute("SELECT password_hash FROM utenti WHERE id_utente = %s", (utente["id_utente"],))
    return db.fetchone()["password_hash"]


def test_changing_the_password_succeeds(as_user, utente, known_password):
    """The current password is verified, then the new one is stored."""
    response = as_user(utente).put(
        "/api/user/password",
        json={"current_password": known_password, "new_password": NEW_PASSWORD},
    )

    assert response.status_code == 200


def test_the_new_password_is_stored_as_a_usable_bcrypt_hash(
    as_user, utente, known_password, db
):
    """What lands in the column verifies against the new plaintext, and is not it."""
    as_user(utente).put(
        "/api/user/password",
        json={"current_password": known_password, "new_password": NEW_PASSWORD},
    )

    hashed = stored_hash(db, utente)
    assert hashed != NEW_PASSWORD
    assert bcrypt.checkpw(NEW_PASSWORD.encode(), hashed.encode())


def test_the_old_password_stops_working(as_user, utente, known_password, db):
    """The previous hash is replaced, not kept alongside."""
    as_user(utente).put(
        "/api/user/password",
        json={"current_password": known_password, "new_password": NEW_PASSWORD},
    )

    assert not bcrypt.checkpw(known_password.encode(), stored_hash(db, utente).encode())


def test_a_wrong_current_password_is_refused(as_user, utente, db):
    """Knowing the session is not enough: the current password must be proven."""
    before = stored_hash(db, utente)

    response = as_user(utente).put(
        "/api/user/password",
        json={"current_password": "not-my-password", "new_password": NEW_PASSWORD},
    )

    assert response.status_code == 400
    assert stored_hash(db, utente) == before


def test_omitting_the_current_password_is_refused(as_user, utente, db):
    """current_password is optional in the model but required by this endpoint."""
    before = stored_hash(db, utente)

    response = as_user(utente).put("/api/user/password", json={"new_password": NEW_PASSWORD})

    assert response.status_code == 400
    assert stored_hash(db, utente) == before


@pytest.mark.parametrize("new_password", ["", "1234567"])
def test_a_too_short_new_password_is_refused(as_user, utente, known_password, new_password):
    """The 8-character minimum from PasswordChange is enforced at the edge."""
    response = as_user(utente).put(
        "/api/user/password",
        json={"current_password": known_password, "new_password": new_password},
    )

    assert response.status_code == 422


def test_a_password_bcrypt_would_truncate_is_refused(as_user, utente, known_password, db):
    """
    Over 72 bytes is refused instead of being silently cut down.

    Previously the tail was dropped and the user could then authenticate with
    just the prefix, believing they had a much longer password.
    """
    before = stored_hash(db, utente)

    response = as_user(utente).put(
        "/api/user/password",
        json={"current_password": known_password, "new_password": "x" * 73},
    )

    assert response.status_code == 422
    assert stored_hash(db, utente) == before


def test_changing_a_password_does_not_touch_other_accounts(
    as_user, utente, known_password, make_utente, password_hash, db
):
    """The UPDATE is keyed on the authenticated id_utente only."""
    altro = make_utente(password_hash=password_hash)

    as_user(utente).put(
        "/api/user/password",
        json={"current_password": known_password, "new_password": NEW_PASSWORD},
    )

    assert bcrypt.checkpw(known_password.encode(), stored_hash(db, altro).encode())
