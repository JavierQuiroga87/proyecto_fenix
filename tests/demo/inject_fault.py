"""Inyección segura y repetible de fallas en los recursos propios de Fénix.

Uso desde la raíz del repositorio:
    python -m tests.demo.inject_fault node-01
    python -m tests.demo.inject_fault bucket-01

`node-01` se detiene en EC2 mock. `bucket-01` pierde la etiqueta Owner en S3.
El módulo nunca acepta IDs arbitrarios: resuelve los recursos exclusivamente
mediante `data/inventory.json` y verifica las etiquetas de propiedad antes de
modificarlos. No elimina recursos.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from dotenv import load_dotenv
from botocore.exceptions import BotoCoreError

from fenix.utils.errors import ValidationError


_REQUIRED_TAGS = {
    "ManagedBy": "ppa2",
    "Project": "fenix",
}


def _tags_to_dict(raw_tags: Any) -> dict[str, str]:
    """Normaliza tags en formato diccionario o lista AWS Key/Value."""
    if isinstance(raw_tags, Mapping):
        return {str(key): str(value) for key, value in raw_tags.items()}
    if isinstance(raw_tags, list):
        normalized: dict[str, str] = {}
        for item in raw_tags:
            if not isinstance(item, Mapping) or "Key" not in item or "Value" not in item:
                raise ValidationError("El inventario contiene etiquetas con formato inválido")
            key = str(item["Key"])
            if key in normalized:
                raise ValidationError("El inventario contiene etiquetas duplicadas")
            normalized[key] = str(item["Value"])
        return normalized
    raise ValidationError("Las etiquetas deben ser un objeto o una lista Key/Value")


def _load_inventory(path: Path) -> dict[str, Any]:
    """Lee el inventario local y exige un objeto JSON indexado por alias."""
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ValidationError(f"No existe el inventario: {path}") from error
    except (OSError, json.JSONDecodeError) as error:
        raise ValidationError("No se pudo leer el inventario JSON") from error
    if not isinstance(loaded, dict):
        raise ValidationError("El inventario debe ser un objeto JSON")
    return loaded


def _resolve_owned_resource(
    alias: str,
    inventory: dict[str, Any],
    group_id: str,
) -> tuple[str, str, dict[str, str]]:
    """Resuelve alias, tipo e ID y valida las etiquetas esperadas del grupo."""
    metadata = inventory.get(alias)
    if not isinstance(metadata, dict):
        raise ValidationError(f"El alias {alias!r} no existe en el inventario del grupo")

    resource_type = metadata.get("type")
    resource_id = metadata.get("id")
    if resource_type not in {"ec2", "s3"} or not isinstance(resource_id, str) or not resource_id:
        raise ValidationError(f"El inventario de {alias!r} no tiene type/id válidos")

    expected = _tags_to_dict(metadata.get("expected_tags"))
    required_expected = {
        **_REQUIRED_TAGS,
        "GroupId": group_id,
        "Owner": group_id,
    }
    for key, value in required_expected.items():
        if expected.get(key) != value:
            raise ValidationError(
                f"El inventario de {alias!r} no coincide con el GROUP_ID configurado"
            )
    return resource_type, resource_id, expected


def _assert_owned_tags(
    actual_tags: dict[str, str],
    group_id: str,
    *,
    owner_may_be_missing: bool = False,
) -> None:
    """Falla de forma segura si el recurso no demuestra pertenecer al grupo."""
    required = {**_REQUIRED_TAGS, "GroupId": group_id}
    for key, expected_value in required.items():
        if actual_tags.get(key) != expected_value:
            raise ValidationError(
                "Se rechazó la modificación: las etiquetas de propiedad no coinciden"
            )
    owner = actual_tags.get("Owner")
    if owner is None and owner_may_be_missing:
        return
    if owner != group_id:
        raise ValidationError(
            "Se rechazó la modificación: la etiqueta Owner no identifica al grupo"
        )


def inject_fault(
    resource_alias: str,
    *,
    inventory_path: str | Path = "data/inventory.json",
    client_factory: Callable[[str], Any] | None = None,
) -> dict[str, str]:
    """Provoca una falla de laboratorio sobre un alias inventariado y propio.

    Args:
        resource_alias: Alias permitido: `node-01` o `bucket-01`; nunca un ID cloud.
        inventory_path: Ruta al inventario generado por `setup-demo`.
        client_factory: Fábrica opcional de clientes Boto3, útil para pruebas unitarias.
    Returns:
        Diccionario con alias, recurso, acción y estado de la inyección.
    Raises:
        ValidationError: Ante alias ajeno, inventario inconsistente o falta de propiedad.
        BotoCoreError: Si Boto3/LocalStack rechaza o no puede completar la operación.
    Side Effects:
        Detiene la instancia propia o quita la etiqueta Owner del bucket propio.
        No termina instancias, no borra buckets y no elimina colas.
    """
    load_dotenv()
    group_id = os.environ.get("GROUP_ID", "").strip()
    if not group_id:
        raise ValidationError("Falta GROUP_ID en el entorno o en .env")

    inventory = _load_inventory(Path(inventory_path))
    resource_type, resource_id, _expected_tags = _resolve_owned_resource(
        resource_alias, inventory, group_id
    )

    if client_factory is None:
        from fenix.config.settings import client as client_factory  # Importa el guardián local.

    if resource_alias == "node-01" and resource_type == "ec2":
        ec2 = client_factory("ec2")
        response = ec2.describe_instances(InstanceIds=[resource_id])
        instances = [
            instance
            for reservation in response.get("Reservations", [])
            for instance in reservation.get("Instances", [])
        ]
        if len(instances) != 1 or instances[0].get("InstanceId") != resource_id:
            raise ValidationError("EC2 no devolvió exactamente la instancia inventariada")

        instance = instances[0]
        actual_tags = _tags_to_dict(instance.get("Tags", []))
        _assert_owned_tags(actual_tags, group_id)
        state = instance.get("State", {}).get("Name")
        if state == "stopped":
            status = "already_injected"
        elif state == "running":
            ec2.stop_instances(InstanceIds=[resource_id])
            status = "injected"
        else:
            raise ValidationError(f"No se detiene EC2 desde el estado {state!r}")
        return {
            "alias": resource_alias,
            "resource_id": resource_id,
            "action": "stop_instance",
            "status": status,
        }

    if resource_alias == "bucket-01" and resource_type == "s3":
        s3 = client_factory("s3")
        response = s3.get_bucket_tagging(Bucket=resource_id)
        tag_set = response.get("TagSet", [])
        actual_tags = _tags_to_dict(tag_set)
        _assert_owned_tags(actual_tags, group_id, owner_may_be_missing=True)

        if "Owner" not in actual_tags:
            status = "already_injected"
        else:
            # El resto de las etiquetas se conserva, incluidas las ajenas a la reparación.
            remaining = [
                {"Key": key, "Value": value}
                for key, value in actual_tags.items()
                if key != "Owner"
            ]
            s3.put_bucket_tagging(Bucket=resource_id, Tagging={"TagSet": remaining})
            status = "injected"
        return {
            "alias": resource_alias,
            "resource_id": resource_id,
            "action": "remove_owner_tag",
            "status": status,
        }

    raise ValidationError(
        f"El alias {resource_alias!r} no corresponde a un fault soportado por Fénix"
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Ejecuta la inyección desde la terminal y devuelve un código de salida."""
    parser = argparse.ArgumentParser(
        description="Provoca una falla controlada en un recurso propio de Fénix."
    )
    parser.add_argument(
        "resource_alias",
        choices=("node-01", "bucket-01"),
        help="Alias inventariado; no acepta IDs de AWS/LocalStack.",
    )
    parser.add_argument(
        "--inventory",
        default="data/inventory.json",
        help="Ruta al inventario del grupo (por defecto: data/inventory.json).",
    )
    args = parser.parse_args(argv)

    try:
        result = inject_fault(args.resource_alias, inventory_path=args.inventory)
    except (ValidationError, BotoCoreError, OSError, ValueError) as error:
        safe_error = {
            "status": "error",
            "error_type": type(error).__name__,
            "message": str(error),
        }
        print(json.dumps(safe_error, ensure_ascii=False), file=sys.stderr)
        return 1

    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
