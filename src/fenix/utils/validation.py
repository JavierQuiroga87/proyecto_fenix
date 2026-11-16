"""Módulo de validación y sanitización de datos para el Proyecto Fénix.

Contiene validadores estrictos y puros para identificadores de recursos/eventos,
marcas temporales en formato ISO 8601 UTC y tiempos de vida (TTL),
cumpliendo con los contratos de la cátedra para el Integrante 1.
"""

from datetime import datetime, timezone
import re
from typing import Any

from fenix.utils.errors import ValidationError

__all__ = ["identifier", "ttl_seconds", "utc_text"]

# Expresión regular oficial: 3 a 32 caracteres, alfanumérico en minúsculas y guiones medios.
_IDENTIFIER_PATTERN = re.compile(r"^[a-z0-9-]{3,32}$")


def identifier(value: Any) -> str:
    """Valida que un identificador (event_id o resource_id/alias) cumpla el contrato de dominio.

    Reglas:
    - Debe ser una cadena de texto (str).
    - Longitud entre 3 y 32 caracteres.
    - Contener únicamente letras minúsculas (a-z), dígitos (0-9) y guiones medios (-).

    Args:
        value: Cadena con el identificador a validar.

    Returns:
        str: El identificador validado.

    Raises:
        ValidationError: Si el valor no es string o no cumple con el patrón '^[a-z0-9-]{3,32}$'.
    """
    if not isinstance(value, str):
        raise ValidationError(
            f"El identificador debe ser una cadena de texto (str), se recibió: {type(value).__name__}"
        )

    if not _IDENTIFIER_PATTERN.match(value):
        raise ValidationError(
            f"El identificador '{value}' es inválido. Debe cumplir con el patrón "
            f"'^[a-z0-9-]{{3,32}}$' (3 a 32 caracteres en minúsculas, números o guiones medios)."
        )

    return value


def ttl_seconds(value: Any) -> int:
    """Valida y normaliza un valor a segundos de tiempo de vida (TTL).

    Práctica común de validación para entornos efímeros o colas con retención.
    Rechaza explícitamente booleanos, números con decimales (float / redondeos)
    y cadenas no compuestas exclusivamente por dígitos enteros positivos.

    Reglas de la cátedra (test_ttl_contract):
    - Rango permitido: entre 60 y 600 segundos (inclusive).
    - Rechaza booleanos (bool como entero prohibido).
    - Rechaza números flotantes o decimales (no se redondean entradas).
    - Rechaza cadenas no compuestas estrictamente por dígitos enteros.

    Args:
        value: Valor entero o texto numérico que representa segundos de TTL.

    Returns:
        int: Número entero de segundos validado (60 <= val <= 600).

    Raises:
        ValidationError: Si es bool, float, no numérico o fuera del rango [1].
    """
    if isinstance(value, bool):
        raise ValidationError("El valor de TTL no puede ser un booleano (bool como entero rechazado).")

    if isinstance(value, float):
        raise ValidationError("No se redondean entradas: el TTL debe ser un entero exacto (float rechazado).")

    if isinstance(value, str):
        clean_val = value.strip()
        if not clean_val.isdigit():
            raise ValidationError(
                f"El valor de TTL '{value}' no es un entero válido (no se permiten decimales ni texto no numérico)."
            )
        val = int(clean_val)
    elif isinstance(value, int):
        val = value
    else:
        raise ValidationError(
            f"Tipo no soportado para TTL: {type(value).__name__}. Se esperaba int o str de dígitos."
        )

    if val < 60 or val > 600:
        raise ValidationError(f"El TTL debe estar entre 60 y 600 segundos (recibido: {val}).")

    return val


def utc_text(value: Any) -> datetime:
    """Valida e interpreta una marca de tiempo en formato estándar ISO 8601 con zona UTC explícita.

    Exigido para campos como occurred_at en eventos de autorreparación.

    Reglas:
    - Debe ser una cadena de texto (str).
    - Debe cumplir con el formato ISO 8601 (ej. '2026-10-22T18:00:00Z' o '2026-10-22T18:00:00+00:00').
    - Debe tener zona horaria explícita (no se admiten fechas naive).
    - La zona horaria debe ser estrictamente UTC (offset de 0 segundos).

    Args:
        value: Cadena de texto con la fecha y hora a validar.

    Returns:
        datetime: Objeto datetime consciente de zona horaria en UTC.

    Raises:
        ValidationError: Si el valor no es string, está malformado, carece de zona horaria
                         o no tiene offset UTC (+00:00).
    """
    if not isinstance(value, str):
        raise ValidationError(
            f"La marca de tiempo debe ser una cadena de texto (str), se recibió: {type(value).__name__}"
        )

    clean_val = value.strip()
    if not clean_val:
        raise ValidationError("La marca de tiempo no puede ser una cadena vacía.")

    try:
        # Python 3.11+ interpreta nativamente terminaciones en 'Z' y offsets '+00:00'
        parsed_dt = datetime.fromisoformat(clean_val)
    except (ValueError, TypeError) as err:
        raise ValidationError(
            f"Formato ISO 8601 inválido en la marca de tiempo '{value}': {err}"
        ) from err

    if parsed_dt.tzinfo is None or parsed_dt.utcoffset() is None:
        raise ValidationError(
            f"La marca de tiempo '{value}' carece de zona horaria. Debe incluir UTC explícito (ej. 'Z' o '+00:00')."
        )

    if parsed_dt.utcoffset() != timezone.utc.utcoffset(parsed_dt):
        raise ValidationError(
            f"La marca de tiempo '{value}' tiene un desplazamiento no UTC ({parsed_dt.tzinfo}). "
            f"Debe tener offset cero (+00:00 / UTC)."
        )

    return parsed_dt
