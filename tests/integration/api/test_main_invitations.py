"""Apiary invitations and share notices by email (#55), through the routes.

POST …/condivisioni sends a notice to an existing account and an invitation to
an unknown email; POST …/inviti/{id}/reinvia sends it again; POST
/api/auth/invite/accept creates the account. The mailer is the fake in conftest.py.
"""

import re

import pytest

from api.auth import get_current_active_user
from tests.integration.api.conftest import BASE_URL

EMAIL = "new@example.org"
ACCEPT = "/api/auth/invite/accept"


@pytest.fixture
def owner(make_utente):
    return make_utente(nome="Giulia", cognome="Rossi")


@pytest.fixture
def apiario(make_apiario, owner):
    return make_apiario(owner, nome_apiario="Collina")


def share(client, apiario, email=EMAIL, ruolo="viewer"):
    return client.post(
        f"/api/user/apiari/{apiario['id_apiario']}/condivisioni",
        json={"email": email, "ruolo": ruolo},
    )


def shares_of(client, apiario):
    return client.get(f"/api/user/apiari/{apiario['id_apiario']}/condivisioni").json()


def token_from(message):
    match = re.search(rf"{re.escape(BASE_URL)}/invite#token=(\S+)", message["text"])
    assert match, message["text"]
    return match.group(1)


def resend(client, apiario):
    (invito,) = [s for s in shares_of(client, apiario) if s["stato"] == "in_attesa"]
    return client.post(
        f"/api/user/apiari/{apiario['id_apiario']}/inviti/{invito['id_invito']}/reinvia"
    )


def accept(client, token, password="secret123"):
    return client.post(
        ACCEPT,
        json={
            "token": token,
            "nome": "Nuovo",
            "cognome": "Utente",
            "password": password,
        },
    )


# ============================================
# Sharing sends email
# ============================================


def test_an_unknown_email_is_sent_an_invitation(as_user, mailer, owner, apiario):
    response = share(as_user(owner), apiario, ruolo="collaborator")

    assert response.status_code == 200
    (message,) = mailer.outbox
    assert message["to"] == EMAIL
    assert "Giulia Rossi" in message["subject"]
    assert "Collina" in message["text"]
    assert "collaboratore" in message["text"]
    assert "7 giorni" in message["text"]
    token_from(message)


def test_the_token_never_reaches_the_sharer(as_user, mailer, owner, apiario):
    """Only the invited mailbox holds it: the share answer stays #40's three fields."""
    response = share(as_user(owner), apiario)

    assert response.json() == {
        "id_apiario": apiario["id_apiario"],
        "email": EMAIL,
        "ruolo": "viewer",
    }
    assert token_from(mailer.outbox[0]) not in response.text


def test_an_existing_account_is_sent_a_notice(
    as_user, mailer, owner, apiario, make_utente
):
    guest = make_utente()

    share(as_user(owner), apiario, email=guest["email"], ruolo="manager")

    (message,) = mailer.outbox
    assert message["to"] == guest["email"]
    assert "Giulia Rossi" in message["subject"]
    assert "Collina" in message["text"]
    assert "gestore" in message["text"]
    assert BASE_URL in message["text"]
    assert "#token=" not in message["text"]


def test_both_answers_stay_the_same_with_email_on(
    as_user, mailer, owner, apiario, make_utente
):
    """The emails differ; what the sharer sees does not (#40)."""
    guest = make_utente()
    client = as_user(owner)

    known = share(client, apiario, email=guest["email"])
    unknown = share(client, apiario)

    assert known.status_code == unknown.status_code == 200
    assert {**known.json(), "email": None} == {**unknown.json(), "email": None}


def test_without_email_sharing_works_and_sends_nothing(as_user, client, owner, apiario):
    response = share(as_user(owner), apiario)

    assert response.status_code == 200
    assert shares_of(client, apiario)[0]["stato"] == "in_attesa"


def test_without_a_public_url_only_the_notice_goes_out(
    as_user, mailer, set_email_settings, owner, apiario, make_utente
):
    """An invitation is a link to this server; a notice can do without one."""
    set_email_settings(PUBLIC_BASE_URL=None)
    guest = make_utente()
    client = as_user(owner)

    share(client, apiario)
    share(client, apiario, email=guest["email"])

    (notice,) = mailer.outbox
    assert notice["to"] == guest["email"]
    assert "Lo trovi nell'app Meshbee." in notice["text"]


def test_past_the_daily_cap_invitations_are_stored_but_not_sent(
    as_user, mailer, set_email_settings, owner, apiario
):
    set_email_settings(INVITE_MAX_PER_DAY=2)
    client = as_user(owner)

    responses = [share(client, apiario, email=f"n{i}@example.org") for i in range(3)]

    assert [r.status_code for r in responses] == [200, 200, 200]
    assert len(mailer.outbox) == 2
    assert len(shares_of(client, apiario)) == 3


# ============================================
# Accepting
# ============================================


