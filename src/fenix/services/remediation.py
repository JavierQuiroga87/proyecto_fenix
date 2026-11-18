
"""Coordinación durable de reparación y notificación."""

from copy import deepcopy

from fenix.services.events import validate
from fenix.utils.state import load, save
from fenix.utils.errors import (
    RetryableError,
    RemediationError,
    ValidationError,
)


def handle(
    event: dict,
    inventory: dict,
    ledger_path: str = "data/events.json",
) -> dict:
    """Procesa un evento y guarda cada etapa para poder reanudarlo."""

    # 1. Validar el evento antes de realizar acciones.
    event = validate(event, inventory)
    event_id = event["event_id"]

    # 2. Leer el registro de eventos.
    ledger = load(ledger_path)

    if not isinstance(ledger, dict):
        raise RemediationError("El registro de eventos no tiene un formato válido.")

    # 3. Recuperar el evento o crear un registro nuevo.
    if event_id in ledger:
        record = ledger[event_id]

        # El mismo ID no puede representar dos eventos diferentes.
        if record.get("event") != event:
            raise ValidationError(
                "Conflicto: el event_id ya existe con otro contenido."
            )
    else:
        record = {
            "event": deepcopy(event),
            "attempts": 0,
            "repair_done": False,
            "repair_result": None,
            "notified": False,
            "status": "pending",
        }
        ledger[event_id] = record

    # 4. Registrar este intento.
    record["attempts"] += 1
    save(ledger_path, ledger)

    # 5. Simular fallas antes de comenzar la reparación.
    if record["attempts"] <= event["simulate_failures"]:
        record["status"] = "retrying"
        save(ledger_path, ledger)
        raise RetryableError("Falla de laboratorio simulada.")

    # 6. Reparar solamente si todavía no se reparó.
    if not record["repair_done"]:
        repair_fn = globals().get("repair")

        if not callable(repair_fn):
            raise RemediationError(
                "La función repair() de I3 todavía no está disponible."
            )

        try:
            result = repair_fn(event, inventory)

            if not isinstance(result, dict):
                raise RemediationError(
                    "repair() debe devolver un diccionario."
                )

            record["repair_result"] = result
            record["repair_done"] = True
            record["status"] = "notification_pending"
            save(ledger_path, ledger)

        except Exception:
            record["status"] = "repair_pending"
            save(ledger_path, ledger)
            raise

    # 7. Notificar solamente si todavía no se notificó.
    if not record["notified"]:
        try:
            from fenix.services import notifications

            notify_fn = getattr(notifications, "notify", None)

            if not callable(notify_fn):
                raise RemediationError(
                    "La función notify() de I4 todavía no está disponible."
                )

            notify_fn(event, record["repair_result"])

            record["notified"] = True
            record["status"] = "completed"
            save(ledger_path, ledger)

        except Exception:
            record["status"] = "notification_pending"
            save(ledger_path, ledger)
            raise

    return deepcopy(record)
