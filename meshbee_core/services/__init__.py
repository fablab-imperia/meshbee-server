"""Business logic: the decisions Meshbee makes, independent of HTTP and MQTT.

Services call the repository to persist and raise `meshbee_core.errors`,
never HTTPException.
"""
