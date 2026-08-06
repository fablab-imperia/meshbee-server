#!/usr/bin/env python3
"""
Export the MQTT payload contract to a JSON Schema file.

`mqtt_handler/contract.py` describes the wire format as a pydantic model so the
contract can be published as something a machine reads — the counterpart of what
`export_openapi.py` does for the API. This writes that artifact:

    docker-compose exec api python -m scripts.export_mqtt_schema   (or: make mqtt-schema)

The api image carries `mqtt_handler/` and compose bind-mounts it, so the output
lands in the working tree. Unlike `export_openapi.py` nothing here builds
`Settings`, so this would also run on the host — do it in the container anyway,
so the pinned pydantic version is the one that generated the committed file.

The output is sorted and indented so regenerating an unchanged contract produces
an empty diff, and `tests/unit/mqtt_handler/test_contract.py` fails for as long
as the committed file and the model disagree.
"""
import json
import sys
from pathlib import Path

from mqtt_handler.contract import SCHEMA_DIALECT, SCHEMA_ID, MqttPayload

# Relative to the repo root, which is the working directory in the api container.
DEFAULT_OUTPUT = Path("mqtt_handler/mqtt-payload.schema.json")


def collapse_descriptions(node) -> None:
    """
    Fold every wrapped description onto one line, in place.

    Descriptions are written across several lines in contract.py because that is
    what reads well in Python; they are read one per line in the JSON for the
    same reason.
    """
    if isinstance(node, dict):
        if isinstance(node.get("description"), str):
            node["description"] = " ".join(node["description"].split())
        for value in node.values():
            collapse_descriptions(value)
    elif isinstance(node, list):
        for value in node:
            collapse_descriptions(value)


def build_schema() -> dict:
    """Pydantic's document, plus the JSON Schema envelope it knows nothing about."""
    schema = MqttPayload.model_json_schema()

    for prop in schema["properties"].values():
        # Absence, not an explicit null. Every field carries default=None only to
        # stay out of `required`; publishing `"default": null` would tell a code
        # generator to *send* a null, which the handler does not expect.
        prop.pop("default", None)
        # Pydantic derives a title from the attribute name ("Id Nodo"). It says
        # nothing the description does not.
        prop.pop("title", None)

    collapse_descriptions(schema)

    # `additionalProperties` already follows from extra="allow", but is restated
    # so the published contract cannot change because a pydantic upgrade renders
    # that config differently.
    return {
        "$schema": SCHEMA_DIALECT,
        "$id": SCHEMA_ID,
        **schema,
        "additionalProperties": True,
    }


def render() -> str:
    """The exact bytes of the artifact, so a test can compare without guessing."""
    return json.dumps(build_schema(), indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def export(destination: Path) -> None:
    destination.write_text(render(), encoding="utf-8")
    print(f"Schema del payload MQTT scritto in {destination}")


if __name__ == "__main__":
    export(Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUTPUT)
