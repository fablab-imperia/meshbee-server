#!/usr/bin/env python3
"""
MQTT Handler per Sistema IoT Arnie
Riceve messaggi MQTT dai nodi e li salva nel database PostgreSQL

Thin entry point: the callback parses the payload, opens a cursor and calls one
service in `meshbee_core`. There is no SQL here — the same service backs the
API's manual-insert endpoint, so the two paths cannot drift.
"""
import logging
import signal
import sys
import time

import paho.mqtt.client as mqtt

from meshbee_core.db import close_db_pool, get_db_cursor, init_db_pool
from meshbee_core.errors import CoreError
from meshbee_core.services import ingest
from mqtt_handler.config import get_settings
from mqtt_handler.payload import parse_message

# Configurazione logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# This process holds a handful of connections, not the API's twenty: it does one
# short write per message and nothing concurrent.
DB_POOL_SIZE = 10


class BeehiveMQTTHandler:
    """Handler per messaggi MQTT dal sistema arnie"""

    def __init__(self, settings):
        self.settings = settings
        self.client = mqtt.Client(client_id=settings.MQTT_CLIENT_ID)
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.client.on_disconnect = self.on_disconnect
        self.running = True

    def on_connect(self, client, userdata, flags, rc):
        """Callback quando connesso al broker MQTT"""
        if rc == 0:
            logger.info(
                f"Connesso al broker MQTT {self.settings.MQTT_BROKER}:{self.settings.MQTT_PORT}"
            )
            client.subscribe(self.settings.MQTT_TOPIC)
            logger.info(f"Sottoscritto al topic: {self.settings.MQTT_TOPIC}")
        else:
            logger.error(f"Connessione fallita con codice: {rc}")

    def on_disconnect(self, client, userdata, rc):
        """Callback quando disconnesso dal broker"""
        if rc != 0:
            logger.warning(f"Disconnessione inaspettata. Codice: {rc}")

    def on_message(self, client, userdata, msg):
        """
        Callback quando arriva un messaggio MQTT

        Formato atteso del messaggio JSON:
        {
            "id_nodo": "NODE001",
            "id_sensore": "SENSOR01",
            "timestamp": "2024-02-01T12:00:00",  # opzionale
            "temperatura": 34.5,
            "umidita": 65.0,
            "peso": 42.350,
            "bat": 4.01,  # opzionale, tensione batteria (V)
            "dati_raw": {...}  # opzionale, altri dati
        }
        """
        logger.debug(f"Ricevuto messaggio su {msg.topic}: {msg.payload}")

        try:
            payload = parse_message(msg.topic, msg.payload)
        except ValueError as exc:
            logger.error(str(exc))
            return

        try:
            with get_db_cursor() as cursor:
                lettura = ingest.record_node_reading(cursor, payload)
        except CoreError as exc:
            # An unresolvable arnia or an out-of-range measurement. Expected
            # enough to report without a traceback; the cursor has rolled back.
            logger.error(f"Lettura scartata: {exc}")
            return
        except Exception as exc:
            logger.error(f"Errore salvataggio dati: {exc}", exc_info=True)
            return

        logger.info(
            f"Salvata lettura per arnia {lettura['id_arnia']} "
            f"(nodo: {lettura['id_nodo']}, "
            f"T: {lettura['temperatura']}°C, "
            f"H: {lettura['umidita']}%, "
            f"W: {lettura['peso']}kg, "
            f"B: {lettura['batteria']}V)"
        )

    def run(self):
        """Avvia il client MQTT"""
        try:
            logger.info(
                f"Connessione a {self.settings.MQTT_BROKER}:{self.settings.MQTT_PORT}..."
            )
            if self.settings.MQTT_USER and self.settings.MQTT_PASSWORD:
                self.client.username_pw_set(
                    self.settings.MQTT_USER,
                    self.settings.MQTT_PASSWORD.get_secret_value(),
                )
                logger.info(f"Autenticazione MQTT con utente: {self.settings.MQTT_USER}")
            self.client.connect(
                self.settings.MQTT_BROKER, self.settings.MQTT_PORT, 60
            )
            self.client.loop_start()

            # Mantieni il processo in esecuzione
            while self.running:
                time.sleep(1)

        except KeyboardInterrupt:
            logger.info("Interruzione da tastiera ricevuta")
        except Exception as e:
            logger.error(f"Errore durante esecuzione: {e}", exc_info=True)
        finally:
            self.stop()

    def stop(self):
        """Ferma il client MQTT"""
        logger.info("Fermando MQTT handler...")
        self.running = False
        self.client.loop_stop()
        self.client.disconnect()
        logger.info("MQTT handler fermato")


def signal_handler(signum, frame):
    """Handler per segnali di terminazione"""
    logger.info(f"Ricevuto segnale {signum}")
    sys.exit(0)


def main():
    """Funzione principale"""
    # Registra handler per segnali
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    settings = get_settings()

    # Inizializza database
    logger.info(
        f"Connessione al database {settings.DB_HOST}:{settings.DB_PORT}/{settings.DB_NAME}..."
    )
    try:
        init_db_pool(settings, maxconn=DB_POOL_SIZE)
    except Exception:
        logger.error("Impossibile inizializzare database. Uscita.")
        sys.exit(1)

    try:
        # Avvia handler MQTT
        handler = BeehiveMQTTHandler(settings)
        handler.run()
    finally:
        close_db_pool()


if __name__ == '__main__':
    main()
