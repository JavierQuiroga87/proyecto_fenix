
"""Pruebas de diagnóstico, idempotencia y orden de confirmación - I6."""

import json

import pytest

from fenix.services import remediation, notifications, worker
from fenix.utils.state import load


def make_event():
    """Genera un evento válido para el inventario de prueba."""
    return {
        "schema_version": 1,
        "event_id": "evt-test-001",
        "event_type": "instance.stopped",
        "resource_id": "node-01",
        "occurred_at": "2026-11-18T18:00:00Z",
        "simulate_failures": 0,
    }


def test_duplicate_is_idempotent(tmp_path, monkeypatch):
    """Una repetición no vuelve a reparar ni a notificar."""

    inventory = {
        "node-01": {"type": "ec2"}
    }
    event = make_event()
    ledger_path = tmp_path / "events.json"

    repair_calls = []
    notification_calls = []

    def fake_repair(event, inventory):
        repair_calls.append(event["event_id"])
        return {"resource_id": event["resource_id"], "status": "repaired"}

    def fake_notify(event, result):
        notification_calls.append(event["event_id"])

    # Sustituimos únicamente las dependencias externas.
    monkeypatch.setattr(
        remediation, "repair", fake_repair, raising=False
    )
    monkeypatch.setattr(
        notifications, "notify", fake_notify, raising=False
    )

    # Primera ejecución.
    first_result = remediation.handle(
        event, inventory, ledger_path=str(ledger_path)
    )

    assert first_result["repair_done"] is True
    assert first_result["notified"] is True

    # Simulamos la recuperación del estado desde el disco.
    saved_state = load(str(ledger_path))
    assert event["event_id"] in saved_state

    # Segunda ejecución del mismo evento.
    second_result = remediation.handle(
        event, inventory, ledger_path=str(ledger_path)
    )

    # La reparación y la notificación deben ejecutarse una sola vez.
    assert repair_calls == ["evt-test-001"]
    assert notification_calls == ["evt-test-001"]

    # El registro conserva el estado completado.
    assert second_result["repair_done"] is True
    assert second_result["notified"] is True
    assert second_result["status"] == "completed"
    assert second_result["attempts"] == 2


def test_ack_is_after_success(tmp_path, monkeypatch):
    """El worker solo confirma el mensaje cuando el handler termina bien."""

    monkeypatch.chdir(tmp_path)

    data_dir = tmp_path / "data"
    data_dir.mkdir()

    inventory = {"node-01": {"type": "ec2"}}
    (data_dir / "inventory.json").write_text(
        json.dumps(inventory),
        encoding="utf-8",
    )

    event = make_event()
    message = {
        "Body": json.dumps(event),
        "ReceiptHandle": "receipt-test-001",
        "Attributes": {"ApproximateReceiveCount": "1"},
    }

    class FakeLogger:
        def info(self, *args, **kwargs):
            pass

        def exception(self, *args, **kwargs):
            pass

    class FakeListener:
        def stop(self):
            pass

    monkeypatch.setattr(
        worker, "setup",
        lambda name: (FakeLogger(), FakeListener())
    )
    monkeypatch.setattr(
        worker, "queue_url",
        lambda prefix: "http://localhost/test-queue"
    )
    monkeypatch.setattr(
        worker, "receive",
        lambda url: [message]
    )
    monkeypatch.setattr(
        worker, "mark_acknowledged",
        lambda event_id, ledger_path: None
    )

    calls = []

    def fake_ack(url, receipt):
        calls.append("ack")

    def fake_retry(url, received_message):
        calls.append("retry")
        return 2

    monkeypatch.setattr(worker, "acknowledge", fake_ack)
    monkeypatch.setattr(worker, "retry_later", fake_retry)

    # Caso 1: el procesamiento falla.
    def failing_handler(event, inventory, ledger_path):
        calls.append("handler")
        raise RuntimeError("Falla controlada de prueba")

    monkeypatch.setattr(worker, "handle", failing_handler)

    worker.run(once=True)

    assert calls == ["handler", "retry"]
    assert "ack" not in calls

    # Caso 2: el procesamiento termina correctamente.
    calls.clear()

    def successful_handler(event, inventory, ledger_path):
        calls.append("handler")
        return {"status": "completed"}

    monkeypatch.setattr(worker, "handle", successful_handler)

    worker.run(once=True)

    assert calls == ["handler", "ack"]


@pytest.mark.integracion
def test_redrive_with_localstack():
    """Pendiente hasta disponer de la configuración real de I2."""
    pytest.skip(
        "I6-D requiere que I2 implemente ensure_queues y retry_later "
        "para probar el redrive real en LocalStack."
    )
