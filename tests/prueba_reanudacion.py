
import json
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import Mock, patch

from fenix.services import remediation, notifications

# Archivo de prueba separado del registro real.
ledger_path = "data/test_reanudacion.json"
Path(ledger_path).unlink(missing_ok=True)

event = {
    "schema_version": 1,
    "event_id": "prueba-001",
    "event_type": "instance.stopped",
    "resource_id": "node-01",
    "occurred_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    "simulate_failures": 0,
}

inventory = {
    "node-01": {"type": "ec2"}
}

# Simulamos una reparacion exitosa.
repair_mock = Mock(return_value={"result": "Reparacion realizada"})

# La primera notificacion falla y la segunda funciona.
notify_mock = Mock(
    side_effect=[
        RuntimeError("Fallo de notificacion simulado"),
        None,
    ]
)

try:
    with (
        patch.object(remediation, "repair", repair_mock, create=True),
        patch.object(notifications, "notify", notify_mock, create=True),
    ):
        try:
            remediation.handle(event, inventory, ledger_path)
        except RuntimeError:
            print("Primera notificacion fallida, como esperabamos.")

        ledger = json.loads(Path(ledger_path).read_text(encoding="utf-8"))
        record = ledger["prueba-001"]

        print("Reparacion guardada:", record["repair_done"])
        print("Notificacion pendiente:", not record["notified"])

        result = remediation.handle(event, inventory, ledger_path)

        print("Cantidad de reparaciones:", repair_mock.call_count)
        print("Notificacion completada:", result["notified"])
        print("Estado final:", result["status"])

        assert repair_mock.call_count == 1
        assert result["repair_done"] is True
        assert result["notified"] is True
        assert result["status"] == "completed"

        print("\nPRUEBA DE REANUDACION EXITOSA")

finally:
    Path(ledger_path).unlink(missing_ok=True)
