"""Tests for the bootstrap script (scripts/seed.py).

The seed runs on every `docker-compose up`, so idempotency is its whole
contract: re-running it must not fail, must not reset a password an operator has
changed, and must not undo an access revocation. None of that was covered before.
"""

import pytest
from pydantic import ValidationError

from meshbee_core.repository import accessi, utenti
from meshbee_core.security import verify_password
from scripts import seed as seed_script

PASSWORD = "correct-horse-battery-staple"


@pytest.fixture
def settings(build_core_settings):
    """SeedSettings with both passwords supplied."""
    return seed_script.SeedSettings(
        _env_file=None,
        DB_PASSWORD="unused-here",
        ADMIN_PASSWORD=PASSWORD,
        USER_PASSWORD=PASSWORD,
    )


@pytest.fixture
def run_seed(use_db, settings):
    """Point the script at the rolled-back test transaction and run its steps."""
    use_db(seed_script)
    return settings


# ============================================
# Configuration
# ============================================


@pytest.mark.parametrize("missing", ["ADMIN_PASSWORD", "USER_PASSWORD"])
def test_a_missing_initial_password_fails_loudly(monkeypatch, required_env, missing):
    """
    Both are required, with no default.

    They used to be read with `os.getenv(NAME, "")`, so an unset variable seeded
    admin@beehive.local with a bcrypt hash of the empty string: a working
    administrator account with no password, created silently.
    """
    monkeypatch.setenv("ADMIN_PASSWORD", PASSWORD)
    monkeypatch.setenv("USER_PASSWORD", PASSWORD)
    monkeypatch.delenv(missing)

    with pytest.raises(ValidationError) as exc_info:
        seed_script.SeedSettings(_env_file=None)

    assert (missing,) in [error["loc"] for error in exc_info.value.errors()]


def test_an_empty_initial_password_is_refused(build_core_settings):
    """
    Being required is not enough: an exported-but-empty variable is still a str.

    Building the accounts as `UserCreate` is what catches it, applying the same
    8-character minimum as the admin API.
    """
    settings = seed_script.SeedSettings(
        _env_file=None, DB_PASSWORD="x", ADMIN_PASSWORD="", USER_PASSWORD=PASSWORD
    )

    with pytest.raises(ValidationError):
        seed_script.default_users(settings)


def test_a_short_initial_password_is_refused(build_core_settings):
    """The seed cannot create an account the admin API would have rejected."""
    settings = seed_script.SeedSettings(
        _env_file=None, DB_PASSWORD="x", ADMIN_PASSWORD="short", USER_PASSWORD=PASSWORD
    )

    with pytest.raises(ValidationError):
        seed_script.default_users(settings)


def test_the_seed_settings_carry_no_jwt_key():
    """
    The seed extends CoreSettings, not the API's Settings.

    That is what lets docker-compose stop handing this container a signing key
    it has no use for.
    """
    assert "JWT_SECRET_KEY" not in seed_script.SeedSettings.model_fields


# ============================================
# Creating the accounts
# ============================================


def test_the_default_accounts_are_created(session, db, run_seed):
    """A fresh database gets one admin and one ordinary user."""
    seed_script.create_users(seed_script.default_users(run_seed))

    admin = utenti.get_by_email(session, seed_script.ADMIN_EMAIL)
    utente = utenti.get_by_email(session, seed_script.TEST_EMAIL)

    assert admin["ruolo"] == "admin"
    assert utente["ruolo"] == "user"
    assert admin["attivo"] is True
    assert admin["data_attivazione"] is not None


def test_the_seeded_password_actually_works(session, db, run_seed):
    """A real bcrypt hash, not a placeholder: the account is usable at once."""
    seed_script.create_users(seed_script.default_users(run_seed))

    stored = utenti.get_credentials_by_email(session, seed_script.ADMIN_EMAIL)

    assert verify_password(PASSWORD, stored["password_hash"])


def test_running_twice_creates_nothing_new(db, run_seed):
    """The service starts on every `up`, so a second run must be a no-op."""
    users = seed_script.default_users(run_seed)
    first = seed_script.create_users(users)

    second = seed_script.create_users(users)

    assert first == second
    db.execute("SELECT COUNT(*) AS n FROM utenti")
    assert db.fetchone()["n"] == 2


def test_rerunning_does_not_reset_a_changed_password(session, db, run_seed):
    """
    An operator who changed the admin password keeps it across restarts.

    Re-hashing the configured password on every boot would silently undo that.
    """
    users = seed_script.default_users(run_seed)
    seed_script.create_users(users)
    ids = {
        u.email: utenti.find_id_by_email(session, u.email)["id_utente"] for u in users
    }
    utenti.set_password_hash(
        session, ids[seed_script.ADMIN_EMAIL], "hash-scelto-dall-operatore"
    )

    seed_script.create_users(users)

    stored = utenti.get_credentials_by_email(session, seed_script.ADMIN_EMAIL)
    assert stored["password_hash"] == "hash-scelto-dall-operatore"


# ============================================
# Associations and sample data
# ============================================


