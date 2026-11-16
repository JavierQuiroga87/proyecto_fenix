"""Contrato de eventos de autorreparación para el Proyecto Fénix.

Responsabilidad: Integrante 1 (Ingeniero de Entradas, Excepciones y Validación).
Valida estrictamente el contrato JSON cerrado de los eventos y verifica
la existencia y compatibilidad del recurso contra el inventario oficial.
"""

from copy import deepcopy
import json
from pathlib import Path
from typing import Any, Optional

from fenix.utils.errors import ValidationError, InventoryError
from fenix.utils.validation import identifier, utc_text

__all__ = ["validate", "REQUIRED_FIELDS", "ALLOWED_EVENT_TYPES"]

# Contrato cerrado: exactamente estas 6 claves obligatorias, ninguna más, ninguna menos.
REQUIRED_FIELDS = frozenset({
    "schema_version",
    "event_id",
    "event_type",
    "resource_id",
    "occurred_at",
    "simulate_failures",
})

# Tipos de eventos admitidos en el dominio Fénix
ALLOWED_EVENT_TYPES = frozenset({
    "instance.stopped",
    "bucket.tags_missing",
})

# Inventario por defecto con los recursos oficiales del laboratorio
_DEFAULT_FALLBACK_INVENTORY = {
    "node-01": {"type": "ec2"},
    "bucket-01": {"type": "s3"},
}


def _resolve_inventory(inventory: Optional[Any]) -> dict[str, Any]:
    """Resuelve y carga el inventario desde un dict, Path o ruta de archivo por defecto."""
    if inventory is not None:
        if isinstance(inventory, dict):
            return inventory
        if isinstance(inventory, (str, Path)):
            inv_path = Path(inventory)
            if not inv_path.exists():
                raise ValidationError(f"El archivo de inventario '{inventory}' no existe.")
            try:
                content = json.loads(inv_path.read_text(encoding="utf-8"))
                if not isinstance(content, dict):
                    raise ValidationError("El archivo de inventario debe contener un objeto JSON (dict).")
                return content
            except json.JSONDecodeError as err:
                raise ValidationError(f"Error al decodificar el inventario JSON: {err}") from err
        raise ValidationError(f"Tipo de inventario inválido: {type(inventory).__name__}. Se esperaba dict o Path.")

    # Si no se pasó inventario, buscar data/inventory.json
    default_path = Path("data/inventory.json")
    if default_path.exists():
        try:
            content = json.loads(default_path.read_text(encoding="utf-8"))
            if isinstance(content, dict):
                return content
        except (OSError, json.JSONDecodeError):
            pass

    # Fallback seguro a los recursos oficiales de la cátedra
    return _DEFAULT_FALLBACK_INVENTORY


