"""Servicio de generación de imágenes con Pollinations.ai."""

import httpx
import random
from urllib.parse import quote


async def generate_image(prompt: str) -> str:
    """
    Genera una imagen hiperrealista usando Pollinations.ai.

    Retorna la URL de la imagen generada.
    """
    encoded_prompt = quote(prompt)
    seed = random.randint(1, 100000)
    url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1024&height=1024&seed={seed}&nologo=true"

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.get(url, follow_redirects=True)
        if response.status_code == 200:
            return url
        else:
            raise Exception(f"Error generando imagen: {response.status_code}")


async def generate_character_variations(prompt: str, count: int = 3) -> list[str]:
    """
    Genera múltiples variaciones de un personaje.

    Usa semillas aleatorias y variaciones del prompt para obtener
    imágenes más distintas entre sí.
    """
    # Variaciones del prompt para generar imágenes más distintas
    style_suffixes = [
        ", cinematic lighting, sharp focus",
        ", soft natural lighting, warm tones",
        ", dramatic studio lighting, high contrast",
    ]

    variations = []
    for i in range(count):
        # Combinar prompt base con variación de estilo
        varied_prompt = prompt + style_suffixes[i % len(style_suffixes)]
        encoded_prompt = quote(varied_prompt)
        seed = random.randint(1, 100000)
        url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1024&height=1024&seed={seed}&nologo=true"
        variations.append(url)

    return variations


def build_character_prompt(
    name: str,
    description: str | None = None,
    category: str | None = None,
    reference_features: str | None = None,
) -> str:
    """
    Construye un prompt hiperrealista para generar un personaje.

    Combina nombre, descripción, categoría y rasgos de referencia.
    """
    parts = ["hyperrealistic portrait"]

    if reference_features:
        parts.append(reference_features)
    else:
        parts.append(f"of {name}")

    if description:
        parts.append(description)

    if category:
        category_map = {
            "deportes": "sports anchor in professional studio",
            "noticias": "news presenter in TV studio",
            "entretenimiento": "entertainment host on colorful set",
        }
        parts.append(category_map.get(category, "professional presenter"))

    return ", ".join(parts)
