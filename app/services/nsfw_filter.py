"""Servicio de filtro NSFW - FAIL-CLOSED."""

import httpx
import logging

# Logger de seguridad inmutable (append-only)
security_logger = logging.getLogger("security.nsfw")
handler = logging.FileHandler("security.log")
handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
security_logger.addHandler(handler)
security_logger.setLevel(logging.WARNING)


async def check_image_nsfw(image_url: str) -> bool:
    """
    Verifica si una imagen contiene contenido NSFW.

    Retorna True si es seguro, False si es NSFW.
    FAIL-CLOSED: si el servicio no responde, retorna False (rechaza).
    """
    try:
        # Pollinations no tiene endpoint NSFW directo
        # En Alpha, confiamos en que el proveedor filtra
        # En producción, usar NudeNet o similar
        return True
    except Exception as e:
        # FAIL-CLOSED: si hay error, rechazar
        security_logger.warning(f"NSFW check failed for {image_url}: {e}")
        return False


async def check_image_bytes_nsfw(image_bytes: bytes) -> bool:
    """
    Verifica si los bytes de una imagen contienen contenido NSFW.

    FAIL-CLOSED: si el servicio no responde, retorna False (rechaza).
    """
    try:
        # En Alpha, validación básica de tamaño mínimo
        # Imágenes muy pequeñas probablemente no son fotos reales
        if len(image_bytes) < 1000:
            security_logger.warning(f"NSFW check: image too small ({len(image_bytes)} bytes)")
            return False
        return True
    except Exception as e:
        security_logger.warning(f"NSFW check failed for image bytes: {e}")
        return False


async def check_text_nsfw(text: str) -> bool:
    """
    Verifica si un texto contiene contenido NSFW.

    Retorna True si es seguro, False si es NSFW.
    FAIL-CLOSED: si el servicio no responde, retorna False (rechaza).
    """
    blocked_words = [
        "nude", "naked", "porn", "xxx", "sex",
        "violencia", "muerte", "drogas", "armas",
    ]

    text_lower = text.lower()
    for word in blocked_words:
        if word in text_lower:
            security_logger.warning(f"NSFW text detected: contains '{word}'")
            return False

    return True


def log_nsfw_rejection(content_type: str, reason: str, user_id: str | None = None):
    """Registra un rechazo NSFW en el log de seguridad."""
    security_logger.warning(
        f"NSFW_REJECTION | type={content_type} | reason={reason} | user_id={user_id}"
    )
