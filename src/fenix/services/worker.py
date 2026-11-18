
"""Worker encargado de consumir y procesar eventos de SQS."""

import json
import os
import time

from botocore.exceptions import BotoCoreError, ClientError

from fenix.services.sqs import (
    queue_url,
    receive,
    acknowledge,
    retry_later,
)
from fenix.services.events import validate
from fenix.services.remediation import handle
from fenix.utils.logging_json import setup
from fenix.utils.state import load, save


def load_inventory(path="data/inventory.json"):
    """Carga el inventario oficial del proyecto."""
    with open(path, "r", encoding="utf-8") as file:
        inventory = json.load(file)

    if not isinstance(inventory, dict):
        raise ValueError("El inventario debe ser un objeto JSON.")

    return inventory


def mark_acknowledged(event_id, ledger_path):
    """Registra que SQS confirmó la eliminación del mensaje."""
    ledger = load(ledger_path)

    if not isinstance(ledger, dict):
        raise ValueError("El registro de eventos no es válido.")

    if event_id not in ledger:
        raise KeyError(
            f"No existe el evento {event_id} en el registro."
        )

    record = ledger[event_id]

    if not isinstance(record, dict):
        raise ValueError("El registro del evento no es válido.")

    record["status"] = "acknowledged"
    save(ledger_path, ledger)


def run(once: bool = False):
    """Consume mensajes SQS y procesa sus eventos."""

    logger, listener = setup("fenix-worker")

    try:
        prefix = os.getenv("QUEUE_PREFIX", "fenix-grupo01")
        ledger_path = "data/events.json"

        inventory = load_inventory()
        url = queue_url(prefix)

        logger.info("Worker iniciado")

        while True:
            try:
                messages = receive(url)

            except (BotoCoreError, ClientError, ConnectionError, TimeoutError):
                logger.exception("Error de transporte al consultar SQS")

                if once:
                    break

                time.sleep(2)
                continue

            except Exception:
                logger.exception("Error inesperado al consultar SQS")

                if once:
                    break

                time.sleep(2)
                continue

            if not messages:
                if once:
                    logger.info("No hay mensajes. Worker finalizado.")
                    break

                continue

            for message in messages:
                receipt = message.get("ReceiptHandle")

                try:
                    event = json.loads(message["Body"])

                    if not isinstance(event, dict):
                        raise ValueError(
                            "El mensaje debe contener un objeto JSON."
                        )

                    event = validate(event, inventory)

                    handle(
                        event,
                        inventory,
                        ledger_path=ledger_path,
                    )

                    # Primero se confirma la eliminación en SQS.
                    acknowledge(url, receipt)

                    # Después se actualiza el registro local.
                    try:
                        mark_acknowledged(
                            event["event_id"],
                            ledger_path,
                        )
                    except Exception:
                        logger.exception(
                            "El mensaje fue confirmado en SQS, "
                            "pero no se pudo actualizar el registro local."
                        )

                    logger.info(
                        "Evento confirmado correctamente",
                        extra={"event_id": event["event_id"]},
                    )

                except Exception:
                    logger.exception("Error al procesar el mensaje")

                    try:
                        retry_later(url, message)

                    except NotImplementedError:
                        logger.exception(
                            "retry_later todavía no está implementada por I2."
                        )

                    except Exception:
                        logger.exception(
                            "No se pudo programar el reintento."
                        )

            if once:
                logger.info("Modo de ejecución única finalizado.")
                break

    finally:
        logger.info("Worker detenido.")
        listener.stop()