def test_the_invited_person_creates_an_account_and_is_logged_in(
    as_user, client, mailer, owner, apiario, make_arnia
):
    arnia = make_arnia(apiario=apiario)
    share(as_user(owner), apiario, ruolo="collaborator")
    # From here on, a real bearer token: the one the accept route returned.
    client.app.dependency_overrides.pop(get_current_active_user)

    response = accept(client, token_from(mailer.outbox[0]))

    assert response.status_code == 200
    tokens = response.json()
    assert {"access_token", "refresh_token"} <= tokens.keys()
    hives = client.get(
        "/api/user/arnie", headers={"Authorization": f"Bearer {tokens['access_token']}"}
    ).json()
    assert [(a["id_arnia"], a["accesso"]) for a in hives] == [
        (arnia["id_arnia"], "collaborator")
    ]


def test_the_new_account_can_log_in_with_its_password(
    client, as_user, mailer, owner, apiario
):
    share(as_user(owner), apiario)
    accept(client, token_from(mailer.outbox[0]), password="la-mia-password")

    response = client.post(
        "/api/auth/login", json={"email": EMAIL, "password": "la-mia-password"}
    )

    assert response.status_code == 200


def test_the_share_list_shows_the_invitation_as_active_once_accepted(
    client, as_user, mailer, owner, apiario
):
    share(as_user(owner), apiario)
    accept(client, token_from(mailer.outbox[0]))

    (entry,) = shares_of(as_user(owner), apiario)

    assert (entry["email"], entry["stato"]) == (EMAIL, "attiva")


@pytest.mark.parametrize("case", ["used", "withdrawn", "unknown"])
def test_a_bad_link_is_one_400(client, as_user, mailer, owner, apiario, case):
    owner_client = as_user(owner)
    share(owner_client, apiario)
    token = token_from(mailer.outbox[0])
    if case == "used":
        accept(client, token)
    elif case == "withdrawn":
        (invito,) = shares_of(owner_client, apiario)
        owner_client.delete(
            f"/api/user/apiari/{apiario['id_apiario']}/inviti/{invito['id_invito']}"
        )
    else:
        token = "never-issued"

    response = accept(client, token)

    assert response.status_code == 400
    assert "Invito non valido o scaduto" in response.json()["detail"]


def test_the_password_follows_the_usual_rules(client, as_user, mailer, owner, apiario):
    share(as_user(owner), apiario)

    response = accept(client, token_from(mailer.outbox[0]), password="short")

    assert response.status_code == 422


# ============================================
# Resending
# ============================================


def test_resending_sends_a_new_link_and_voids_the_old(
    client, as_user, mailer, owner, apiario
):
    owner_client = as_user(owner)
    share(owner_client, apiario)
    old = token_from(mailer.outbox[0])

    response = resend(owner_client, apiario)

    assert response.status_code == 202
    assert EMAIL in response.json()["message"]
    new = token_from(mailer.outbox[1])
    assert accept(client, old).status_code == 400
    assert accept(client, new).status_code == 200


def test_resending_past_the_daily_cap_is_429(
    as_user, mailer, set_email_settings, owner, apiario
):
    set_email_settings(INVITE_MAX_PER_DAY=1)
    client = as_user(owner)
    share(client, apiario)

    response = resend(client, apiario)

    assert response.status_code == 429
    assert len(mailer.outbox) == 1


def test_resending_without_email_is_503(as_user, owner, apiario):
    client = as_user(owner)
    share(client, apiario)

    assert resend(client, apiario).status_code == 503


def test_resending_an_unknown_invitation_is_404(as_user, mailer, owner, apiario):
    response = as_user(owner).post(
        f"/api/user/apiari/{apiario['id_apiario']}/inviti/999999/reinvia"
    )

    assert response.status_code == 404


def test_the_token_is_not_logged(as_user, mailer, owner, apiario, caplog):
    with caplog.at_level("DEBUG"):
        share(as_user(owner), apiario)

    assert token_from(mailer.outbox[0]) not in caplog.text


# ============================================
# Keeping notices within the provider's quota
# ============================================


def test_a_role_change_sends_no_new_notice(
    as_user, mailer, owner, apiario, make_utente
):
    guest = make_utente()
    client = as_user(owner)
    share(client, apiario, email=guest["email"], ruolo="viewer")

    share(client, apiario, email=guest["email"], ruolo="manager")

    assert len(mailer.outbox) == 1


def test_notices_stop_at_the_daily_cap_but_shares_do_not(
    as_user, mailer, owner, apiario, make_utente, monkeypatch
):
    """One user cannot spend the provider's daily quota, and everyone's resets with it."""
    from api import main
    from api.ratelimit import SlidingWindowLimiter

    monkeypatch.setattr(
        main, "notice_limiter", SlidingWindowLimiter(limit=2, window=86400)
    )
    guests = [make_utente() for _ in range(3)]
    client = as_user(owner)

    responses = [share(client, apiario, email=g["email"]) for g in guests]

    assert [r.status_code for r in responses] == [200, 200, 200]
    assert len(mailer.outbox) == 2
    assert {s["stato"] for s in shares_of(client, apiario)} == {"attiva"}


@pytest.mark.parametrize(
    "email", ["a@example.org, b@example.org", "Name <a@example.org>", "not-an-email"]
)
def test_sharing_takes_exactly_one_address(as_user, mailer, owner, apiario, email):
    """A list would be one invitation to many people, past the daily caps."""
    client = as_user(owner)

    response = share(client, apiario, email=email)

    assert response.status_code == 422
    assert mailer.outbox == []
    assert shares_of(client, apiario) == []
