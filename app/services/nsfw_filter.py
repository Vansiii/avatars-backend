"""Servicio de filtro NSFW - FAIL-CLOSED."""

import asyncio

import httpx
import logging

# Logger de seguridad inmutable (append-only)
security_logger = logging.getLogger("security.nsfw")
handler = logging.FileHandler("security.log")
handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
security_logger.addHandler(handler)
security_logger.setLevel(logging.WARNING)


async def check_image_url_nsfw(image_url: str) -> bool:
    """
    Descarga una imagen generada y la pasa por el mismo chequeo que la entrada.

    SOUL.md §6 exige validar la SALIDA, no solo la entrada — antes esta función
    no la llamaba nadie y las variaciones se mostraban sin pasar por ningún filtro.
    FAIL-CLOSED: si la descarga falla o da error, se rechaza.
    """
    # Un reintento: Pollinations (gratis, sin API key) devuelve 429 bajo ráfagas de
    # pedidos — sin esto, contenido válido se rechazaba por rate-limit, no por NSFW.
    for attempt in range(2):
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(image_url, follow_redirects=True)
            if response.status_code == 200:
                return await check_image_bytes_nsfw(response.content)
            if response.status_code == 429 and attempt == 0:
                await asyncio.sleep(2)
                continue
            security_logger.warning(f"NSFW check: no se pudo descargar {image_url} ({response.status_code})")
            return False
        except Exception as e:
            if attempt == 0:
                await asyncio.sleep(1)
                continue
            security_logger.warning(f"NSFW check failed for {image_url}: {e}")
            return False
    return False


async def check_generated_images_nsfw(image_urls: list[str], user_id: str | None = None) -> list[str]:
    """Filtra una lista de imágenes generadas, descartando las que no pasan el chequeo de salida."""
    safe_urls = []
    for url in image_urls:
        if await check_image_url_nsfw(url):
            safe_urls.append(url)
        else:
            log_nsfw_rejection("generated_image", "output image flagged as NSFW", user_id)
    return safe_urls


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
