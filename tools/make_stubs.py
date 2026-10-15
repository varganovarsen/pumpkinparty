"""Сгенерировать эталонные заглушки ассетов в server/stubs/ (SPEC раздел 12).

Нужны Pillow и ffmpeg (для mp3 и webm). Запускается разработчиком один раз,
результат лежит в репозитории. Сервер при старте копирует заглушки на место
отсутствующих файлов в assets/.

    python tools/make_stubs.py
"""
from __future__ import annotations

import math
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from server.assets import SFX  # noqa: E402

OUT = ROOT / "server" / "stubs"

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
]

ORANGE = (232, 118, 26)
DARK = (40, 22, 10)


def font(size: int) -> ImageFont.ImageFont:
    for p in FONT_CANDIDATES:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default(size)


def save(img: Image.Image, rel: str, **kw) -> None:
    p = OUT / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    img.save(p, **kw)


def label(draw: ImageDraw.ImageDraw, box, text: str, size: int, fill=(255, 255, 255)) -> None:
    f = font(size)
    x0, y0, x1, y1 = box
    l, t, r, b = draw.multiline_textbbox((0, 0), text, font=f, align="center")
    draw.multiline_text(((x0 + x1 - (r - l)) / 2 - l, (y0 + y1 - (b - t)) / 2 - t), text, font=f,
                        fill=fill, align="center")


def pumpkin(draw: ImageDraw.ImageDraw, cx, cy, r, color, stem=(70, 110, 40)) -> None:
    for dx in (-0.45, 0.45, 0):
        draw.ellipse((cx + dx * r - r * 0.7, cy - r * 0.8, cx + dx * r + r * 0.7, cy + r * 0.8),
                     fill=color, outline=tuple(max(0, c - 60) for c in color), width=max(1, int(r * 0.04)))
    draw.rectangle((cx - r * 0.1, cy - r * 1.05, cx + r * 0.1, cy - r * 0.7), fill=stem)


def avatars() -> None:
    hues = [(232, 118, 26), (240, 160, 40), (200, 80, 30), (250, 190, 60),
            (180, 100, 40), (220, 60, 50), (150, 170, 60), (240, 130, 90)]
    for i, c in enumerate(hues, 1):
        img = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.ellipse((4, 4, 252, 252), fill=(50, 30, 60, 255))
        pumpkin(d, 128, 140, 80, c)
        label(d, (0, 110, 256, 180), str(i), 64, fill=DARK)
        save(img, f"avatars/pumpkin-{i}.png")


def game() -> None:
    for name, color in (("pumpkin", ORANGE), ("golden", (250, 210, 50)), ("rotten", (100, 110, 60))):
        img = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        pumpkin(d, 64, 70, 46, color, stem=(60, 60, 40) if name == "rotten" else (70, 110, 40))
        if name == "rotten":
            for x, y in ((50, 60), (78, 80), (60, 90)):
                d.ellipse((x - 6, y - 6, x + 6, y + 6), fill=(50, 50, 30))
        save(img, f"game/{name}.png")
    img = Image.new("RGBA", (256, 128), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.polygon([(10, 30), (246, 30), (215, 120), (41, 120)], fill=(150, 95, 45), outline=(90, 55, 20))
    for y in range(45, 120, 18):
        d.line([(20, y), (236, y)], fill=(110, 70, 30), width=3)
    save(img, "game/basket.png")


def stickers() -> None:
    for i, (text, color) in enumerate((("BOO!", (255, 255, 255)), ("🎃", ORANGE), ("2026", (250, 210, 50))), 1):
        img = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.ellipse((8, 8, 248, 248), fill=(60, 20, 70, 230))
        label(d, (0, 0, 256, 256), f"STUB\n{text if i != 2 else 'тыква'}", 54, fill=color)
        save(img, f"stickers/stub-{i}.png")


def backgrounds() -> None:
    w, h = 1920, 1080
    img = Image.new("RGB", (w, h))
    px = img.load()
    for y in range(h):
        t = y / h
        for x in range(0, w):
            g = 0.5 + 0.5 * math.sin(x / w * math.pi)
            px[x, y] = (int(30 + 60 * t * g), int(15 + 25 * t * g), int(25 + 10 * (1 - t)))
    d = ImageDraw.Draw(img)
    label(d, (0, 0, w, h), "ЗАГЛУШКА · ambient-light.jpg", 40, fill=(120, 80, 60))
    save(img, "img/ambient-light.jpg", quality=85)


def final_frame() -> None:
    w, h, b = 3000, 2250, 110
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, w, h), outline=(232, 118, 26, 255), width=b)
    d.rectangle((b, h - 330, w - b, h - b), fill=(30, 15, 10, 200))
    label(d, (b, h - 330, w - b, h - b), "Тыквенный спас 2026", 130, fill=(255, 200, 120, 255))
    save(img, "overlay/final-frame.png", optimize=True)


def riv() -> None:
    p = OUT / "rive" / "head.riv"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"STUB: not a Rive file. /tv uses the CSS fallback head.\n")


def ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


def sounds() -> None:
    (OUT / "sfx").mkdir(parents=True, exist_ok=True)
    for i, name in enumerate(SFX):
        freq = 330 + i * 55
        dur = 0.08 if name == "warning-tick" else 0.25
        ffmpeg("-f", "lavfi", "-i", f"sine=frequency={freq}:duration={dur}",
               "-af", f"afade=t=out:st={dur * 0.6}:d={dur * 0.4}",
               "-ac", "1", "-ar", "44100", "-c:a", "libmp3lame", "-b:a", "64k", str(OUT / "sfx" / f"{name}.mp3"))


def video() -> None:
    (OUT / "video").mkdir(parents=True, exist_ok=True)
    src = ("gradients=s=960x540:c0=0x2a1206:c1=0x6b2a08:c2=0x1a0c14:nb_colors=3:speed=0.02:duration=8:rate=30")
    ffmpeg("-f", "lavfi", "-i", src, "-vf", "format=yuv420p",
           "-c:v", "libvpx-vp9", "-b:v", "150k", "-an", str(OUT / "video" / "ambient.webm"))


def main() -> None:
    if not shutil.which("ffmpeg"):
        sys.exit("Нужен ffmpeg (для mp3 и webm)")
    avatars()
    game()
    stickers()
    backgrounds()
    final_frame()
    riv()
    sounds()
    video()
    print(f"Заглушки записаны в {OUT}")


if __name__ == "__main__":
    main()