def validate(
    event: Any,
    inventory: Optional[Any] = None,
) -> dict[str, Any]:
    """Valida exhaustivamente un evento de autorreparación contra el contrato cerrado y el inventario.

    Reglas de validación (Cátedra PPA-2 - Integrante 1):
    1. El evento debe ser un objeto JSON (dict). Se rechazan listas, primitivos o None.
    2. Contrato cerrado: debe contener exactamente los 6 campos requeridos sin campos extra ni faltantes.
    3. schema_version: debe ser el entero 1 (nunca booleano).
    4. event_id: debe cumplir con la expresión regular '^[a-z0-9-]{3,32}$'.
    5. resource_id: debe cumplir con '^[a-z0-9-]{3,32}$' y existir en el inventario oficial.
    6. event_type: solo admite 'instance.stopped' o 'bucket.tags_missing'.
    7. Compatibilidad de tipo:
       - 'instance.stopped' solo es válido para recursos de tipo 'ec2' (ej. node-01).
       - 'bucket.tags_missing' solo es válido para recursos de tipo 's3' (ej. bucket-01).
    8. occurred_at: marca de tiempo en formato ISO 8601 con zona UTC explícita.
    9. simulate_failures: entero entre 0 y 5 (nunca booleano).

    Args:
        event: Diccionario con el evento recibido.
        inventory: Diccionario, ruta a archivo o None para resolver inventario.

    Returns:
        dict[str, Any]: Copia íntegra y validada del evento.

    Raises:
        ValidationError: Ante cualquier incumplimiento del esquema, tipos, claves o inventario.
    """
    # 1. Validación del tipo raíz: Prohibido listas o primitivos
    if not isinstance(event, dict):
        raise ValidationError(
            f"El evento debe ser un objeto JSON (dict), se recibió: {type(event).__name__}. "
            "Las listas JSON y tipos primitivos están expresamente prohibidos."
        )

    # 2. Contrato cerrado: Detección estricta de claves faltantes o adicionales
    event_keys = set(event.keys())
    missing_keys = REQUIRED_FIELDS - event_keys
    if missing_keys:
        raise ValidationError(
            f"Contrato JSON incompleto. Faltan claves obligatorias: {sorted(missing_keys)}"
        )

    extra_keys = event_keys - REQUIRED_FIELDS
    if extra_keys:
        raise ValidationError(
            f"Contrato JSON cerrado violado. Claves adicionales no permitidas: {sorted(extra_keys)}"
        )

    # 3. schema_version: Entero 1 estricto (rechazar bool)
    schema_ver = event["schema_version"]
    if isinstance(schema_ver, bool) or not isinstance(schema_ver, int):
        raise ValidationError(
            f"schema_version debe ser un entero (int), recibido: {type(schema_ver).__name__}"
        )
    if schema_ver != 1:
        raise ValidationError(
            f"schema_version no soportada: {schema_ver}. Solo se admite la versión 1."
        )

    # 4. event_id: Validación con validador de identificadores
    identifier(event["event_id"])

    # 5. resource_id: Sintaxis de identificador
    res_id = identifier(event["resource_id"])

    # 6. event_type: Tipos permitidos
    event_type = event["event_type"]
    if not isinstance(event_type, str):
        raise ValidationError(
            f"event_type debe ser una cadena (str), recibido: {type(event_type).__name__}"
        )
    if event_type not in ALLOWED_EVENT_TYPES:
        raise ValidationError(
            f"event_type desconocido: '{event_type}'. Solo se admite: {sorted(ALLOWED_EVENT_TYPES)}"
        )

    # 7. occurred_at: Marca ISO 8601 UTC estricta
    utc_text(event["occurred_at"])

    # 8. simulate_failures: Entero entre 0 y 5 (rechazar bool)
    sim_failures = event["simulate_failures"]
    if isinstance(sim_failures, bool) or not isinstance(sim_failures, int):
        raise ValidationError(
            f"simulate_failures debe ser un entero (int), recibido: {type(sim_failures).__name__}"
        )
    if sim_failures < 0 or sim_failures > 5:
        raise ValidationError(
            f"simulate_failures debe ser un entero entre 0 y 5, recibido: {sim_failures}"
        )

    # 9. Validación contra Inventario y compatibilidad de recurso
    inv_data = _resolve_inventory(inventory)
    if res_id not in inv_data:
        raise InventoryError(
            f"El recurso '{res_id}' no pertenece al inventario oficial del grupo. "
            "Se prohíbe reparar recursos ajenos o no registrados."
        )

    res_meta = inv_data[res_id]
    res_type = res_meta.get("type") if isinstance(res_meta, dict) else None

    # Si se conoce el tipo de recurso en el inventario, validar coherencia con el evento
    if res_type == "ec2" and event_type != "instance.stopped":
        raise ValidationError(
            f"Incompatibilidad de evento: el recurso '{res_id}' es de tipo EC2 "
            f"y no admite el evento '{event_type}' (se esperaba 'instance.stopped')."
        )
    if res_type == "s3" and event_type != "bucket.tags_missing":
        raise ValidationError(
            f"Incompatibilidad de evento: el recurso '{res_id}' es de tipo S3 "
            f"y no admite el evento '{event_type}' (se esperaba 'bucket.tags_missing')."
        )

    # Retornar una copia validada para evitar mutaciones externas
    return deepcopy(event)
