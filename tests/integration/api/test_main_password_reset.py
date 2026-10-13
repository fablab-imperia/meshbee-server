"""POST /api/auth/password/forgot and /reset (#54), and the notice after a change.

The mailer is a fake that records each message; TestClient runs background
tasks before returning, so what a route queued is already in `outbox`.
"""

import re

import bcrypt
import pytest

from api.config import Settings, get_settings
from api.mail import get_mailer
from tests.conftest import REQUIRED_ENV

BASE_URL = "https://meshbee.example.org"
NEW_PASSWORD = "una-nuova-password"
FORGOT = "/api/auth/password/forgot"
RESET = "/api/auth/password/reset"


class FakeMailer:
    def __init__(self):
        self.outbox = []

    def send(self, to, subject, text, html=None):
        self.outbox.append({"to": to, "subject": subject, "text": text})


def email_settings(**overrides):
    values = {
        "SMTP_HOST": "mailpit",
        "MAIL_FROM": "noreply@meshbee.local",
        "PUBLIC_BASE_URL": BASE_URL,
        **overrides,
    }
    return Settings(_env_file=None, **REQUIRED_ENV, **values)


@pytest.fixture
def mailer(client):
    """Email on, through a fake: the client now sends to `mailer.outbox`."""
    from api import main

    fake = FakeMailer()
    main.app.dependency_overrides[get_settings] = lambda: email_settings()
    main.app.dependency_overrides[get_mailer] = lambda: fake
    return fake


@pytest.fixture
def utente(make_utente, password_hash):
    return make_utente(password_hash=password_hash, nome="Giulia")


def token_from(message):
    """The token in the link, read back as a person clicking it would."""
    match = re.search(
        rf"{re.escape(BASE_URL)}/reset-password#token=(\S+)", message["text"]
    )
    assert match, message["text"]
    return match.group(1)


def stored_hash(db, utente):
    db.execute(
        "SELECT password_hash FROM utenti WHERE id_utente = %s", (utente["id_utente"],)
    )
    return db.fetchone()["password_hash"]


def forgot(client, email):
    return client.post(FORGOT, json={"email": email})


# ============================================
# Forgot
# ============================================


def test_a_registered_address_is_sent_a_link(client, mailer, utente):
    response = forgot(client, utente["email"])

    assert response.status_code == 202
    (message,) = mailer.outbox
    assert message["to"] == utente["email"]
    assert "Giulia" in message["text"]
    assert "30 minuti" in message["text"]
    token_from(message)


@pytest.mark.parametrize(
    "case", ["registered", "unknown", "inactive", "malformed", "capped"]
)
def test_every_case_gets_the_same_answer(client, mailer, make_utente, utente, case):
    """Status and body never tell whether the address has an active account."""
    if case == "capped":
        for _ in range(3):
            forgot(client, utente["email"])
    email = {
        "registered": utente["email"],
        "unknown": "nobody@example.org",
        "inactive": make_utente(attivo=False)["email"],
        "malformed": "not-an-email",
        "capped": utente["email"],
    }[case]

    response = forgot(client, email)

    assert response.status_code == 202
    assert response.json() == {
        "message": "Se l'indirizzo corrisponde a un account attivo, riceverai "
        "un'email con il link per reimpostare la password",
        "detail": None,
    }


def test_an_unknown_address_is_sent_nothing(client, mailer):
    forgot(client, "nobody@example.org")

    assert mailer.outbox == []


def test_a_deactivated_account_is_sent_nothing(client, mailer, make_utente):
    forgot(client, make_utente(attivo=False)["email"])

    assert mailer.outbox == []


def test_the_address_is_matched_whatever_its_case(client, mailer, utente):
    forgot(client, f"  {utente['email'].upper()} ")

    assert len(mailer.outbox) == 1


def test_the_per_account_cap_stops_the_emails(client, mailer, utente):
    for _ in range(4):
        assert forgot(client, utente["email"]).status_code == 202

    assert len(mailer.outbox) == 3


def test_the_per_ip_limit_answers_429(client, mailer):
    """Random addresses from one client run into the limit, whatever they are."""
    for i in range(10):
        assert forgot(client, f"nobody{i}@example.org").status_code == 202

    response = forgot(client, "one-more@example.org")

    assert response.status_code == 429
    assert int(response.headers["Retry-After"]) > 0


