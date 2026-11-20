"""Stub local de notificaciones para probar fallos sin enviar mensajes reales."""
from __future__ import annotations

from collections import deque
from typing import Any, Iterable

from fenix.utils.errors import PermanentError, RetryableError


class NotifyStub:
    """Callable que simula resultados `ok`, `429`, `timeout` o `permanent`.

    Ejemplo:
        notify = NotifyStub(["429", "ok"])
        # Primera llamada: RetryableError; segunda llamada: resultado exitoso.

    El stub no realiza llamadas HTTP ni imprime tokens, URLs o payloads.
    """

    def __init__(self, outcomes: Iterable[str] = ("ok",)) -> None:
        self._outcomes = deque(outcomes)
        self.calls = 0

    def __call__(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.calls += 1
        outcome = self._outcomes.popleft() if self._outcomes else "ok"
        if outcome == "429":
            raise RetryableError("Fallo de notificación simulado: HTTP 429")
        if outcome == "timeout":
            raise RetryableError("Fallo de notificación simulado: timeout")
        if outcome == "permanent":
            raise PermanentError("Fallo de notificación simulado: rechazo permanente")
        if outcome != "ok":
            raise ValueError(f"Resultado de stub desconocido: {outcome}")
        return {"ok": True, "simulated": True, "call": self.calls}
