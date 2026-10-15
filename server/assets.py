"""Ассеты заказчика и заглушки (SPEC раздел 12).

Эталонные заглушки лежат в server/stubs/ (генерирует tools/make_stubs.py).
При старте сервер копирует заглушку на место любого отсутствующего файла.
Файл считается заглушкой, пока его содержимое совпадает с эталонной заглушкой
(сравнение по хэшу), поэтому замена файлом с тем же именем не требует правок кода.
Наклейки: заглушки называются stub-*.png (маркер в имени) и копируются,
только если в assets/stickers/ нет ни одной картинки.
"""
from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

from .config import ROOT

STUB_DIR = ROOT / "server" / "stubs"

SFX = [
    "fact-notify", "shutter", "countdown", "correct", "wrong", "warning-tick",
    "game-start", "game-catch", "game-golden", "game-rotten", "game-end",
]

REQUIRED: list[str] = (
    ["rive/head.riv", "video/ambient.webm", "img/ambient-light.jpg", "overlay/final-frame.png"]
    + [f"avatars/pumpkin-{i}.png" for i in range(1, 9)]
    + [f"game/{n}.png" for n in ("pumpkin", "golden", "rotten", "basket")]
    + [f"sfx/{n}.mp3" for n in SFX]
)

# Необязательные: без файла работает запасной вариант, заглушка не нужна.
OPTIONAL: dict[str, str] = {
    "rive/timer.riv": "декор таймера (контракт позже)",
    "carve/pumpkin.glb": "по умолчанию процедурная модель",
}

STUB_STICKERS = ["stickers/stub-1.png", "stickers/stub-2.png", "stickers/stub-3.png"]

AVATARS = [f"pumpkin-{i}" for i in range(1, 9)]

_hash_cache: dict[tuple[str, float, int], str] = {}


def _sha(p: Path) -> str:
    st = p.stat()
    key = (str(p), st.st_mtime, st.st_size)
    if key not in _hash_cache:
        _hash_cache[key] = hashlib.sha256(p.read_bytes()).hexdigest()
    return _hash_cache[key]


def ensure_assets(assets_dir: Path) -> list[str]:
    """Положить заглушки на место отсутствующих файлов. Возвращает список созданных."""
    created = []
    for rel in REQUIRED:
        dst, src = assets_dir / rel, STUB_DIR / rel
        if not dst.exists() and src.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
            created.append(rel)
    stickers = assets_dir / "stickers"
    has_stickers = stickers.exists() and any(stickers.glob("*.png"))
    if not has_stickers:
        for rel in STUB_STICKERS:
            src = STUB_DIR / rel
            if src.exists():
                (assets_dir / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(src, assets_dir / rel)
                created.append(rel)
    return created


def is_stub(assets_dir: Path, rel: str) -> bool:
    p, s = assets_dir / rel, STUB_DIR / rel
    if Path(rel).name.startswith("stub-"):
        return True
    return p.exists() and s.exists() and _sha(p) == _sha(s)


def status(assets_dir: Path) -> list[dict]:
    """Состояние каждого ассета: ok | stub | missing | optional_missing."""
    out = []
    for rel in REQUIRED:
        p = assets_dir / rel
        st = "missing" if not p.exists() else ("stub" if is_stub(assets_dir, rel) else "ok")
        out.append({"path": rel, "status": st})
    for rel, note in OPTIONAL.items():
        st = "ok" if (assets_dir / rel).exists() else "optional_missing"
        out.append({"path": rel, "status": st, "note": note})
    stickers = sorted((assets_dir / "stickers").glob("*.png")) if (assets_dir / "stickers").exists() else []
    if not stickers:
        out.append({"path": "stickers/*.png", "status": "missing"})
    for p in stickers:
        rel = f"stickers/{p.name}"
        out.append({"path": rel, "status": "stub" if is_stub(assets_dir, rel) else "ok"})
    return out


def stub_paths(assets_dir: Path) -> list[str]:
    return [a["path"] for a in status(assets_dir) if a["status"] == "stub"]


def stickers(assets_dir: Path) -> list[str]:
    d = assets_dir / "stickers"
    return sorted(f"stickers/{p.name}" for p in d.glob("*.png")) if d.exists() else []
