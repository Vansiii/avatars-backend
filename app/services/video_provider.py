"""Servicio de HeyGen: identidad del personaje (avatar) y generación de video (API v3).

Reemplaza a Shotstack (motor de composición, sin movimiento real del personaje)
ahora que el usuario consiguió una API key de HeyGen (2026-07-20) — revierte la
decisión "Ninguno por ahora" del 2026-07-17 (ver HEARTBEAT.md/MEMORY.md).

HeyGen anima la identidad del personaje (avatar de HeyGen, o de respaldo la
imagen de referencia de personajes viejos — SOUL.md §4: la misma identidad se
usa en cada generación) con lip-sync real sobre el guión exacto — se eligió el
endpoint `type: "image"/"avatar"` de /v3/videos en vez del "Video Agent"
(/v3/video-agents) porque ese último trata el guión como un concepto a
elaborar creativamente (agrega escenas, reescribe texto), y un spot
publicitario necesita decir el guión aprobado tal cual.

Desde 2026-07-20 (segunda vuelta) la CREACIÓN del personaje también pasa por
HeyGen en vez de Pollinations: foto propia → avatar animable (`POST /v3/avatars`
type=photo), o elegir del catálogo público (`GET /v3/avatars/looks`). Ver
SOUL.md §4 y MEMORY.md para el porqué del giro.

Esquema verificado en vivo contra developers.heygen.com/reference/ antes de
implementar (CLAUDE.md: leer documentación oficial, no confiar en datos de
entrenamiento — la API de HeyGen tiene v1/v2/v3 y cambia rápido).
"""

import asyncio

import httpx

from app.config.settings import settings

BASE_URL = "https://api.heygen.com/v3"

# SOUL.md §5: corto 3-5s, largo 15-30s. HeyGen no fija una duración explícita
# para type=image — la marca el TTS del guión — así que esto queda solo como
# etiqueta aproximada para Spot.duration_seconds, no un límite duro real.
DURATION_SECONDS = {"short": 5, "long": 30}

_voice_id_cache: str | None = None
_voice_lock = asyncio.Lock()


def _headers() -> dict:
    return {"x-api-key": settings.HEYGEN_API_KEY, "Content-Type": "application/json"}


async def _resolve_voice_id(client: httpx.AsyncClient) -> str:
    """Voz en español a usar. `HEYGEN_VOICE_ID` manual tiene prioridad; si no,
    se descubre la primera voz en español del catálogo una vez por proceso
    (el catálogo no cambia en caliente, no vale la pena pedirlo cada spot).
    """
    global _voice_id_cache
    if settings.HEYGEN_VOICE_ID:
        return settings.HEYGEN_VOICE_ID
    if _voice_id_cache:
        return _voice_id_cache
    async with _voice_lock:
        if _voice_id_cache:
            return _voice_id_cache
        response = await client.get(
            f"{BASE_URL}/voices", params={"language": "Spanish", "limit": 1}, headers=_headers()
        )
        if response.status_code != 200:
            raise Exception(f"Error listando voces de HeyGen: {response.status_code} {response.text}")
        voices = response.json()["data"]
        if not voices:
            raise Exception("HeyGen no tiene ninguna voz en español disponible en el catálogo")
        _voice_id_cache = voices[0]["voice_id"]
        return _voice_id_cache


