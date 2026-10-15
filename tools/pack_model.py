"""Упаковать glTF (scene.gltf + scene.bin + textures/) в один assets/carve/pumpkin.glb.

    python tools/pack_model.py <папка с scene.gltf> [assets/carve/pumpkin.glb]

Цветовая текстура пережимается в JPEG (q90), остальные картинки остаются как есть.
Геометрия и развёртка не меняются. Требования к модели для резьбы: docs/DECISIONS.md.
"""
from __future__ import annotations

import io
import json
import struct
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent


def pad4(b: bytes, fill: bytes = b"\0") -> bytes:
    return b + fill * (-len(b) % 4)


def main() -> None:
    src = Path(sys.argv[1])
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "assets" / "carve" / "pumpkin.glb"
    gltf = json.loads((src / "scene.gltf").read_text(encoding="utf-8"))
    if len(gltf.get("buffers", [])) != 1:
        sys.exit("Ожидается один буфер (scene.bin)")
    binary = bytearray((src / gltf["buffers"][0]["uri"]).read_bytes())
    binary = bytearray(pad4(bytes(binary)))

    color_images = set()
    for m in gltf.get("materials", []):
        tex = m.get("pbrMetallicRoughness", {}).get("baseColorTexture")
        if tex is not None:
            color_images.add(gltf["textures"][tex["index"]]["source"])

    for i, img in enumerate(gltf.get("images", [])):
        path = src / img.pop("uri")
        data, mime = path.read_bytes(), "image/png"
        if i in color_images:
            buf = io.BytesIO()
            Image.open(path).convert("RGB").save(buf, "JPEG", quality=90)
            data, mime = buf.getvalue(), "image/jpeg"
        gltf["bufferViews"].append({"buffer": 0, "byteOffset": len(binary), "byteLength": len(data)})
        img["bufferView"] = len(gltf["bufferViews"]) - 1
        img["mimeType"] = mime
        binary += pad4(data)

    gltf["buffers"] = [{"byteLength": len(binary)}]
    js = pad4(json.dumps(gltf, separators=(",", ":"), ensure_ascii=False).encode("utf-8"), b" ")
    total = 12 + 8 + len(js) + 8 + len(binary)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("wb") as f:
        f.write(struct.pack("<4sII", b"glTF", 2, total))
        f.write(struct.pack("<I4s", len(js), b"JSON") + js)
        f.write(struct.pack("<I4s", len(binary), b"BIN\0") + bytes(binary))
    print(f"{out}: {total / 1024 / 1024:.1f} МБ")


if __name__ == "__main__":
    main()
