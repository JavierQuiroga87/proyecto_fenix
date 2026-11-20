"""Pruebas del Integrante 6 para contratos de seguridad, eventos y logs.

Las pruebas de HTTP/worker (F06, F09, F11 y F12) se agregan al integrar los
módulos receiver.py y worker.py, porque sus interfaces son responsabilidad de
I3 e I5 y todavía deben coincidir con el código finalmente integrado.
"""
from __future__ import annotations

import gzip
import json
import logging
from pathlib import Path

import pytest

from fenix.services.events import validate
from fenix.utils.crypto import signature, verify
from fenix.utils.errors import InventoryError, ValidationError
from fenix.utils.logging_json import JSONFormatter, setup


TEST_SECRET = "clave-ficticia-solo-para-tests"
TEST_NOW = 1_900_000_000
TEST_BODY = b'{"event":"instance.stopped"}'
TEST_INVENTORY = {
    "node-01": {"type": "ec2", "id": "i-00000000000000001"},
    "bucket-01": {"type": "s3", "id": "fenix-test-bucket"},
}


def _signed_header(body: bytes = TEST_BODY, timestamp: int = TEST_NOW) -> str:
    digest = signature(TEST_SECRET, timestamp, body)
    return f"t={timestamp},v1={digest}"


def _valid_event() -> dict:
    return {
        "schema_version": 1,
        "event_id": "evt-node-001",
        "event_type": "instance.stopped",
        "resource_id": "node-01",
        "occurred_at": "2026-11-16T12:00:00Z",
        "simulate_failures": 0,
    }


# F04 / F05: autenticación HMAC, ventana temporal y bytes originales.
def test_signature_authenticates_raw_bytes() -> None:
    body = b'{"x":1}'
    digest = signature(TEST_SECRET, 1000, body)
    header = f"t=1000,v1={digest}"

    assert verify(TEST_SECRET, header, body, now=1000) is None
    with pytest.raises(ValidationError):
        verify(TEST_SECRET, header, b'{"x": 1}', now=1000)


def test_f04_rejects_invalid_signature() -> None:
    digest = signature(TEST_SECRET, TEST_NOW, TEST_BODY)
    wrong = ("0" if digest[0] != "0" else "1") + digest[1:]
    with pytest.raises(ValidationError):
        verify(TEST_SECRET, f"t={TEST_NOW},v1={wrong}", TEST_BODY, now=TEST_NOW)


@pytest.mark.parametrize("offset", [-301, 301])
def test_f04_rejects_timestamp_outside_window(offset: int) -> None:
    timestamp = TEST_NOW + offset
    header = _signed_header(TEST_BODY, timestamp)
    with pytest.raises(ValidationError):
        verify(TEST_SECRET, header, TEST_BODY, now=TEST_NOW)


def test_f04_accepts_timestamp_at_window_boundary() -> None:
    timestamp = TEST_NOW - 300
    verify(TEST_SECRET, _signed_header(TEST_BODY, timestamp), TEST_BODY, now=TEST_NOW)


def test_f04_rejects_duplicate_signature_fields() -> None:
    header = _signed_header()
    with pytest.raises(ValidationError):
        verify(TEST_SECRET, header + ",v1=" + signature(TEST_SECRET, TEST_NOW, TEST_BODY),
               TEST_BODY, now=TEST_NOW)


def test_f05_same_json_meaning_with_different_bytes_is_rejected() -> None:
    original = b'{"x":1}'
    reformatted = b'{ "x": 1 }'
    header = _signed_header(original, TEST_NOW)
    with pytest.raises(ValidationError):
        verify(TEST_SECRET, header, reformatted, now=TEST_NOW)


# F07: contrato cerrado e inventario autorizado.
def test_f07_accepts_known_resource_and_returns_copy() -> None:
    event = _valid_event()
    result = validate(event, inventory=TEST_INVENTORY)
    assert result == event
    assert result is not event


def test_f07_rejects_resource_outside_group_inventory() -> None:
    event = _valid_event()
    event["resource_id"] = "node-foreign"
    with pytest.raises(InventoryError):
        validate(event, inventory=TEST_INVENTORY)


def test_f07_rejects_extra_contract_field() -> None:
    event = _valid_event()
    event["admin_override"] = True
    with pytest.raises(ValidationError):
        validate(event, inventory=TEST_INVENTORY)


def test_f07_rejects_boolean_simulate_failures() -> None:
    event = _valid_event()
    event["simulate_failures"] = True
    with pytest.raises(ValidationError):
        validate(event, inventory=TEST_INVENTORY)


# F16: formato JSON y rotación comprimida.
def test_f16_json_formatter_keeps_correlation_fields() -> None:
    record = logging.LogRecord(
        name="fenix-test", level=logging.INFO, pathname=__file__, lineno=1,
        msg="reparacion completada", args=(), exc_info=None,
    )
    record.event_id = "evt-node-001"
    record.message_id = "message-123"
    record.resource_id = "node-01"
    record.attempt = 2
    record.action = "start_instance"
    record.status = "success"

    line = JSONFormatter().format(record)
    parsed = json.loads(line)
    assert parsed["event_id"] == "evt-node-001"
    assert parsed["message_id"] == "message-123"
    assert parsed["resource_id"] == "node-01"
    assert parsed["attempt"] == 2
    assert parsed["action"] == "start_instance"
    assert parsed["status"] == "success"


def test_f16_forces_rotation_and_reads_gzip_history(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    logger, listener = setup("fenix-i6-rotation-test")
    sink = listener.handlers[0]
    sink.maxBytes = 300  # Reduce el umbral solo para esta prueba.
    sink.backupCount = 3

    try:
        for number in range(12):
            logger.info(
                "registro de prueba %s %s", number, "x" * 120,
                extra={"event_id": f"evt-{number:03d}", "action": "test", "status": "ok"},
            )
    finally:
        listener.stop()  # Vacía la cola de logs y cierra el archivo.
        logger.handlers.clear()

    archives = list((tmp_path / "logs").glob("*.gz"))
    assert archives, "La rotación debía producir al menos un histórico .gz"
    decoded_lines = []
    for archive in archives:
        with gzip.open(archive, "rt", encoding="utf-8") as compressed:
            decoded_lines.extend(compressed.readlines())
    assert decoded_lines
    for line in decoded_lines:
        assert isinstance(json.loads(line), dict)