@pytest.mark.parametrize(
    "overrides",
    [{"SMTP_HOST": None, "MAIL_FROM": None}, {"PUBLIC_BASE_URL": None}],
    ids=["no email", "no public url"],
)
def test_without_email_or_a_public_url_forgot_is_503(client, utente, overrides):
    """Not configured says so, the same for every address: nothing is revealed."""
    from api import main

    main.app.dependency_overrides[get_settings] = lambda: email_settings(**overrides)

    response = forgot(client, utente["email"])

    assert response.status_code == 503
    assert "amministratore" in response.json()["detail"]


def test_a_failed_send_still_answers_202(client, mailer, utente, caplog):
    """The email goes out after the response: an SMTP failure cannot change it."""
    from meshbee_core.errors import Unavailable

    def broken(*args, **kwargs):
        raise Unavailable("Servizio email non disponibile")

    mailer.send = broken

    assert forgot(client, utente["email"]).status_code == 202


def test_the_token_is_not_logged(client, mailer, utente, caplog):
    with caplog.at_level("DEBUG"):
        forgot(client, utente["email"])

    assert token_from(mailer.outbox[0]) not in caplog.text


# ============================================
# Reset
# ============================================


def reset(client, token, new_password=NEW_PASSWORD):
    return client.post(RESET, json={"token": token, "new_password": new_password})


def test_the_emailed_link_sets_a_new_password(client, mailer, utente, db):
    forgot(client, utente["email"])

    response = reset(client, token_from(mailer.outbox[0]))

    assert response.status_code == 200
    assert bcrypt.checkpw(NEW_PASSWORD.encode(), stored_hash(db, utente).encode())


def test_the_new_password_logs_in(client, mailer, utente):
    forgot(client, utente["email"])
    reset(client, token_from(mailer.outbox[0]))

    response = client.post(
        "/api/auth/login", json={"email": utente["email"], "password": NEW_PASSWORD}
    )

    assert response.status_code == 200


def test_a_reset_sends_a_notice(client, mailer, utente):
    forgot(client, utente["email"])
    reset(client, token_from(mailer.outbox[0]))

    notice = mailer.outbox[1]
    assert notice["to"] == utente["email"]
    assert "cambiata" in notice["subject"]


@pytest.mark.parametrize("case", ["used", "replaced", "unknown"])
def test_a_bad_token_is_one_400(client, mailer, utente, db, case):
    forgot(client, utente["email"])
    token = token_from(mailer.outbox[0])
    if case == "used":
        reset(client, token)
    elif case == "replaced":
        forgot(client, utente["email"])
    elif case == "unknown":
        token = "never-issued"
    before = stored_hash(db, utente)

    response = reset(client, token, "ancora-un-altra")

    assert response.status_code == 400
    assert (
        response.json()["detail"] == "Link non valido o scaduto: richiedine uno nuovo"
    )
    assert stored_hash(db, utente) == before


def test_an_expired_token_is_400(client, mailer, utente, db):
    forgot(client, utente["email"])
    db.execute(
        "UPDATE token_monouso SET data_scadenza = data_creazione - interval '1 minute' "
        "WHERE id_utente = %s",
        (utente["id_utente"],),
    )

    response = reset(client, token_from(mailer.outbox[0]))

    assert response.status_code == 400


def test_the_new_password_follows_the_usual_rules(client, mailer, utente):
    forgot(client, utente["email"])

    response = reset(client, token_from(mailer.outbox[0]), "short")

    assert response.status_code == 422


def test_reset_works_without_email_and_sends_no_notice(client, mailer, utente):
    """A token issued earlier stays good if email is switched off before it is used."""
    from api import main

    forgot(client, utente["email"])
    token = token_from(mailer.outbox[0])
    main.app.dependency_overrides[get_mailer] = lambda: None

    assert reset(client, token).status_code == 200
    assert len(mailer.outbox) == 1


# ============================================
# Changing one's own password
# ============================================


def test_changing_the_password_sends_a_notice(as_user, mailer, utente, known_password):
    response = as_user(utente).put(
        "/api/user/password",
        json={"current_password": known_password, "new_password": NEW_PASSWORD},
    )

    assert response.status_code == 200
    (notice,) = mailer.outbox
    assert notice["to"] == utente["email"]
    assert "cambiata" in notice["subject"]


def test_a_refused_change_sends_nothing(as_user, mailer, utente):
    as_user(utente).put(
        "/api/user/password",
        json={"current_password": "wrong-password", "new_password": NEW_PASSWORD},
    )

    assert mailer.outbox == []
