"""Preparación idempotente de recursos de demostración e inyección de fallas (I2)."""
import os
from botocore.exceptions import ClientError
from fenix.config.settings import client
from fenix.utils.errors import InventoryError, ValidationError
from fenix.utils.state import load, save


def _group_config() -> tuple[str, str, str]:
    """Obtiene identificadores del grupo y región desde variables de entorno."""
    group = os.getenv("GROUP_ID", "grupo01").strip() or "grupo01"
    project = os.getenv("PROJECT", "fenix").strip() or "fenix"
    region = os.getenv("AWS_DEFAULT_REGION", "us-east-1").strip() or "us-east-1"
    return group, project, region


def _ensure_ec2_node(ec2, existing: dict, group: str, project: str) -> str:
    """Reutiliza una instancia EC2 activa o crea una nueva con tags del grupo."""
    instance_id = existing.get("instance_id")
    if instance_id:
        try:
            resp = ec2.describe_instances(InstanceIds=[instance_id])
            reservations = resp.get("Reservations", [])
            if reservations and reservations[0].get("Instances"):
                state = reservations[0]["Instances"][0]["State"]["Name"]
                if state not in ("terminated", "shutting-down"):
                    return instance_id
        except ClientError:
            pass

    tags = [
        {"Key": "Name", "Value": f"{project}-{group}-node-01"},
        {"Key": "Project", "Value": project},
        {"Key": "Group", "Value": group},
    ]
    created = ec2.run_instances(
        ImageId="ami-12345678",
        InstanceType="t3.micro",
        MinCount=1,
        MaxCount=1,
        TagSpecifications=[{"ResourceType": "instance", "Tags": tags}],
    )
    return created["Instances"][0]["InstanceId"]


def _ensure_s3_bucket(s3, bucket_name: str, region: str, group: str, project: str) -> None:
    """Crea o reutiliza el bucket S3 del grupo y asegura sus etiquetas obligatorias."""
    try:
        s3.head_bucket(Bucket=bucket_name)
    except ClientError:
        if region == "us-east-1":
            s3.create_bucket(Bucket=bucket_name)
        else:
            s3.create_bucket(
                Bucket=bucket_name,
                CreateBucketConfiguration={"LocationConstraint": region},
            )

    s3.put_bucket_tagging(
        Bucket=bucket_name,
        Tagging={
            "TagSet": [
                {"Key": "Project", "Value": project},
                {"Key": "Group", "Value": group},
            ]
        },
    )


def setup_demo(inventory_path: str = "data/inventory.json") -> dict:
    """Crea o actualiza el inventario local y los recursos EC2/S3 en LocalStack."""
    group, project, region = _group_config()
    current = load(inventory_path)
    if not isinstance(current, dict):
        current = {}

    ec2 = client("ec2")
    s3 = client("s3")

    node_meta = current.get("node-01") if isinstance(current.get("node-01"), dict) else {}
    instance_id = _ensure_ec2_node(ec2, node_meta, group, project)

    bucket_meta = current.get("bucket-01") if isinstance(current.get("bucket-01"), dict) else {}
    bucket_name = bucket_meta.get("bucket_name") or f"{project}-{group}-bucket-01"
    _ensure_s3_bucket(s3, bucket_name, region, group, project)

    inventory = {
        "node-01": {
            "type": "ec2",
            "instance_id": instance_id,
            "name": f"{project}-{group}-node-01",
            "group": group,
            "project": project,
        },
        "bucket-01": {
            "type": "s3",
            "bucket_name": bucket_name,
            "group": group,
            "project": project,
        },
    }
    save(inventory_path, inventory)
    return inventory


def fault(resource_id: str, inventory_path: str = "data/inventory.json") -> None:
    """Provoca una falla controlada en un recurso registrado del inventario."""
    inventory = load(inventory_path)
    if not isinstance(inventory, dict) or resource_id not in inventory:
        raise InventoryError(
            f"El recurso '{resource_id}' no existe en el inventario ({inventory_path})."
        )

    resource = inventory[resource_id]
    res_type = resource.get("type")

    if res_type == "ec2":
        instance_id = resource.get("instance_id")
        if not instance_id:
            raise ValidationError(f"El recurso '{resource_id}' no tiene instance_id configurado.")
        client("ec2").stop_instances(InstanceIds=[instance_id])
        return

    if res_type == "s3":
        bucket_name = resource.get("bucket_name")
        if not bucket_name:
            raise ValidationError(f"El recurso '{resource_id}' no tiene bucket_name configurado.")
        client("s3").delete_bucket_tagging(Bucket=bucket_name)
        return

    raise ValidationError(f"Tipo de recurso no soportado para fallas: '{res_type}'.")
