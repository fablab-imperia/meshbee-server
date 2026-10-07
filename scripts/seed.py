#!/usr/bin/env python3
"""
Seed iniziale del database.

Crea gli account di default, un apiario di esempio se non esiste ancora
nessuna arnia, li associa alle arnie e inserisce un log attività di esempio. Gira a ogni `docker-compose up` (il servizio `seed`
esce con 0 e non riparte), quindi ogni passo è **idempotente**: se qualcosa
esiste già viene lasciato com'è, password comprese.

Come i due entry point, non contiene SQL: chiama i service di meshbee_core.
"""
import logging
import sys
from datetime import datetime, timedelta

from pydantic import Field, SecretStr, ValidationError

from meshbee_core.config import CoreSettings
from meshbee_core.db import close_db_pool, get_db_cursor, init_db_pool
from meshbee_core.schemas import ArniaCreate, AttivitaCreate, NodoCreate, UserCreate
from meshbee_core.services import accessi as accessi_service
from meshbee_core.services import arnie as arnie_service
from meshbee_core.services import attivita as attivita_service
from meshbee_core.services import letture as letture_service
from meshbee_core.services import nodi as nodi_service
from meshbee_core.services import utenti as utenti_service

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# A seed opens two connections in sequence and exits.
DB_POOL_SIZE = 2

ADMIN_EMAIL = "admin@beehive.local"
TEST_EMAIL = "utente@test.local"

# Days back the sample activity is dated, so the app has something in its history.
SAMPLE_ACTIVITY_AGE_DAYS = 7

# The demo apiary a fresh install starts with. It used to be inserted by
# database/init.sql; schema migrations carry no data, so the seed owns it now.
SAMPLE_NODO = NodoCreate(
    id_nodo="NODE001",
    nome_nodo="Apiario Collina",
    descrizione="Nodo principale apiario collina sud",
    posizione="Lat: 45.4642, Lon: 9.1900",
)
SAMPLE_ARNIE = [
    ArniaCreate(
        id_nodo="NODE001",
        id_sensore_fisico="SENSOR01",
        nome_arnia="Arnia Alpha",
        descrizione="Arnia con regina ligustica",
        posizione="Fila 1, Posizione 1",
        latitudine="45.464200",
        longitudine="9.190000",
        metadati={"razza": "Ligustica", "anno_regina": 2024, "colore_arnia": "giallo"},
    ),
    ArniaCreate(
        id_nodo="NODE001",
        id_sensore_fisico="SENSOR02",
        nome_arnia="Arnia Beta",
        descrizione="Arnia con regina carnica",
        posizione="Fila 1, Posizione 2",
        latitudine="45.464250",
        longitudine="9.190050",
        metadati={"razza": "Carnica", "anno_regina": 2023, "colore_arnia": "verde"},
    ),
]
# (hours ago, temperatura, umidita, peso) per sample arnia, in SAMPLE_ARNIE order.
SAMPLE_LETTURE = [
    [(1, "34.5", "65.0", "42.350"), (2, "33.8", "66.5", "42.320")],
    [(1, "35.2", "63.0", "38.720"), (2, "34.9", "64.0", "38.710")],
]


class SeedSettings(CoreSettings):
    """
    Settings for the seed script: the database, plus the two initial passwords.

    Both are required. They used to be read with `os.getenv(NAME, "")`, which
    meant an unset variable seeded `admin@beehive.local` with a valid bcrypt
    hash of the empty string — a working administrator account with no password,
    and no error to say so.
    """

    ADMIN_PASSWORD: SecretStr = Field(
        description="Password iniziale di admin@beehive.local (env: ADMIN_PASSWORD)"
    )
    USER_PASSWORD: SecretStr = Field(
        description="Password iniziale di utente@test.local (env: USER_PASSWORD)"
    )


def default_users(settings: SeedSettings):
    """
    The accounts every fresh install gets.

    Built as `UserCreate` so they go through the same validation as an account
    created through the admin API — in particular the 8-character minimum, which
    is the second thing stopping an empty password from being seeded.
    """
    return [
        UserCreate(
            email=ADMIN_EMAIL,
            password=settings.ADMIN_PASSWORD.get_secret_value(),
            nome="Admin",
            cognome="Sistema",
            ruolo="admin",
        ),
        UserCreate(
            email=TEST_EMAIL,
            password=settings.USER_PASSWORD.get_secret_value(),
            nome="Mario",
            cognome="Rossi",
            ruolo="user",
        ),
    ]