async def list_spanish_voices(limit: int = 12) -> list[dict]:
    """Catálogo de voces en español de HeyGen, para que el usuario elija la voz
    de su personaje (con preview de audio) en vez de que quede auto-asignada.
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{BASE_URL}/voices", params={"language": "Spanish", "limit": limit}, headers=_headers()
        )
    if response.status_code != 200:
        raise Exception(f"Error listando voces de HeyGen: {response.status_code} {response.text}")
    return [
        {
            "voice_id": v["voice_id"],
            "name": v["name"],
            "gender": v.get("gender"),
            "preview_audio_url": v.get("preview_audio_url"),
        }
        for v in response.json()["data"]
    ]


async def fetch_voice_preview(url: str) -> bytes:
    """Descarga el preview de audio de una voz desde el CDN de HeyGen.

    Se re-sirve desde el backend en vez de un `<audio src>` directo al CDN
    porque el Content-Type que devuelve HeyGen es inconsistente entre voces
    (a veces "binary/octet-stream" en vez de "audio/mpeg" aunque el archivo
    real sea el mismo MP3, tenga o no extensión .wav en la URL) — los
    navegadores no reproducen audio si el Content-Type no es de audio, así
    que el proxy siempre fija uno correcto.

    `url` se valida contra el dominio de HeyGen antes de pedirla — si no, el
    endpoint que llama a esto sería un proxy abierto a cualquier URL.
    """
    host = httpx.URL(url).host
    if not host or not host.endswith(".heygen.ai"):
        raise ValueError("URL de preview no pertenece a HeyGen")
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(url)
    if response.status_code != 200:
        raise Exception(f"Error descargando preview de voz: {response.status_code}")
    return response.content


async def create_avatar_from_photo(name: str, image_bytes: bytes, media_type: str) -> dict:
    """Crea un avatar animable de HeyGen a partir de una foto propia
    (`POST /v3/avatars` type=photo). A diferencia de Pollinations, esto es
    UN solo resultado determinístico por foto (no 3 variaciones) y consume
    crédito real de la cuenta — por eso no se persiste como Character acá,
    solo se devuelve el resultado para que el usuario confirme (ver
    `app/api/v1/characters.py: create-from-photo` + `confirm`).
    """
    import base64

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            f"{BASE_URL}/avatars",
            json={
                "type": "photo",
                "name": name,
                "file": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": base64.b64encode(image_bytes).decode("ascii"),
                },
            },
            headers=_headers(),
        )
        if response.status_code not in (200, 201):
            raise Exception(f"Error creando avatar en HeyGen: {response.status_code} {response.text}")
        data = response.json()["data"]
        avatar_id = data["avatar_item"]["id"]
        group_id = data["avatar_group"]["id"]

        # El avatar entrena en segundo plano ("processing" -> "completed"/"failed")
        # antes de poder usarse en un video. Se reusa el mismo endpoint de listar
        # looks (filtrado a este grupo) en vez de pedir uno nuevo para el polling.
        elapsed = 0
        timeout_seconds = 120
        while elapsed < timeout_seconds:
            looks_response = await client.get(
                f"{BASE_URL}/avatars/looks",
                params={"group_id": group_id, "ownership": "private"},
                headers=_headers(),
            )
            if looks_response.status_code != 200:
                raise Exception(
                    f"Error consultando estado del avatar en HeyGen: "
                    f"{looks_response.status_code} {looks_response.text}"
                )
            look = next(
                (item for item in looks_response.json()["data"] if item["id"] == avatar_id), None
            )
            if look is None:
                raise Exception(f"HeyGen no devolvió el look recién creado ({avatar_id})")
            if look["status"] == "completed":
                return {
                    "avatar_id": avatar_id,
                    "avatar_group_id": group_id,
                    "preview_image_url": look["preview_image_url"],
                }
            if look["status"] == "failed":
                raise Exception(f"HeyGen no pudo procesar la foto: {look.get('error')}")
            await asyncio.sleep(5)
            elapsed += 5

    raise Exception(f"Timeout esperando que HeyGen procese el avatar {avatar_id}")


async def list_public_avatar_looks(limit: int = 20, token: str | None = None) -> dict:
    """Catálogo público de avatares de HeyGen, para elegir uno ya existente
    en vez de crear uno nuevo desde una foto.
    """
    params = {"ownership": "public", "limit": limit}
    if token:
        params["token"] = token
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(f"{BASE_URL}/avatars/looks", params=params, headers=_headers())
    if response.status_code != 200:
        raise Exception(f"Error listando catálogo de HeyGen: {response.status_code} {response.text}")
    body = response.json()
    return {
        "items": [
            {
                "avatar_id": item["id"],
                "avatar_group_id": item["group_id"],
                "name": item["name"],
                "preview_image_url": item.get("preview_image_url"),
                "gender": item.get("gender"),
            }
            for item in body["data"]
        ],
        "next_token": body.get("next_token"),
    }


async def _submit_video(
    client: httpx.AsyncClient,
    script: str,
    voice_id: str,
    image_url: str | None = None,
    avatar_id: str | None = None,
) -> str:
    if avatar_id:
        payload = {"type": "avatar", "avatar_id": avatar_id, "script": script, "voice_id": voice_id}
    else:
        payload = {"type": "image", "image": {"type": "url", "url": image_url}, "script": script, "voice_id": voice_id}
    payload.update({"aspect_ratio": "16:9", "resolution": "720p"})
    response = await client.post(f"{BASE_URL}/videos", json=payload, headers=_headers())
    if response.status_code not in (200, 201):
        raise Exception(f"Error enviando video a HeyGen: {response.status_code} {response.text}")
    return response.json()["data"]["video_id"]


async def _poll_video(video_id: str, timeout_seconds: int = 900) -> str:
    """Espera a que HeyGen termine de animar el video. Lanza excepción si falla o hace timeout."""
    elapsed = 0
    async with httpx.AsyncClient(timeout=30.0) as client:
        while elapsed < timeout_seconds:
            response = await client.get(f"{BASE_URL}/videos/{video_id}", headers=_headers())
            if response.status_code != 200:
                raise Exception(f"Error consultando video {video_id} de HeyGen: {response.status_code} {response.text}")
            data = response.json()["data"]
            status = data["status"]
            if status == "completed":
                return data["video_url"]
            if status == "failed":
                raise Exception(f"HeyGen falló el video {video_id}: {data.get('failure_message')}")
            await asyncio.sleep(10)
            elapsed += 10
    raise Exception(f"Timeout esperando el video {video_id} de HeyGen")


async def generate_spot_variations(
    image_url: str | None,
    script: str,
    duration_type: str = "short",
    count: int = 3,
    voice_id: str | None = None,
    avatar_id: str | None = None,
) -> list[str]:
    """Genera variaciones del spot: misma identidad + mismo guión, `count` renders
    independientes de HeyGen enviados en paralelo y esperados en paralelo
    (evita triplicar el tiempo de espera del usuario, mismo patrón que antes).

    `avatar_id` (Character.heygen_avatar_id) tiene prioridad si está seteado
    — personajes creados por foto propia o catálogo de HeyGen. Si es None,
    cae a `image_url` (Character.reference_image_url) — personajes viejos
    creados antes de este cambio, que no tienen avatar_id.

    `voice_id`: la voz elegida por el usuario para ESTE personaje
    (Character.heygen_voice_id). Si es None (personaje sin voz elegida
    todavía), se auto-descubre una voz en español por defecto.

    `duration_type` se mantiene en la firma por compatibilidad con
    `app/api/v1/spots.py` aunque HeyGen no la use — ver nota de DURATION_SECONDS.
    ponytail: no se fuerza diferencia artificial entre variaciones (ni encuadre
    ni semilla) — cada render de HeyGen ya varía un poco por sí solo; si en la
    práctica salen demasiado parecidas, ahí se agrega variación explícita.
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        resolved_voice_id = voice_id or await _resolve_voice_id(client)
        video_ids = [
            await _submit_video(client, script, resolved_voice_id, image_url=image_url, avatar_id=avatar_id)
            for _ in range(count)
        ]

    return list(await asyncio.gather(*(_poll_video(vid) for vid in video_ids)))
