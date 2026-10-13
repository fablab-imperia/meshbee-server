"""The text of the emails the server sends, as (subject, body) pairs.

Plain strings in Italian, like the rest of what users read; no templates and no
HTML. Kept apart from `mail.py`, which only knows how to deliver a message, so
the wording can change without touching the transport.
"""

from dataclasses import dataclass

SIGNATURE = "\n-- \nMeshbee"

# How much of a name chosen by a user (a person's, an apiary's) an email repeats.
INLINE_MAX = 60


def inline(value: str, limit: int = INLINE_MAX) -> str:
    """
    User-chosen text as it may appear in an email: one line, at most `limit` characters.

    Emails go to addresses the user picked, from the server's own domain. Names
    are kept short and on one line, so a name can't carry a message of its own,
    or break the Subject header with a newline.
    """
    flat = " ".join(value.split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


@dataclass(frozen=True)
class Email:
    subject: str
    text: str


def password_reset(nome: str, link: str, minutes: int) -> Email:
    """The reset link. It names its own expiry, and says what to do if unexpected."""
    return Email(
        subject="Meshbee: reimposta la password",
        text=(
            f"Ciao {inline(nome)},\n\n"
            "abbiamo ricevuto una richiesta di reimpostare la password del tuo "
            "account Meshbee. Per sceglierne una nuova apri questo link:\n\n"
            f"{link}\n\n"
            f"Il link vale per {minutes} minuti e si può usare una volta sola.\n\n"
            "Se non sei stato tu a chiederlo, ignora questa email: la tua "
            "password resta quella di prima.\n" + SIGNATURE
        ),
    )


def password_changed(nome: str) -> Email:
    """A notice after any change the user made, so an unexpected one gets noticed."""
    return Email(
        subject="Meshbee: la tua password è stata cambiata",
        text=(
            f"Ciao {inline(nome)},\n\n"
            "la password del tuo account Meshbee è appena stata cambiata, e i "
            "dispositivi collegati dovranno accedere di nuovo.\n\n"
            "Se non sei stato tu, reimposta subito la password dalla pagina di "
            "accesso o contatta un amministratore.\n" + SIGNATURE
        ),
    )


# What each role on an apiary means, in the words an email uses.
RUOLI = {
    "viewer": "visualizzatore (puoi vedere le arnie e le loro letture)",
    "collaborator": "collaboratore (puoi anche registrare le attività)",
    "manager": "gestore (puoi anche modificare l'apiario e le sue arnie)",
}


def apiary_shared(
    mittente: str, nome_apiario: str, ruolo: str, app_url: str | None
) -> Email:
    """A notice to someone with an account: an apiary was shared with them (#55)."""
    where = (
        f"Lo trovi nell'app Meshbee: {app_url}\n"
        if app_url
        else ("Lo trovi nell'app Meshbee.\n")
    )
    mittente, nome_apiario = inline(mittente), inline(nome_apiario)
    return Email(
        subject=f"Meshbee: {mittente} ha condiviso l'apiario {nome_apiario}",
        text=(
            "Ciao,\n\n"
            f"{mittente} ha condiviso con te l'apiario «{nome_apiario}» come "
            f"{RUOLI[ruolo]}.\n\n" + where + SIGNATURE
        ),
    )


def invitation(
    mittente: str, nome_apiario: str, ruolo: str, link: str, days: int
) -> Email:
    """An invitation to someone with no account: the link creates one (#55)."""
    mittente, nome_apiario = inline(mittente), inline(nome_apiario)
    return Email(
        subject=f"Meshbee: {mittente} ti invita nell'apiario {nome_apiario}",
        text=(
            "Ciao,\n\n"
            f"{mittente} ti ha invitato a seguire l'apiario «{nome_apiario}» su "
            f"Meshbee come {RUOLI[ruolo]}.\n\n"
            "Per accettare, crea il tuo account da questo link:\n\n"
            f"{link}\n\n"
            f"Il link vale per {days} giorni e si può usare una volta sola. "
            "L'account userà questo indirizzo email.\n\n"
            "Se non conosci chi ti ha invitato, ignora questa email: senza un "
            "account non succede nulla.\n" + SIGNATURE
        ),
    )
