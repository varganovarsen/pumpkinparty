"""Резервные копии data/ (модуль 01)."""
from __future__ import annotations

import datetime as dt
import shutil
from pathlib import Path

from .db import DB

KEEP_AUTO = 12
DB_NAMES = {"pumpkin.db", "pumpkin.db-wal", "pumpkin.db-shm"}


def _stamp() -> str:
    return dt.datetime.now().strftime("%Y%m%d-%H%M%S")


def _file_list(data_dir: Path) -> str:
    lines = []
    for p in sorted(data_dir.rglob("*")):
        rel = p.relative_to(data_dir)
        if rel.parts and rel.parts[0] == "backups":
            continue
        if p.is_file():
            lines.append(f"{p.stat().st_size}\t{rel.as_posix()}")
    return "\n".join(lines) + "\n"


def make_backup(db: DB, data_dir: Path) -> Path:
    """Копия базы и список файлов в data/backups/<ts>/, храним последние 12."""
    root = data_dir / "backups"
    dest = root / _stamp()
    n = 1
    while dest.exists():
        n += 1
        dest = root / f"{_stamp()}-{n}"
    db.backup_to(dest / "pumpkin.db")
    (dest / "files.txt").write_text(_file_list(data_dir), encoding="utf-8", newline="\n")
    auto = sorted(p for p in root.iterdir() if p.is_dir() and p.name[:1].isdigit())
    for old in auto[:-KEEP_AUTO]:
        shutil.rmtree(old, ignore_errors=True)
    return dest


def copy_before_reset(db: DB, data_dir: Path) -> Path:
    """Полная копия data/ (кроме backups) в data/backups/before_reset_<ts>/."""
    dest = data_dir / "backups" / f"before_reset_{_stamp()}"
    dest.mkdir(parents=True, exist_ok=True)
    db.backup_to(dest / "pumpkin.db")
    for p in data_dir.iterdir():
        if p.name == "backups" or p.name in DB_NAMES:
            continue
        if p.is_dir():
            shutil.copytree(p, dest / p.name, dirs_exist_ok=True)
        else:
            shutil.copy2(p, dest / p.name)
    return dest
