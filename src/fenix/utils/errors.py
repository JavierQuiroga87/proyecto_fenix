"""Módulo de excepciones semánticas de dominio para el Proyecto Fénix.
Define la jerarquía estructurada de errores que heredan estrictamente
de Exception.
"""

from typing import Any, Optional

__all__ = [
    "ProjectError",
    "FenixError",
    "ValidationError",
    "RetryableError",
    "PermanentError",
    "SecurityError",
    "HMACVerificationError",
    "CloudProviderError",
    "SQSError",
    "SQSConnectionError",
    "RemediationError",
    "InventoryError",
    "NotificationError",
    "StateError",
]


class ProjectError(Exception):
    """Excepción raíz del Proyecto Fénix.

    Hereda directamente de Exception (nunca de BaseException) para no
    interferir con señales críticas del sistema operativo
    (KeyboardInterrupt, SystemExit).
    Permite capturar cualquier error controlado del dominio
    y cerrar con código 1.
    """

    def __init__(self, message: str, details: Optional[Any] = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details

    def __str__(self) -> str:
        if self.details:
            return f"{self.message} | Detalles: {self.details}"
        return self.message


# Alias semántico para compatibilidad de nomenclatura en el dominio Fénix
FenixError = ProjectError


class ValidationError(ProjectError):
    """Error de validación sintáctica, esquema o inventario.

    Se lanza ante:
    - Tipos incorrectos (ej. booleanos pasados como enteros).
    - Claves ausentes o claves adicionales no permitidas en el evento.
    - Tipos de evento (event_type) desconocidos.
    - Recursos (resource_id / alias) no registrados en inventory.json.
    - Formatos que violan expresiones regulares o estándares ISO 8601 UTC.
    """


class RetryableError(ProjectError):
    """Fallo transitorio que amerita reintento con backoff en SQS.

    Se lanza ante indisponibilidad temporal de servicios, timeouts recuperables
    o respuestas HTTP 429 / 5xx transitorias, permitiendo una nueva recepción
    del mensaje dentro de la ventana de visibilidad.
    """


class PermanentError(ProjectError):
    """Fallo no recuperable que no debe reintentarse indefinidamente.

    Se lanza ante eventos malformados, lógica irrecuperable o fallos que,
    tras agotar los reintentos (maxReceiveCount), deben derivarse a la DLQ.
    """


class SecurityError(PermanentError):
    """Excepción base para violaciones de seguridad o autenticación."""


class HMACVerificationError(SecurityError):
    """Firma HMAC ausente, malformada o inválida,
    o timestamp fuera de ventana."""


class CloudProviderError(ProjectError):
    """Fallo en operaciones contra APIs cloud (LocalStack / AWS)."""


class SQSError(CloudProviderError):
    """Errores generales en la interacción con el servicio de colas SQS."""


class SQSConnectionError(RetryableError, SQSError):
    """Fallo de conectividad o indisponibilidad en el endpoint de SQS."""


class RemediationError(CloudProviderError):
    """Fallo al ejecutar una acción de autorreparación sobre EC2 o S3."""


class InventoryError(ValidationError, CloudProviderError):
    """El recurso no existe en el inventario oficial autorizado."""


class NotificationError(ProjectError):
    """Fallo en el despacho de alertas externas hacia Telegram o Slack."""


class StateError(ProjectError):
    """Fallo en la persistencia o lectura atómica del ledger local."""
class TransientError(Exception):
    """Error temporal (ej. fallo de red). El mensaje se puede reintentar."""
    pass

class RemediationError(Exception):
    """Error permanente durante la reparación. No tiene sentido reintentar."""
    pass