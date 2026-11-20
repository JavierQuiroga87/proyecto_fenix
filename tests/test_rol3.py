import pytest
import json
import time
import hmac
import hashlib
from unittest.mock import patch, MagicMock

from fenix.utils.crypto import verify, signature
from fenix.utils.errors import ValidationError
from fenix.services.remediation import repair

SECRET_TEST = "mi_secreto_super_seguro_para_testing_123"
BODY_TEST = b'{"schema_version": 1, "event_id": "evt-001", "event_type": "instance.stopped", "resource_id": "node-01"}'

@pytest.fixture
def valid_timestamp():
    return int(time.time())

@pytest.fixture
def valid_header(valid_timestamp):
    v1 = signature(SECRET_TEST, valid_timestamp, BODY_TEST)
    return f"t={valid_timestamp},v1={v1}"

def test_verify_firma_valida(valid_header):
    """Caso feliz: La firma es válida y no debe lanzar excepción."""
    verify(SECRET_TEST, valid_header, BODY_TEST)

def test_verify_firma_invalida(valid_header):
    """Ataque: Alguien modifica el body, la firma no coincidirá."""
    body_alterado = b'{"schema_version": 1, "event_id": "evt-002", "event_type": "instance.stopped", "resource_id": "node-01"}'
    with pytest.raises(ValidationError, match="Firma inválida: no coincide"):
        verify(SECRET_TEST, valid_header, body_alterado)

def test_verify_replay_attack(valid_timestamp):
    """Ataque de Replay: Alguien reenvía un mensaje viejo (más de 300s)."""
    old_timestamp = valid_timestamp - 301
    v1 = signature(SECRET_TEST, old_timestamp, BODY_TEST)
    old_header = f"t={old_timestamp},v1={v1}"
    
    with pytest.raises(ValidationError, match="Firma expirada"):
        verify(SECRET_TEST, old_header, BODY_TEST)

@patch('boto3.client')
def test_repair_ec2_apagada(mock_boto_client):
    """Caso de negocio: Instancia apagada debe encenderse."""
    mock_ec2 = MagicMock()
    mock_boto_client.return_value = mock_ec2
    
    mock_ec2.describe_instances.return_value = {
        'Reservations': [{'Instances': [{'State': {'Name': 'stopped'}}]}]
    }
    
    event = {"resource_id": "node-01", "event_type": "instance.stopped"}
    
    resultado = repair(event, {})
    
    assert resultado["action"] == "ec2_started"
    mock_ec2.start_instances.assert_called_once_with(InstanceIds=["node-01"])

@patch('boto3.client')
def test_repair_ec2_ya_prendida(mock_boto_client):
    """Idempotencia: Si la instancia YA está encendida, no hacer nada."""
    mock_ec2 = MagicMock()
    mock_boto_client.return_value = mock_ec2
    
    mock_ec2.describe_instances.return_value = {
        'Reservations': [{'Instances': [{'State': {'Name': 'running'}}]}]
    }
    
    event = {"resource_id": "node-01", "event_type": "instance.stopped"}
    
    resultado = repair(event, {})
    
    assert resultado["action"] == "none"
    assert resultado["status"] == "already_running"
    mock_ec2.start_instances.assert_not_called()