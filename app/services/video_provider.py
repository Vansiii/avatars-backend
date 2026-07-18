"""Servicio de generación de video con Shotstack.

Shotstack es un motor de composición/render (timeline en JSON), no un
generador de IA: no sintetiza movimiento hiperrealista del personaje.
Decisión del usuario (2026-07-17, reemplaza el placeholder de Kling/Luma
que nunca se implementó): el spot se arma con la imagen ya aprobada del
personaje + narración TTS nativa de Shotstack (voz "Lupe", es-US, modo
newscaster) + subtítulos.

El usuario pidió después (mismo día) un avatar animado con movimiento real
("que interactúe a lo largo del video"). Eso requiere un proveedor de
foto-a-avatar-hablante (HeyGen, Hedra, D-ID, etc.) — servicio de pago nuevo,
fuera de lo que ya está contratado. El usuario eligió explícitamente NO
sumarlo todavía ("Ninguno por ahora"). Como alternativa sin proveedor nuevo,
el spot se arma como varios "planos" de la ÚNICA foto aprobada del personaje
(distinto encuadre vía crop + distinto movimiento de cámara por segmento,
con corte en fundido entre planos) en vez de un solo plano fijo — más
dinámico, sigue sin ser movimiento real del personaje.

Nota: se probó primero el TTS gratuito de Pollinations
(text.pollinations.ai?model=openai-audio) pero quedó deprecado — devuelve
404 "legacy API"; el reemplazo requiere cuenta/créditos de pago. El TTS de
Shotstack evita depender de un segundo proveedor.
"""

import asyncio

import httpx

from app.config.settings import settings

BASE_URLS = {
    "sandbox": "https://api.shotstack.io/edit/stage",
    "production": "https://api.shotstack.io/edit/v1",
}

# SOUL.md §5: corto 3-5s, largo 15-30s. Se usa el tope superior como duración
# fija del clip: si la narración real dura menos, el resto es silencio sobre
# la imagen; si dura más, se corta ahí — es el límite duro del producto.
DURATION_SECONDS = {"short": 5, "long": 30}

# Cuántos "planos" (segmentos) arma un spot — corto no da para más de 2 sin
# que cada uno quede demasiado breve para el fundido de transición.
SEGMENTS_PER_TYPE = {"short": 2, "long": 3}

# Efectos de cámara suaves (sin las variantes "Fast", se ven bruscas sobre
# una foto fija). Se combinan con SHOT_CROPS y se rotan por variación +
# segmento para que ninguna de las 3 variaciones del spot se vea igual.
CAMERA_EFFECTS = ["zoomIn", "zoomOutSlow", "slideLeftSlow", "slideRightSlow", "zoomInSlow", "slideUpSlow"]

# Recortes distintos sobre la misma foto para simular planos distintos
# (no hay una foto nueva por plano — es la única imagen de referencia
# aprobada del personaje, SOUL.md §4 exige usar siempre esa misma imagen).
SHOT_CROPS = [
    {},  # plano general
    {"bottom": 0.35},  # plano más cerrado
    {"top": 0.15, "bottom": 0.15},  # plano medio
]


def _script_chunks(script: str, count: int) -> list[str]:
    """Divide el guión en partes para que el subtítulo cambie junto con cada plano."""
    words = script.split()
    if len(words) < count:
        return [script] * count
    chunk_size = -(-len(words) // count)  # ceil division sin importar math
    return [" ".join(words[i * chunk_size:(i + 1) * chunk_size]) or script for i in range(count)]


def _base_url() -> str:
    return BASE_URLS.get(settings.SHOTSTACK_ENV, BASE_URLS["sandbox"])


def _api_key() -> str:
    if settings.SHOTSTACK_ENV == "production":
        return settings.SHOTSTACK_API_KEY_PRODUCTION
    return settings.SHOTSTACK_API_KEY_SANDBOX


def build_spot_edit(image_url: str, script: str, duration_type: str, variation_index: int) -> dict:
    """Arma el JSON de edición de Shotstack: varios planos de la misma foto
    (distinto encuadre + cámara por segmento, con fundido entre ellos) +
    narración TTS de un tirón + subtítulos sincronizados con cada plano.
    """
    total_length = DURATION_SECONDS.get(duration_type, DURATION_SECONDS["short"])
    segments = SEGMENTS_PER_TYPE.get(duration_type, 2)
    segment_length = total_length / segments
    captions = _script_chunks(script, segments)

    title_clips = []
    image_clips = []
    for i in range(segments):
        start = i * segment_length
        effect = CAMERA_EFFECTS[(variation_index + i) % len(CAMERA_EFFECTS)]
        crop = SHOT_CROPS[i % len(SHOT_CROPS)]
        transition = {}
        if i > 0:
            transition["in"] = "fade"
        if i < segments - 1:
            transition["out"] = "fade"

        title_clips.append({
            "asset": {"type": "title", "text": captions[i], "style": "minimal", "position": "bottom"},
            "start": start,
            "length": segment_length,
            **({"transition": transition} if transition else {}),
        })

        image_asset = {"type": "image", "src": image_url}
        if crop:
            image_asset["crop"] = crop
        image_clips.append({
            "asset": image_asset,
            "start": start,
            "length": segment_length,
            "effect": effect,
            "fit": "cover",
            **({"transition": transition} if transition else {}),
        })

    return {
        "timeline": {
            "tracks": [
                {"clips": title_clips},
                {
                    "clips": [
                        {
                            "asset": {
                                "type": "text-to-speech",
                                "text": script,
                                "voice": "Lupe",
                                "language": "es-US",
                                "newscaster": True,
                            },
                            "start": 0,
                            "length": total_length,
                        }
                    ]
                },
                {"clips": image_clips},
            ]
        },
        "output": {"format": "mp4", "resolution": "sd", "aspectRatio": "16:9"},
    }


async def _submit_render(edit: dict) -> str:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{_base_url()}/render",
            json=edit,
            headers={"x-api-key": _api_key(), "Content-Type": "application/json"},
        )
    if response.status_code not in (200, 201):
        raise Exception(f"Error enviando render a Shotstack: {response.status_code} {response.text}")
    return response.json()["response"]["id"]


async def _poll_render(render_id: str, timeout_seconds: int = 120) -> str:
    """Espera a que Shotstack termine el render. Lanza excepción si falla o hace timeout."""
    elapsed = 0
    async with httpx.AsyncClient(timeout=30.0) as client:
        while elapsed < timeout_seconds:
            response = await client.get(
                f"{_base_url()}/render/{render_id}",
                headers={"x-api-key": _api_key()},
            )
            data = response.json()["response"]
            status = data["status"]
            if status == "done":
                return data["url"]
            if status == "failed":
                raise Exception(f"Shotstack falló el render {render_id}: {data.get('error')}")
            await asyncio.sleep(3)
            elapsed += 3
    raise Exception(f"Timeout esperando el render {render_id} de Shotstack")


async def generate_spot_variations(
    image_url: str,
    script: str,
    duration_type: str = "short",
    count: int = 3,
) -> list[str]:
    """Genera variaciones del spot (mismo guión narrado, distinto efecto de cámara).

    Los 3 renders se envían primero y se esperan en paralelo, en vez de
    uno por uno, para no triplicar el tiempo de espera del usuario.
    """
    render_ids = []
    for i in range(count):
        edit = build_spot_edit(image_url, script, duration_type, variation_index=i)
        render_ids.append(await _submit_render(edit))

    return list(await asyncio.gather(*(_poll_render(rid) for rid in render_ids)))
