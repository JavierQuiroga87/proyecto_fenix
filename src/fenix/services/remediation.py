
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
import boto3
from botocore.exceptions import ClientError
from fenix.utils.errors import TransientError, RemediationError

LOCALSTACK_URL = "http://localhost:4566"
REGION = "us-east-1"

def repair(event: dict, inventory: dict) -> dict:
    """Función convergente de reparación con Boto3."""
    resource_id = event.get("resource_id")
    event_type = event.get("event_type")
    
    ec2 = boto3.client('ec2', endpoint_url=LOCALSTACK_URL, region_name=REGION,
                       aws_access_key_id='test', aws_secret_access_key='test')
    s3 = boto3.client('s3', endpoint_url=LOCALSTACK_URL, region_name=REGION,
                      aws_access_key_id='test', aws_secret_access_key='test')

    try:
        if event_type == "instance.stopped":
            try:
                response = ec2.describe_instances(InstanceIds=[resource_id])
                state = response['Reservations'][0]['Instances'][0]['State']['Name']
                
                if state != 'running':
                    ec2.start_instances(InstanceIds=[resource_id])
                    return {"action": "ec2_started", "resource_id": resource_id, "status": "success"}
                return {"action": "none", "resource_id": resource_id, "status": "already_running"}
            except ClientError as e:
                raise TransientError(f"Error de AWS al reparar EC2: {e}")

        elif event_type == "s3.tags_missing":
            expected_tags = inventory.get(resource_id, {}).get("tags", {})
            if not expected_tags:
                return {"action": "none", "resource_id": resource_id, "status": "no_tags_in_inventory"}

            tag_set = [{'Key': k, 'Value': v} for k, v in expected_tags.items()]
            
            try:
                s3.put_bucket_tagging(Bucket=resource_id, Tagging={'TagSet': tag_set})
                return {"action": "s3_tags_restored", "resource_id": resource_id, "status": "success"}
            except ClientError as e:
                raise TransientError(f"Error de AWS al reparar S3: {e}")

        return {"action": "ignored", "resource_id": resource_id, "status": "unsupported_event"}

    except TransientError:
        raise 
    except Exception as e:
        raise RemediationError(f"Error inesperado en reparación: {str(e)}")