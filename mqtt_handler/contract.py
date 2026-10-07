"""The MQTT wire contract, as a schema rather than as prose.

`payload.py` decodes what a node put on the wire; this module *describes* what it
is supposed to put there. Nothing validates against it at runtime — decoding
stays deliberately lenient, because a node with one broken sensor should still
get its other measurements stored, and the ranges are enforced once, later, by
`meshbee_core.schemas.LetturaCreate`. The model exists so that
`scripts/export_mqtt_schema.py` can generate `mqtt-payload.schema.json`: the
artifact the firmware, the app and the umbrella repository's contract pages point
at, none of which can read the table in `README.md`.

Because no code imports it, only tests keep it honest —
`tests/unit/mqtt_handler/test_contract.py` pins it to what `parse_message`
returns and to the committed JSON, and `tests/integration/core/test_schemas.py`
pins its ranges to `LetturaBase` and to the CHECK constraints in
`database/init.sql`.

Every field carries `default=None` while no annotation is `Optional`. That is
deliberate: on the wire a field is *absent* — a node with only a scale sends only
`peso` — never explicitly null. The default is what keeps the field out of
`required`; a non-optional annotation is what keeps `"type": "string"` from
becoming `["string", "null"]`. Pydantic does not validate defaults, so `None`
never trips a bound.
"""
from datetime import datetime
from typing import Any, Dict

from pydantic import BaseModel, ConfigDict, Field

# Where the artifact is served and what its own `$id` claims: this file, on this
# branch. A `$ref` in someone's toolchain resolves against this URL, so moving or
# renaming the file is a breaking change for anyone who wrote one — regenerate
# and announce it, don't just fix the path.
#
# It used to name the docs site, which meant the meshbee repo had to fetch and
# republish these bytes to keep the `$id` honest. Pointing at the generated file
# itself removes that round trip: one copy, in the repo that generates it.
SCHEMA_ID = (
    "https://raw.githubusercontent.com/fablab-imperia/meshbee-server/main"
    "/mqtt_handler/mqtt-payload.schema.json"
)
SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"

# nodi.id_nodo and arnie.id_sensore_fisico are VARCHAR(50) in database/init.sql.
ID_MAX_LENGTH = 50

# The third copy of the ranges on meshbee_core.schemas.LetturaBase and of the
# valid_temperatura / valid_umidita / valid_peso / valid_batteria CHECK constraints. Nothing links
# the three — tests/integration/core/test_schemas.py derives its cases from here.
TEMPERATURA_MIN, TEMPERATURA_MAX = -50, 100
UMIDITA_MIN, UMIDITA_MAX = 0, 100
PESO_MIN = 0
BATTERIA_MIN, BATTERIA_MAX = 0, 5


class MqttPayload(BaseModel):
    """
    One reading published by a node to beehive/<id_nodo>/data.

    Generated from mqtt_handler/contract.py in meshbee-server; the code that
    consumes it is mqtt_handler/payload.py. Every field is optional and unknown
    fields are preserved, so adding one is a backwards-compatible change. No
    field carries a payload version yet; see the contract docs for the planned
    versioning scheme.
    """

    # extra="allow" is what puts `additionalProperties: true` in the schema: a
    # consumer must ignore the keys it does not know.
    model_config = ConfigDict(title="MeshBee MQTT payload", extra="allow")

    id_nodo: str = Field(
        default=None,
        max_length=ID_MAX_LENGTH,
        description=(
            "Node identifier. Optional in the body: it falls back to the "
            "<id_nodo> segment of the topic, and the body wins when both are "
            "present. A message is rejected only when neither supplies one."
        ),
    )
    id_sensore: str = Field(
        default=None,
        max_length=ID_MAX_LENGTH,
        description=(
            "Identifies the hive on that node. An unknown value provisions a "
            "new hive; when absent, the node's first hive is used."
        ),
    )
    timestamp: datetime = Field(
        default=None,
        description=(
            "Reading time, ISO 8601. A trailing Z is accepted. Absent or "
            "unparseable values fall back to server time."
        ),
    )
    temperatura: float = Field(
        default=None,
        ge=TEMPERATURA_MIN,
        le=TEMPERATURA_MAX,
        description="Temperature in °C. Out of range drops the whole message.",
    )
    umidita: float = Field(
        default=None,
        ge=UMIDITA_MIN,
        le=UMIDITA_MAX,
        description="Relative humidity in %. Out of range drops the whole message.",
    )
    peso: float = Field(
        default=None,
        ge=PESO_MIN,
        description="Hive weight in kg. Out of range drops the whole message.",
    )
    # The firmware's key is `bat`; it is stored as `letture.batteria`. The
    # rename happens in meshbee_core.services.ingest, not on the wire.
    bat: float = Field(
        default=None,
        ge=BATTERIA_MIN,
        le=BATTERIA_MAX,
        description=(
            "Node battery voltage in V. Out of range drops the whole message."
        ),
    )
    dati_raw: Dict[str, Any] = Field(
        default=None,
        # A `Dict[str, Any]` renders as a bare `{"type": "object"}` — pydantic
        # omits `additionalProperties` when the value schema is `Any`. Stated
        # explicitly because this is the one field where "anything goes" is the
        # point rather than an accident.
        json_schema_extra={"additionalProperties": True},
        description=(
            "Anything else the firmware wants to keep — RSSI and so on. "
            "Stored verbatim as JSONB."
        ),
    )