def test_an_empty_install_gets_the_sample_apiary(db, run_seed):
    """What init.sql used to insert: one node, two arnie, two readings each."""
    seed_script.add_sample_apiary()

    db.execute("SELECT id_nodo FROM nodi")
    assert [row["id_nodo"] for row in db.fetchall()] == ["NODE001"]
    db.execute("SELECT nome_arnia FROM arnie ORDER BY id_arnia")
    assert [row["nome_arnia"] for row in db.fetchall()] == ["Arnia Alpha", "Arnia Beta"]
    db.execute("SELECT count(*) AS n FROM letture")
    assert db.fetchone()["n"] == 4


def test_the_sample_apiary_is_not_added_twice(db, run_seed):
    seed_script.add_sample_apiary()
    seed_script.add_sample_apiary()

    db.execute("SELECT count(*) AS n FROM arnie")
    assert db.fetchone()["n"] == 2


def test_an_install_with_its_own_hives_gets_no_sample_apiary(db, run_seed, make_arnia):
    make_arnia()

    seed_script.add_sample_apiary()

    db.execute("SELECT count(*) AS n FROM nodi WHERE id_nodo = 'NODE001'")
    assert db.fetchone()["n"] == 0


def test_the_test_account_is_associated_with_every_arnia(
    session, db, run_seed, make_arnia
):
    """Whatever hives already exist, the demo account can see them."""
    make_arnia()
    make_arnia()
    ids = seed_script.create_users(seed_script.default_users(run_seed))

    arnie = seed_script.associate_test_user(ids[seed_script.TEST_EMAIL])

    assert len(arnie) == 2
    for id_arnia in arnie:
        granted = accessi.get_permesso(session, ids[seed_script.TEST_EMAIL], id_arnia)
        assert granted["permessi"] == "admin"


def test_no_arnie_is_not_an_error(db, run_seed):
    """A brand-new install has no hives yet; the seed still completes."""
    ids = seed_script.create_users(seed_script.default_users(run_seed))

    assert seed_script.associate_test_user(ids[seed_script.TEST_EMAIL]) == []


def test_rerunning_does_not_revive_a_revoked_association(
    session, db, run_seed, make_arnia
):
    """
    The reason this uses insert-if-absent rather than the reviving upsert.

    `accessi.upsert` sets `attivo = true` and clears the revocation date, so
    seeding with it would hand the demo account its access back on every
    `docker-compose up` — a silent authorization change.
    """
    arnia = make_arnia()
    ids = seed_script.create_users(seed_script.default_users(run_seed))
    id_utente = ids[seed_script.TEST_EMAIL]
    seed_script.associate_test_user(id_utente)
    accessi.deactivate(session, id_utente, arnia["id_arnia"])

    seed_script.associate_test_user(id_utente)

    assert accessi.get_permesso(session, id_utente, arnia["id_arnia"]) is None


def test_a_sample_activity_is_added_to_the_first_arnia(db, run_seed, make_arnia):
    """So the mobile app has something in its history on first launch."""
    arnia = make_arnia()
    ids = seed_script.create_users(seed_script.default_users(run_seed))

    seed_script.add_sample_activity(ids[seed_script.TEST_EMAIL], arnia["id_arnia"])

    db.execute("SELECT * FROM log_attivita WHERE id_arnia = %s", (arnia["id_arnia"],))
    logged = db.fetchone()
    assert logged["tipo_attivita"] == "ispezione"
    assert logged["dati"] == {"telaini_miele": 8, "covata_presente": True}


def test_the_sample_activity_is_backdated(db, run_seed, make_arnia):
    """Dated a week back so the history is not a single point at install time."""
    from datetime import datetime, timedelta

    arnia = make_arnia()
    ids = seed_script.create_users(seed_script.default_users(run_seed))

    seed_script.add_sample_activity(ids[seed_script.TEST_EMAIL], arnia["id_arnia"])

    db.execute(
        "SELECT timestamp FROM log_attivita WHERE id_arnia = %s", (arnia["id_arnia"],)
    )
    age = datetime.now() - db.fetchone()["timestamp"]
    assert timedelta(days=6) < age < timedelta(days=8)


def test_the_sample_activity_is_not_duplicated(db, run_seed, make_arnia):
    """Re-running must not pile up example rows in a live database."""
    arnia = make_arnia()
    ids = seed_script.create_users(seed_script.default_users(run_seed))
    seed_script.add_sample_activity(ids[seed_script.TEST_EMAIL], arnia["id_arnia"])

    seed_script.add_sample_activity(ids[seed_script.TEST_EMAIL], arnia["id_arnia"])

    db.execute(
        "SELECT COUNT(*) AS n FROM log_attivita WHERE id_arnia = %s",
        (arnia["id_arnia"],),
    )
    assert db.fetchone()["n"] == 1


def test_an_arnia_with_its_own_history_is_left_alone(
    db, run_seed, make_arnia, make_utente, make_attivita
):
    """
    Real entries suppress the example, rather than the example joining them.

    The count is what decides, so a hive an operator has already inspected never
    gets a fabricated "Controllo regolare" appended to its log.
    """
    arnia, utente = make_arnia(), make_utente()
    make_attivita(arnia, utente, descrizione="Ispezione vera")
    ids = seed_script.create_users(seed_script.default_users(run_seed))

    seed_script.add_sample_activity(ids[seed_script.TEST_EMAIL], arnia["id_arnia"])

    db.execute(
        "SELECT descrizione FROM log_attivita WHERE id_arnia = %s", (arnia["id_arnia"],)
    )
    assert [row["descrizione"] for row in db.fetchall()] == ["Ispezione vera"]
