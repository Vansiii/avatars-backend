"""Servicio de generación de video - Placeholder para Alpha."""

import httpx
from urllib.parse import quote


async def generate_video(prompt: str, duration: str = "short") -> str:
    """
    Genera un video usando Kling Omni via Luma API.

    Retorna la URL del video generado.
    """
    # Placeholder: en Alpha, retornamos una URL de demostración
    # La implementación real con Luma API se hará en Fase 003
    encoded_prompt = quote(prompt)
    # Por ahora, retornamos una URL que indica que el video está pendiente
    return f"https://placeholder-video.example.com/{encoded_prompt}"


async def generate_spot_variations(
    character_name: str,
    script: str,
    duration: str = "short",
    count: int = 3,
) -> list[str]:
    """
    Genera múltiples variaciones de un spot (video).

    Retorna una lista de URLs de videos.
    """
    variations = []
    for i in range(count):
        prompt = f"{character_name}: {script}"
        url = await generate_video(prompt, duration)
        variations.append(url)
    return variations