def create_users(users) -> dict:
    """Create the default accounts, skipping any that already exist."""
    logger.info("=== Creazione utenti ===")
    user_ids = {}

    for user in users:
        try:
            with get_db_cursor() as cursor:
                row, created = utenti_service.ensure_utente(cursor, user)
        except Exception as e:
            logger.error(f"  ✗ Errore per {user.email}: {e}")
            sys.exit(1)

        user_ids[user.email] = row["id_utente"]
        if created:
            logger.info(f"  ✓ Creato: {user.email} (id={row['id_utente']}, ruolo={user.ruolo})")
        else:
            logger.info(f"  Utente già esistente, skip: {user.email}")

    return user_ids


def add_sample_apiary() -> None:
    """
    Give an install with no hives at all one node, two arnie and a few readings.

    Keyed on "no arnie", not on the sample node: once anyone has registered a
    hive — sample or real — the seed stays out of the way, and deleting the
    demo data does not bring it back on the next start.
    """
    logger.info("\n=== Apiario di esempio ===")

    with get_db_cursor() as cursor:
        if arnie_service.list_ids(cursor):
            logger.info("  Arnie già presenti, skip")
            return

        nodi_service.create_nodo(cursor, SAMPLE_NODO)
        now = datetime.now()
        for arnia, readings in zip(SAMPLE_ARNIE, SAMPLE_LETTURE):
            created = arnie_service.create_arnia(cursor, arnia)
            for hours_ago, temperatura, umidita, peso in readings:
                letture_service.record_reading(cursor, {
                    "id_arnia": created["id_arnia"],
                    "id_nodo": arnia.id_nodo,
                    "timestamp": now - timedelta(hours=hours_ago),
                    "temperatura": temperatura,
                    "umidita": umidita,
                    "peso": peso,
                })

    logger.info(f"  ✓ Nodo {SAMPLE_NODO.id_nodo} con {len(SAMPLE_ARNIE)} arnie creato")


def associate_test_user(id_utente: int) -> list:
    """Give the test account access to every arnia already registered."""
    logger.info("\n=== Associazione utente-arnie ===")

    with get_db_cursor() as cursor:
        arnie = arnie_service.list_ids(cursor)

    if not arnie:
        logger.info("  Nessuna arnia trovata, skip")
        return arnie

    for id_arnia in arnie:
        with get_db_cursor() as cursor:
            accessi_service.grant_if_absent(cursor, id_utente, id_arnia, "admin")

    logger.info(f"  ✓ Utente {id_utente} associato a {len(arnie)} arnie")
    return arnie


def add_sample_activity(id_utente: int, id_arnia: int) -> None:
    """Give the first arnia one activity entry, so the app has something to show."""
    logger.info("\n=== Log attività di esempio ===")

    with get_db_cursor() as cursor:
        if attivita_service.count_for_arnia(cursor, id_arnia):
            logger.info("  Log già esistente, skip")
            return

        attivita_service.create_attivita(
            cursor,
            id_utente,
            id_arnia,
            AttivitaCreate(
                id_arnia=id_arnia,
                timestamp=datetime.now() - timedelta(days=SAMPLE_ACTIVITY_AGE_DAYS),
                tipo_attivita="ispezione",
                descrizione="Controllo regolare - tutto ok",
                dati={"telaini_miele": 8, "covata_presente": True},
            ),
        )
        logger.info("  ✓ Log attività di esempio inserito")


def seed() -> None:
    try:
        settings = SeedSettings()
        users = default_users(settings)
    except ValidationError as e:
        logger.error(f"Configurazione non valida: {e}")
        logger.error(
            "Imposta ADMIN_PASSWORD e USER_PASSWORD (almeno 8 caratteri) nel file .env"
        )
        sys.exit(1)

    init_db_pool(settings, maxconn=DB_POOL_SIZE)
    try:
        user_ids = create_users(users)

        # The remaining steps are conveniences, not prerequisites: a failure
        # there is reported but must not leave the stack without its accounts.
        try:
            add_sample_apiary()
            arnie = associate_test_user(user_ids[TEST_EMAIL])
            if arnie:
                add_sample_activity(user_ids[TEST_EMAIL], arnie[0])
        except Exception as e:
            logger.error(f"  ✗ Errore dati di esempio: {e}")

        logger.info("\n=== Seed completato ===")
        logger.info("Utenti creati: " + ", ".join(user.email for user in users))
    finally:
        close_db_pool()


if __name__ == "__main__":
    seed()
