"""The text of the emails the server sends, as (subject, body) pairs.

Plain strings in Italian, like the rest of what users read; no templates and no
HTML. Kept apart from `mail.py`, which only knows how to deliver a message, so
the wording can change without touching the transport.
"""

from dataclasses import dataclass

SIGNATURE = "\n-- \nMeshbee"


@dataclass(frozen=True)
class Email:
    subject: str
    text: str


def password_reset(nome: str, link: str, minutes: int) -> Email:
    """The reset link. It names its own expiry, and says what to do if unexpected."""
    return Email(
        subject="Meshbee: reimposta la password",
        text=(
            f"Ciao {nome},\n\n"
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
            f"Ciao {nome},\n\n"
            "la password del tuo account Meshbee è appena stata cambiata, e i "
            "dispositivi collegati dovranno accedere di nuovo.\n\n"
            "Se non sei stato tu, reimposta subito la password dalla pagina di "
            "accesso o contatta un amministratore.\n" + SIGNATURE
        ),
    )
