"""The email texts (meshbee_core/emails.py)."""

from meshbee_core import emails

LINK = "https://meshbee.example.org/reset-password#token=abc"


def test_the_reset_email_carries_the_link_and_its_expiry():
    email = emails.password_reset("Giulia", LINK, 30)

    assert "Giulia" in email.text
    assert LINK in email.text
    assert "30 minuti" in email.text
    assert "password" in email.subject


def test_the_link_stands_on_its_own_line():
    """Mail clients make a bare line a clickable link; surrounding words can break it."""
    assert f"\n{LINK}\n" in emails.password_reset("Giulia", LINK, 30).text


def test_the_change_notice_names_the_user():
    email = emails.password_changed("Giulia")

    assert "Giulia" in email.text
    assert "cambiata" in email.subject


INVITE_LINK = "https://meshbee.example.org/invite#token=abc"


def test_the_invitation_names_the_sender_the_apiary_and_the_role():
    email = emails.invitation("Giulia Rossi", "Collina", "collaborator", INVITE_LINK, 7)

    assert "Giulia Rossi" in email.subject
    assert "Collina" in email.text
    assert emails.RUOLI["collaborator"] in email.text
    assert f"\n{INVITE_LINK}\n" in email.text
    assert "7 giorni" in email.text


def test_the_share_notice_links_to_the_app_when_it_can():
    with_url = emails.apiary_shared(
        "Giulia Rossi", "Collina", "viewer", "https://x.org"
    )
    without = emails.apiary_shared("Giulia Rossi", "Collina", "viewer", None)

    assert "https://x.org" in with_url.text
    assert "Lo trovi nell'app Meshbee." in without.text


def test_every_apiary_role_has_words_for_an_email():
    from meshbee_core.limits import RUOLI_APIARIO

    assert set(emails.RUOLI) == set(RUOLI_APIARIO)
