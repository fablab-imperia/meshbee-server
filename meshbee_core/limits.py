"""
The domain's bounds and value sets, declared once.

Every other place a range or an allowed value appears reads it from here:
the table models (`models.py`) turn them into CHECK constraints, the API
schemas (`schemas.py`) into validators, and the MQTT contract
(`mqtt_handler/contract.py`) into JSON Schema keywords. Changing a number here
changes all three; the database follows through a migration (see
`database/README.md`).

Migrations are the one exception: a revision freezes the literal values it was
written with, because replaying history must not change when a constant does.
"""
from typing import Literal, get_args

# Measurements, as stored in `letture` and sent by the nodes.
TEMPERATURA_MIN, TEMPERATURA_MAX = -50, 100   # °C
UMIDITA_MIN, UMIDITA_MAX = 0, 100             # %
PESO_MIN = 0                                  # kg, no upper bound
BATTERIA_MIN, BATTERIA_MAX = 0, 5             # V

# Decimal-degree coordinates of an arnia.
LATITUDINE_MIN, LATITUDINE_MAX = -90, 90
LONGITUDINE_MIN, LONGITUDINE_MAX = -180, 180

# Length of `nodi.id_nodo` and `arnie.id_sensore_fisico`, which the MQTT
# contract publishes as maxLength.
ID_MAX_LENGTH = 50

# Value sets. The Literal is what pydantic and the OpenAPI schema use; the tuple
# is what the CHECK constraint is built from. Both come from one declaration.
Ruolo = Literal["user", "admin"]
Permesso = Literal["read", "write", "admin"]
TipoAttivita = Literal[
    "ispezione",
    "trattamento",
    "raccolta_miele",
    "nutrizione",
    "sostituzione_regina",
    "controllo_salute",
    "manutenzione",
    "altro",
]

RUOLI = get_args(Ruolo)
PERMESSI = get_args(Permesso)
TIPI_ATTIVITA = get_args(TipoAttivita)
