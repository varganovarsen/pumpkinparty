"""Проверки перед вечером (/check и tools/check_env.py)."""
from __future__ import annotations

import importlib
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

from . import assets
from .config import Config
from .content_check import check as check_content

OK, WARN, FAIL, INFO = "ok", "warn", "fail", "info"

DEPS = [
    ("fastapi", True), ("multipart", True), ("uvicorn", True), ("yaml", True), ("PIL", True), ("pillow_heif", True),
    ("qrcode", True), ("cv2", True), ("numpy", True), ("scipy", False), ("soundfile", False),
]


def session_type() -> str:
    """Тип графической сессии. По ssh XDG_SESSION_TYPE=tty, тогда спрашиваем loginctl."""
    env = os.environ.get("XDG_SESSION_TYPE", "")
    if env and env != "tty":
        return env
    try:
        ids = subprocess.run(["loginctl", "list-sessions", "--no-legend"], capture_output=True, text=True, timeout=3)
        for line in ids.stdout.splitlines():
            sid = line.split()[0] if line.split() else ""
            t = subprocess.run(["loginctl", "show-session", sid, "-p", "Type", "--value"],
                               capture_output=True, text=True, timeout=3).stdout.strip()
            if t in ("x11", "wayland"):
                return f"{t} (сессия {sid})"
    except (OSError, subprocess.SubprocessError):
        pass
    return env


def _item(id_: str, title: str, status: str, detail: str = "", items: list | None = None) -> dict:
    return {"id": id_, "title": title, "status": status, "detail": detail, "items": items or []}


def static_checks(cfg: Config) -> list[dict]:
    """Проверки, не требующие запущенного сервера."""
    out = []
    v = sys.version_info
    out.append(_item("python", "Версия Python", OK if v >= (3, 11) else FAIL, platform.python_version()))

    missing, optional = [], []
    for mod, required in DEPS:
        try:
            importlib.import_module(mod)
        except Exception:  # noqa: BLE001
            (missing if required else optional).append(mod)
    if missing:
        out.append(_item("deps", "Зависимости", FAIL, "нет: " + ", ".join(missing)))
    else:
        out.append(_item("deps", "Зависимости", WARN if optional else OK,
                         ("необязательные нет: " + ", ".join(optional)) if optional else "все установлены"))

    usage = shutil.disk_usage(cfg.data_dir if cfg.data_dir.exists() else cfg.root)
    free_gb = usage.free / 1024**3
    out.append(_item("disk", "Свободное место", FAIL if free_gb < 1 else WARN if free_gb < 5 else OK,
                     f"{free_gb:.1f} ГБ"))

    st = assets.status(cfg.root / "assets")
    stubs = [a["path"] for a in st if a["status"] == "stub"]
    miss = [a["path"] for a in st if a["status"] == "missing"]
    opt = [f"{a['path']} ({a['note']})" for a in st if a["status"] == "optional_missing"]
    status = FAIL if miss else WARN if stubs else OK
    detail = f"заглушек {len(stubs)}" + (f", нет файлов {len(miss)}" if miss else "")
    items = [f"нет: {p}" for p in miss] + [f"заглушка: {p}" for p in stubs] + [f"не задан: {p}" for p in opt]
    out.append(_item("assets", "Ассеты", status, detail, items))

    errors, warnings = check_content(cfg.content_dir)
    out.append(_item("content", "Контент (check_content)", FAIL if errors else WARN if warnings else OK,
                     f"ошибок {len(errors)}, предупреждений {len(warnings)}",
                     [f"ошибка: {e}" for e in errors] + [f"внимание: {w}" for w in warnings]))

    session = session_type()
    out.append(_item("session", "Графическая сессия ($XDG_SESSION_TYPE)", INFO, session or "не задана"))

    if platform.system() == "Linux":
        dev = Path(f"/dev/video{int(cfg['webcam_device'])}")
        if not dev.exists():
            out.append(_item("video_dev", f"Устройство {dev}", FAIL, "не найдено"))
        elif not os.access(dev, os.R_OK | os.W_OK):
            out.append(_item("video_dev", f"Устройство {dev}", FAIL, "нет прав (добавить пользователя в группу video)"))
        else:
            out.append(_item("video_dev", f"Устройство {dev}", OK, "доступно"))
    else:
        out.append(_item("video_dev", "Вебка", INFO, f"проверка устройства только на Linux ({platform.system()})"))
    return out
