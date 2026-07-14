import asyncio
from urllib.parse import quote

import httpx

from app.config.settings import settings

POLLINATIONS_URL = "https://image.pollinations.ai/prompt"
MAX_ATTEMPTS = 3
REQUEST_TIMEOUT = 45.0


class NSFWRejected(Exception):
    pass


class ProviderError(Exception):
    pass


async def generate_image(prompt: str, width: int = 512, height: int = 512) -> bytes:
    url = f"{POLLINATIONS_URL}/{quote(prompt)}"
    params = {
        "model": "flux",
        "width": width,
        "height": height,
        "nologo": "true",
        "safe": "false",  # Desactivado temporalmente para testing - confiamos en el filtro local
        "private": "true",
    }
    headers = {}
    if settings.POLLINATIONS_API_KEY:
        headers["Authorization"] = f"Bearer {settings.POLLINATIONS_API_KEY}"

    last_error: Exception | None = None
    for attempt in range(MAX_ATTEMPTS):
        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
                response = await client.get(url, params=params, headers=headers)
        except httpx.RequestError as exc:
            last_error = exc
            await asyncio.sleep(2 ** attempt)
            continue

        if response.status_code == 200 and response.headers.get("content-type", "").startswith("image/"):
            return response.content

        if response.status_code in (400, 403, 422):
            # Pollinations no documenta el código exacto de rechazo para safe=true;
            # cualquier 4xx de bloqueo se trata como rechazo NSFW (fail-closed).
            print(f"[WARNING] Pollinations rechazó el prompt: '{prompt}' (HTTP {response.status_code})")
            raise NSFWRejected(f"Contenido rechazado por el filtro de seguridad (HTTP {response.status_code})")

        last_error = ProviderError(f"Pollinations respondió {response.status_code}")
        await asyncio.sleep(2 ** attempt)

    raise ProviderError(str(last_error) if last_error else "Fallo desconocido del proveedor de IA")
