import hashlib
import hmac
import time
from fenix.utils.errors import ValidationError

def signature(secret: str, timestamp: int, body: bytes) -> str:
    """Firma exactamente timestamp, punto y cuerpo binario original."""
    if len(secret) < 16:
        raise ValidationError("Configurar WEBHOOK_SECRET de 16 caracteres o más")
    signed = str(timestamp).encode("ascii") + b"." + body
    return hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()

def verify(secret: str, header: str, body: bytes, now: int | None = None) -> None:
    """Rechaza cabeceras ambiguas y firmas o fechas inválidas."""
    # 1. Separar por comas y validar que sean exactamente 2 partes (t y v1)
    parts = header.split(',')
    if len(parts) != 2:
        raise ValidationError("Cabecera inválida: formato incorrecto")
    
    # 2. Extraer t y v1
    try:
        t_part = parts[0].strip().split('=')
        v1_part = parts[1].strip().split('=')
        if t_part[0] != 't' or v1_part[0] != 'v1':
            raise ValueError
        timestamp_str = t_part[1]
        v1_hex = v1_part[1]
    except (IndexError, ValueError):
        raise ValidationError("Cabecera inválida: claves duplicadas o incorrectas")

    # 3. Validar timestamp
    try:
        timestamp = int(timestamp_str)
    except ValueError:
        raise ValidationError("Timestamp inválido: no es un entero")

    # 4. Validar firma hexadecimal de 64 caracteres
    if len(v1_hex) != 64 or not all(c in '0123456789abcdefABCDEF' for c in v1_hex):
        raise ValidationError("Firma inválida: no es hexadecimal de 64 caracteres")

    # 5. Validar ventana de tiempo (300 segundos máximo)
    current_time = int(time.time()) if now is None else now
    if abs(current_time - timestamp) > 300:
        raise ValidationError("Firma expirada: diferencia mayor a 300 segundos")

    # 6. Recalcular y comparar de forma segura
    expected_v1 = signature(secret, timestamp, body)
    if not hmac.compare_digest(expected_v1, v1_hex):
        raise ValidationError("Firma inválida: no coincide")
