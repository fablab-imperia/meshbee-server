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
