"""Servicio de consistencia de personajes."""


def get_character_reference(character_data: dict) -> str | None:
    """
    Obtiene la imagen de referencia de un personaje.

    La imagen de referencia se usa para mantener consistencia
    en todas las generaciones de video del mismo personaje.
    """
    return character_data.get("reference_image_url")


def build_video_prompt(character_name: str, script: str, reference_url: str | None = None) -> str:
    """
    Construye un prompt para generar video con un personaje.

    Incluye la imagen de referencia para mantener consistencia.
    """
    parts = [f"hyperrealistic video of {character_name}"]

    if script:
        parts.append(f"doing: {script}")

    parts.append("professional studio lighting, high quality, 4k")

    return ", ".join(parts)
