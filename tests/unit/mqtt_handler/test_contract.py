"""Agreement between the MQTT contract and everything that mirrors it.

`contract.py` describes the wire format, `payload.py` decodes it, the two
READMEs document it in prose and `mqtt-payload.schema.json` is what other
repositories read. Nothing at runtime connects the four — the model is
deliberately *not* used to validate incoming messages — so this module is the
only thing keeping them from drifting apart.
"""
import json
import re
from pathlib import Path

import pytest

from mqtt_handler import contract, payload
from scripts.export_mqtt_schema import render

PACKAGE = Path(payload.__file__).parent
COMMITTED = PACKAGE / "mqtt-payload.schema.json"
READMES = [PACKAGE / "README.md", PACKAGE / "README.it.md"]

TOPIC = "beehive/NODE001/data"

# The payload example in each README: the first ```json block in the file.
JSON_BLOCK = re.compile(r"```json\n(\{.*?\})\n```", re.DOTALL)


def test_the_model_describes_exactly_the_fields_the_handler_produces():
    """
    A field added to one side has to reach the other.

    `parse_message` is the code that runs; the model is what the firmware, the
    app and the umbrella docs are told to expect. A key in one and not in the
    other is a contract that lies.
    """
    parsed = payload.parse_message(TOPIC, json.dumps({"id_nodo": "NODE001"}).encode())

    assert set(contract.MqttPayload.model_fields) == set(parsed)


def test_the_committed_schema_is_what_the_model_generates():
    """
    The exporter runs by hand, so nothing else would notice a stale artifact.

    There is no CI here: this runs under `docker-compose exec api pytest`, which
    is exactly where someone who just edited the model will see it.
    """
    assert COMMITTED.read_text(encoding="utf-8") == render(), (
        "mqtt_handler/mqtt-payload.schema.json is stale — regenerate it with "
        "`make mqtt-schema` (docker-compose exec api python -m scripts.export_mqtt_schema)."
    )


@pytest.mark.parametrize("readme", READMES, ids=["en", "it"])
def test_the_readme_example_satisfies_the_contract(readme):
    """
    The documented example is the first thing anyone copies. Both languages.

    Validating through the model rather than a JSON Schema library is not a
    compromise: the model *is* the schema's source, and it carries the same
    types, ranges and lengths. What it cannot catch is the exporter mangling a
    keyword — the test above catches that instead.
    """
    match = JSON_BLOCK.search(readme.read_text(encoding="utf-8"))
    assert match, f"no ```json payload example in {readme.name}"
    example = json.loads(match.group(1))

    contract.MqttPayload.model_validate(example)
    # extra="allow" means model_validate accepts a misspelt key in silence, and
    # a misspelt key in the example is exactly the bug worth catching here.
    assert set(example) <= set(contract.MqttPayload.model_fields)


@pytest.mark.parametrize("readme", READMES, ids=["en", "it"])
def test_every_contract_field_appears_in_the_payload_table(readme):
    """The prose table and the schema are two views of one contract."""
    text = readme.read_text(encoding="utf-8")

    for field in contract.MqttPayload.model_fields:
        assert f"| `{field}` |" in text, f"{field} is missing from {readme.name}"
