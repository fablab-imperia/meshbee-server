"""Decoding what a node actually put on the wire.

Kept apart from the broker plumbing so the quirks of the payload format can be
tested without a broker or a database — this is the layer that will grow when
nodes start sending a versioned payload.
"""
import json
import logging
from datetime import datetime
from typing import Any, Dict

logger = logging.getLogger(__name__)


def parse_timestamp(value: Any):
    """
    Coerce a reported timestamp to a datetime, or None to mean "now".

    A node with a wrong clock format should not cost us the measurement, so an
    unparseable value degrades to the server's own time rather than rejecting
    the reading.
    """
    if not value:
        return None
    if not isinstance(value, str):
        return value

    try:
        # ESP32 firmware sends the Zulu suffix, which fromisoformat rejects
        # before Python 3.11.
        return datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as exc:
        logger.warning(f"Errore parsing timestamp: {exc}, uso timestamp corrente")
        return None


def parse_message(topic: str, raw: bytes) -> Dict[str, Any]:
    """
    Turn one MQTT message into the fields the ingest service expects.

    The node id may come from the payload or from the topic (`beehive/<id>/data`);
    the payload wins when both are present.

    Raises:
        ValueError: se il messaggio non è utilizzabile.
    """
    try:
        data = json.loads(raw.decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Errore parsing JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError(f"Payload non è un oggetto JSON: {raw!r}")

    # es: beehive/NODE001/data
    topic_parts = topic.split('/')
    id_nodo_from_topic = topic_parts[1] if len(topic_parts) >= 2 else None

    id_nodo = data.get('id_nodo', id_nodo_from_topic)
    if not id_nodo:
        raise ValueError(f"Messaggio senza id_nodo: {raw!r}")

    return {
        'id_nodo': id_nodo,
        'id_sensore': data.get('id_sensore'),
        'timestamp': parse_timestamp(data.get('timestamp')),
        'temperatura': data.get('temperatura'),
        'umidita': data.get('umidita'),
        'peso': data.get('peso'),
        'bat': data.get('bat'),
        'dati_raw': data.get('dati_raw'),
    }
