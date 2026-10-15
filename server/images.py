"""Обработка картинок: HEIC, EXIF-поворот, аватар 256×256."""
from __future__ import annotations

import io

from PIL import Image, ImageDraw, ImageOps

try:  # HEIC с iPhone
    from pillow_heif import register_heif_opener

    register_heif_opener()
    HEIF_OK = True
except Exception:  # noqa: BLE001
    HEIF_OK = False

AVATAR_SIZE = 256
PREVIEW_MAX = 1280


def open_upload(data: bytes) -> Image.Image:
    """Открыть загруженный файл (JPEG/PNG/HEIC/…) с учётом EXIF-поворота, в RGB."""
    img = Image.open(io.BytesIO(data))
    img = ImageOps.exif_transpose(img)
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGBA" if "A" in img.getbands() else "RGB")
    if img.mode == "RGBA":
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[3])
        img = bg
    return img


def make_preview(img: Image.Image) -> bytes:
    img = img.copy()
    img.thumbnail((PREVIEW_MAX, PREVIEW_MAX))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=88)
    return buf.getvalue()


def make_avatar(img: Image.Image, cx: float, cy: float, size: float) -> bytes:
    """Круглая обрезка. cx, cy, size в долях ширины/высоты превью (0..1 от меньшей стороны для size)."""
    w, h = img.size
    side = max(8.0, min(float(size), 1.0) * min(w, h))
    x0 = min(max(0.0, cx * w - side / 2), w - side)
    y0 = min(max(0.0, cy * h - side / 2), h - side)
    crop = img.crop((round(x0), round(y0), round(x0 + side), round(y0 + side)))
    crop = crop.resize((AVATAR_SIZE, AVATAR_SIZE), Image.LANCZOS).convert("RGBA")
    mask = Image.new("L", (AVATAR_SIZE * 4, AVATAR_SIZE * 4), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, AVATAR_SIZE * 4 - 1, AVATAR_SIZE * 4 - 1), fill=255)
    crop.putalpha(mask.resize((AVATAR_SIZE, AVATAR_SIZE), Image.LANCZOS))
    buf = io.BytesIO()
    crop.save(buf, "PNG", optimize=True)
    return buf.getvalue()
