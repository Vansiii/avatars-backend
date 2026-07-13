from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

WATERMARK_TEXT = "ProyectoIA · Alpha"


def apply_watermark(image_bytes: bytes) -> bytes:
    image = Image.open(BytesIO(image_bytes)).convert("RGBA")
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    font_size = max(16, image.width // 18)
    try:
        font = ImageFont.truetype("arial.ttf", font_size)
    except OSError:
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), WATERMARK_TEXT, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    margin = max(8, image.width // 40)
    position = (image.width - text_width - margin, image.height - text_height - margin)

    draw.text((position[0] + 1, position[1] + 1), WATERMARK_TEXT, font=font, fill=(0, 0, 0, 120))
    draw.text(position, WATERMARK_TEXT, font=font, fill=(255, 255, 255, 180))

    watermarked = Image.alpha_composite(image, overlay).convert("RGB")
    output = BytesIO()
    watermarked.save(output, format="PNG")
    return output.getvalue()
