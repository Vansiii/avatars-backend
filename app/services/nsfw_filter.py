"""
Filtro NSFW para validación de contenido de imágenes.

Cumple con SOUL.md §4: filtro obligatorio en entrada Y salida.
Este módulo maneja la validación de SALIDA (imágenes ya generadas).
"""

from io import BytesIO
from typing import Literal

from nudenet import NudeDetector
from PIL import Image


class NSFWFilterError(Exception):
    """Excepción cuando el filtro NSFW no puede procesar la imagen."""
    pass


class ContentRejected(Exception):
    """Excepción cuando el contenido es rechazado por el filtro NSFW."""
    pass


# Inicializar detector (se carga una sola vez al importar el módulo)
# El modelo se descarga automáticamente la primera vez (~50MB)
_detector: NudeDetector | None = None


def _get_detector() -> NudeDetector:
    """Obtiene o inicializa el detector de NudeNet (lazy loading)."""
    global _detector
    if _detector is None:
        _detector = NudeDetector()
    return _detector


def strip_image_metadata(image_bytes: bytes) -> bytes:
    """
    Elimina todos los metadatos EXIF de una imagen.
    
    Los metadatos EXIF pueden contener información sensible como:
    - Geolocalización (GPS coordinates)
    - Fecha y hora de captura
    - Modelo de cámara/teléfono
    - Software de edición usado
    
    Cumple con SOUL.md §5: privacidad de datos del usuario.
    
    Args:
        image_bytes: Imagen en bytes (cualquier formato)
    
    Returns:
        Imagen sin metadatos EXIF en bytes
    
    Raises:
        Exception: Si no puede procesar la imagen
    """
    try:
        # Abrir imagen
        image = Image.open(BytesIO(image_bytes))
        
        # Crear nueva imagen sin EXIF
        # Convertir a RGB si es necesario (algunos formatos tienen problemas)
        if image.mode not in ("RGB", "L"):
            image = image.convert("RGB")
        
        # Guardar sin metadatos
        output = BytesIO()
        image.save(output, format="JPEG", quality=95, exif=b"")
        
        return output.getvalue()
    
    except Exception as exc:
        raise Exception(f"Error al eliminar metadatos EXIF: {exc}")


def validate_image_content(
    image_bytes: bytes,
    threshold: float = 0.6,
    mode: Literal["strict", "moderate"] = "moderate"
) -> bool:
    """
    Valida que una imagen no contenga contenido NSFW.

    Args:
        image_bytes: Imagen en bytes (cualquier formato soportado por PIL)
        threshold: Umbral de confianza para rechazar (0.0 a 1.0)
        mode: 
            - "strict": rechaza cualquier detección NSFW
            - "moderate": solo rechaza detecciones explícitas con alta confianza

    Returns:
        True si la imagen es segura, False si debe rechazarse

    Raises:
        NSFWFilterError: Si el filtro falla al procesar la imagen
        ContentRejected: Si el contenido es rechazado
    """
    import tempfile
    import os
    
    try:
        # Convertir bytes a PIL Image
        image = Image.open(BytesIO(image_bytes))
        
        # Convertir a RGB si es necesario (NudeNet no procesa RGBA)
        if image.mode != "RGB":
            image = image.convert("RGB")
        
        # NudeNet requiere un path de archivo real, no BytesIO
        # Crear archivo temporal
        with tempfile.NamedTemporaryFile(mode='wb', suffix='.jpg', delete=False) as tmp_file:
            image.save(tmp_file, format="JPEG")
            tmp_path = tmp_file.name
        
        try:
            # Detectar contenido NSFW usando el path temporal
            detector = _get_detector()
            detections = detector.detect(tmp_path)
        finally:
            # Limpiar archivo temporal
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        
        # Analizar detecciones
        if not detections:
            return True  # Sin detecciones = imagen segura
        
        # Categorías consideradas NSFW explícito
        explicit_categories = {
            "EXPOSED_ANUS",
            "EXPOSED_BREAST_F",
            "EXPOSED_GENITALIA_F",
            "EXPOSED_GENITALIA_M",
        }
        
        # Categorías consideradas sugestivas (solo en modo strict)
        suggestive_categories = {
            "FEMALE_BREAST_EXPOSED",
            "FEMALE_GENITALIA_EXPOSED",
            "MALE_GENITALIA_EXPOSED",
            "BUTTOCKS_EXPOSED",
        }
        
        for detection in detections:
            label = detection.get("class", "")
            score = detection.get("score", 0.0)
            
            # Modo strict: rechazar cualquier contenido sugestivo o explícito
            if mode == "strict":
                if label in explicit_categories and score >= threshold:
                    raise ContentRejected(
                        f"Contenido explícito detectado: {label} (confianza: {score:.2f})"
                    )
                if label in suggestive_categories and score >= threshold * 1.2:
                    raise ContentRejected(
                        f"Contenido sugestivo detectado: {label} (confianza: {score:.2f})"
                    )
            
            # Modo moderate: solo rechazar contenido explícito con alta confianza
            else:
                if label in explicit_categories and score >= threshold:
                    raise ContentRejected(
                        f"Contenido inapropiado detectado (confianza: {score:.2f})"
                    )
        
        return True  # Ninguna detección superó los umbrales
    
    except ContentRejected:
        raise  # Re-lanzar para que el llamador lo maneje
    
    except Exception as exc:
        # Cualquier error del filtro se trata como fallo del sistema
        # SOUL.md §4: "El fallo del filtro se resuelve rechazando"
        raise NSFWFilterError(f"Error al procesar imagen con filtro NSFW: {exc}")


def validate_batch_content(
    images_bytes: list[bytes],
    threshold: float = 0.6,
    mode: Literal["strict", "moderate"] = "moderate"
) -> tuple[list[bool], list[str]]:
    """
    Valida un lote de imágenes.

    Args:
        images_bytes: Lista de imágenes en bytes
        threshold: Umbral de confianza
        mode: Modo de validación

    Returns:
        Tupla de (resultados, razones):
        - resultados: lista de bool (True = segura, False = rechazada)
        - razones: lista de str con razón del rechazo (vacío si es segura)
    """
    results = []
    reasons = []
    
    for img_bytes in images_bytes:
        try:
            validate_image_content(img_bytes, threshold, mode)
            results.append(True)
            reasons.append("")
        except ContentRejected as exc:
            results.append(False)
            reasons.append(str(exc))
        except NSFWFilterError as exc:
            # Fallo del filtro = rechazar (fail-closed)
            results.append(False)
            reasons.append(str(exc))
    
    return results, reasons
