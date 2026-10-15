"""Тыквы игроков (модуль 06): хранение последней версии в data/pumpkins/<player_id>/.

Тыква = две маски развёртки (through, depth; 8 бит, градации серого),
угол камеры «спереди» и три снимка (при свете, в темноте со свечой, сбоку в темноте).
"""
from __future__ import annotations

import io
import json
import shutil
from pathlib import Path

from PIL import Image

from .state import CmdError, Evening

MASK_NAMES = ("through", "depth")
SHOT_NAMES = ("lit", "dark", "side")
MASK_MAX = 4096
SHOT_MAX_BYTES = 4 * 1024 * 1024
FILES = [f"{n}.png" for n in MASK_NAMES] + [f"{n}.jpg" for n in SHOT_NAMES]


def pumpkin_dir(ev: Evening, player_id: int) -> Path:
    return ev.data_dir / "pumpkins" / str(int(player_id))


def info(ev: Evening, player_id: int) -> dict:
    row = ev.db.one("SELECT version, data, updated_at FROM pumpkins WHERE player_id=?", (player_id,))
    if not row:
        return {"exists": False, "player_id": player_id}
    data = json.loads(row["data"])
    v = row["version"]
    base = f"/media/pumpkins/{player_id}"
    return {
        "exists": True,
        "player_id": player_id,
        "version": v,
        "updated_at": row["updated_at"],
        "camera": data.get("camera"),
        "mask_size": data.get("mask_size"),
        "masks": {n: f"{base}/{n}.png?v={v}" for n in MASK_NAMES},
        "shots": {n: f"{base}/{n}.jpg?v={v}" for n in SHOT_NAMES},
    }


def versions(ev: Evening) -> dict[int, int]:
    return {r["player_id"]: r["version"] for r in ev.db.all("SELECT player_id, version FROM pumpkins")}


def _mask(data: bytes, name: str) -> tuple[bytes, tuple[int, int]]:
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception as e:  # noqa: BLE001
        raise CmdError(f"Маска {name} не читается", "bad_mask") from e
    if img.width != img.height or not 64 <= img.width <= MASK_MAX:
        raise CmdError(f"Маска {name}: неверный размер {img.size}", "bad_mask")
    img = img.convert("L")
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue(), img.size


def _shot(data: bytes, name: str) -> bytes:
    if len(data) > SHOT_MAX_BYTES:
        raise CmdError(f"Снимок {name} слишком большой", "bad_shot")
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception as e:  # noqa: BLE001
        raise CmdError(f"Снимок {name} не читается", "bad_shot") from e
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=88)
    return buf.getvalue()


def prepare(ev: Evening, player_id: int, files: dict[str, bytes], camera: dict) -> dict:
    """Проверить и записать файлы новой версии (старая заменяется целиком).

    Блокирующий вызов (Pillow, диск), выполняется в потоке. Запись в базу — commit().
    """
    p = ev.players.get(int(player_id))
    if not p:
        raise CmdError("Нет такого игрока", "not_found")
    if ev.settings.get("carve_locked"):
        raise CmdError("Голосование уже началось, тыквы больше не меняются", "locked")
    for n in FILES:
        if n not in files:
            raise CmdError(f"Не хватает файла {n}", "bad_request")
    try:
        cam = {k: float(camera[k]) for k in ("theta", "phi", "radius")}
    except (KeyError, TypeError, ValueError) as e:
        raise CmdError("Неверный угол камеры", "bad_request") from e

    out: dict[str, bytes] = {}
    sizes = set()
    for n in MASK_NAMES:
        out[f"{n}.png"], size = _mask(files[f"{n}.png"], n)
        sizes.add(size)
    if len(sizes) != 1:
        raise CmdError("Маски разного размера", "bad_mask")
    for n in SHOT_NAMES:
        out[f"{n}.jpg"] = _shot(files[f"{n}.jpg"], n)

    final = pumpkin_dir(ev, p.id)
    tmp = final.with_name(f"{p.id}.new")
    old = final.with_name(f"{p.id}.old")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    for name, data in out.items():
        (tmp / name).write_bytes(data)
    shutil.rmtree(old, ignore_errors=True)
    if final.exists():
        final.rename(old)
    tmp.rename(final)
    shutil.rmtree(old, ignore_errors=True)
    return {"camera": cam, "mask_size": sizes.pop()[0]}


def commit(ev: Evening, player_id: int, meta: dict) -> dict:
    p = ev.players.get(int(player_id))
    if not p:  # вечер сбросили, пока писали файлы
        raise CmdError("Нет такого игрока", "not_found")
    row = ev.db.one("SELECT version FROM pumpkins WHERE player_id=?", (p.id,))
    version = (row["version"] if row else 0) + 1
    data = json.dumps(meta)
    ev.db.execute(
        "INSERT INTO pumpkins(player_id, version, data, updated_at) VALUES(?, ?, ?, ?) "
        "ON CONFLICT(player_id) DO UPDATE SET version=excluded.version, data=excluded.data, "
        "updated_at=excluded.updated_at",
        (p.id, version, data, ev.clock.now()),
    )
    ev.log(f"{p.name} сохранил тыкву (версия {version})", p.id)
    ev.players_changed()
    return {"ok": True, **info(ev, p.id)}
