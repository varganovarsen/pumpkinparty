"""Фото (модуль 03): общий альбом, селфи, случайные кадры вебки, финальное фото, скачивание.

Файлы: data/photos/<name>.jpg (до 2048 px), data/photos/thumb/<name>.jpg (400 px),
оригиналы финального фото — data/photos/original/. «Удалить» переносит файлы в data/_deleted/.
Тяжёлая обработка картинок идёт в потоке (prepare_*), запись в базу и рассылка — в цикле событий.
"""
from __future__ import annotations

import asyncio
import io
import logging
import random
import secrets
import shutil
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING

from PIL import Image

from . import images, webcam
from .state import CmdError

if TYPE_CHECKING:
    from .state import Evening

log = logging.getLogger("pumpkin.photos")

ALBUM_MAX = 2048
THUMB = 400
FINAL_MAX = 3000
SHOT_WARN_SECONDS = 3
SHOT_SHOW_SECONDS = 4


class Photos:
    def __init__(self, ev: Evening):
        self.ev = ev
        self.root = ev.data_dir / "photos"
        self.shot_running = False
        self.last_shot_error: str | None = None  # для /check: последний неудачный кадр вебки
        self._ensure_next_shot()

    # ------------------------------------------------------------------ файлы
    def _dirs(self) -> None:
        for d in (self.root, self.root / "thumb", self.root / "original"):
            d.mkdir(parents=True, exist_ok=True)

    def prepare(self, img: Image.Image, max_side: int = ALBUM_MAX, quality: int = 85) -> dict:
        """Сохранить картинку и превью (в потоке). Возвращает имена файлов для commit()."""
        self._dirs()
        name = secrets.token_hex(8)
        big = img.convert("RGB")
        big.thumbnail((max_side, max_side), Image.LANCZOS)
        big.save(self.root / f"{name}.jpg", "JPEG", quality=quality)
        small = big.copy()
        small.thumbnail((THUMB, THUMB), Image.LANCZOS)
        small.save(self.root / "thumb" / f"{name}.jpg", "JPEG", quality=80)
        return {"path": f"{name}.jpg", "thumb": f"thumb/{name}.jpg"}

    def commit(self, files: dict, kind: str, author_id: int | None) -> dict:
        cur = self.ev.db.execute(
            "INSERT INTO photos(kind, author_id, path, thumb, created_at) VALUES(?, ?, ?, ?, ?)",
            (kind, author_id, files["path"], files["thumb"], self.ev.clock.now()),
        )
        photo = self.get(cur.lastrowid)
        who = self.ev.players[author_id].name if author_id in self.ev.players else None
        self.ev.log({"selfie": f"Новое селфи от {who}", "webcam": "Кадр с вебки в альбоме",
                     "final": "Финальное фото готово"}[kind], author_id)
        self.ev.emit({"tv", "host", "player"}, {"t": "photo_added", "photo": photo})
        return photo

    # ------------------------------------------------------------------ чтение
    def public(self, r) -> dict:
        p = self.ev.players.get(r["author_id"]) if r["author_id"] else None
        return {
            "id": r["id"], "kind": r["kind"], "author_id": r["author_id"],
            "author_name": p.name if p else None,
            "url": f"/media/photos/{r['path']}", "thumb_url": f"/media/photos/{r['thumb']}",
            "hidden": bool(r["hidden"]), "created_at": r["created_at"],
        }

    def get(self, photo_id: int) -> dict | None:
        r = self.ev.db.one("SELECT * FROM photos WHERE id=? AND deleted=0", (photo_id,))
        return self.public(r) if r else None

    def list(self, include_hidden: bool = False, final_first: bool = False) -> list[dict]:
        sql = "SELECT * FROM photos WHERE deleted=0" + ("" if include_hidden else " AND hidden=0")
        order = " ORDER BY (kind='final') DESC, id DESC" if final_first else " ORDER BY id DESC"
        return [self.public(r) for r in self.ev.db.all(sql + order)]

    def file_path(self, rel: str, include_hidden: bool = False) -> Path | None:
        """Путь к файлу фото (скрытые — только для /host)."""
        r = self.ev.db.one("SELECT * FROM photos WHERE (path=? OR thumb=?) AND deleted=0"
                           + ("" if include_hidden else " AND hidden=0"), (rel, rel))
        if not r:
            return None
        p = self.root / rel
        return p if p.exists() else None

    # ------------------------------------------------------------------ модерация
    def set_hidden(self, photo_id: int, hidden: bool) -> None:
        cur = self.ev.db.execute("UPDATE photos SET hidden=? WHERE id=? AND deleted=0", (int(bool(hidden)), int(photo_id)))
        if not cur.rowcount:
            raise CmdError("Фото не найдено", "not_found")
        self.ev.log(f"Фото {photo_id} {'скрыто' if hidden else 'снова показано'}")
        self.ev.emit({"tv", "host", "player"}, {"t": "photo_changed", "id": int(photo_id), "hidden": bool(hidden)})

    def delete(self, photo_id: int) -> None:
        r = self.ev.db.one("SELECT * FROM photos WHERE id=? AND deleted=0", (int(photo_id),))
        if not r:
            raise CmdError("Фото не найдено", "not_found")
        trash = self.ev.data_dir / "_deleted"
        (trash / "thumb").mkdir(parents=True, exist_ok=True)
        for rel in (r["path"], r["thumb"]):
            src = self.root / rel
            if src.exists():
                shutil.move(str(src), str(trash / rel))
        self.ev.db.execute("UPDATE photos SET deleted=1 WHERE id=?", (r["id"],))
        self.ev.log(f"Фото {r['id']} удалено (в data/_deleted/)")
        self.ev.emit({"tv", "host", "player"}, {"t": "photo_changed", "id": r["id"], "deleted": True})

    # ------------------------------------------------------------------ финальное фото
    def prepare_final(self, data: bytes) -> dict:
        """Оригинал → обрезка по центру до 4:3 → рамка заказчика поверх → JPEG q92 (в потоке)."""
        self._dirs()
        img = images.open_upload(data)
        # оригинал — исходные байты как есть (JPEG/HEIC с камеры, со всеми EXIF)
        ext = "heic" if data[4:12] in (b"ftypheic", b"ftypheix", b"ftypmif1", b"ftypmsf1") else "jpg"
        (self.root / "original" / f"{secrets.token_hex(8)}.{ext}").write_bytes(data)
        w, h = img.size
        if w / h > 4 / 3:
            nw = round(h * 4 / 3)
            img = img.crop(((w - nw) // 2, 0, (w - nw) // 2 + nw, h))
        else:
            nh = round(w * 3 / 4)
            img = img.crop((0, (h - nh) // 2, w, (h - nh) // 2 + nh))
        if img.width > FINAL_MAX:
            img = img.resize((FINAL_MAX, round(FINAL_MAX * 3 / 4)), Image.LANCZOS)
        frame_path = self.ev.assets_dir / "overlay" / "final-frame.png"
        if frame_path.exists():
            frame = Image.open(frame_path).convert("RGBA").resize(img.size, Image.LANCZOS)
            img = Image.alpha_composite(img.convert("RGBA"), frame).convert("RGB")
        return self.prepare(img, max_side=FINAL_MAX, quality=92)

    # ------------------------------------------------------------------ случайные кадры вебки
    def _ensure_next_shot(self) -> None:
        if self.ev.settings.get("shot_next_at") is None:
            self.schedule_next()

    def schedule_next(self) -> None:
        """Срок следующего случайного кадра: через «от»-«до» минут (настройка ведущего) от текущего момента."""
        lo = float(self.ev.settings.get("shots_min_minutes", self.ev.cfg["random_shots"]["interval_minutes"][0]))
        hi = float(self.ev.settings.get("shots_max_minutes", self.ev.cfg["random_shots"]["interval_minutes"][1]))
        self.ev._set("shot_next_at", self.ev.clock.now() + random.uniform(lo, max(lo, hi)) * 60)

    def tick(self) -> None:
        if self.shot_running or not self.ev.settings.get("shots_enabled", True):
            return
        if self.ev.clock.now() < self.ev.settings["shot_next_at"]:
            return
        if self.ev.settings["scene"] not in self.ev.cfg["random_shots"]["allowed_scenes"]:
            return  # срок наступил в другой сцене: снимем при первом разрешённом моменте
        if self.ev.head_current:
            return  # не снимать, пока на экране голова
        asyncio.get_running_loop().create_task(self.shot())

    async def shot(self, manual: bool = False) -> None:
        if self.shot_running:
            raise CmdError("Кадр уже снимается", "busy")
        self.shot_running = True
        try:
            self.ev.emit("tv", {"t": "shot", "stage": "countdown", "seconds": SHOT_WARN_SECONDS})
            await self.ev.clock.sleep(SHOT_WARN_SECONDS)
            loop = asyncio.get_running_loop()
            try:
                jpg = await loop.run_in_executor(None, webcam.snapshot, int(self.ev.cfg["webcam_device"]))
                files = await loop.run_in_executor(None, lambda: self.prepare(Image.open(io.BytesIO(jpg))))
            except Exception as e:  # noqa: BLE001 — нет вебки: пишем в журнал, повтор через интервал
                self.last_shot_error = f"{e}"
                self.ev.log(f"Вебка: кадр не снят ({e})")
                self.ev.emit("tv", {"t": "shot", "stage": "failed"})
                return
            self.last_shot_error = None
            photo = self.commit(files, "webcam", None)
            self.ev.emit("tv", {"t": "shot", "stage": "taken", "photo": photo, "seconds": SHOT_SHOW_SECONDS})
        finally:
            self.shot_running = False
            self.schedule_next()
            self.ev.emit_settings()  # ведущий видит, когда следующий кадр

    def reload(self) -> None:
        self.shot_running = False
        self._ensure_next_shot()

    # ------------------------------------------------------------------ ZIP
    def zip_file(self, ids: list[int], pumpkin_files: list[tuple[Path, str]] | None = None) -> Path:
        """Собрать ZIP во временный файл на диске (в потоке): JPEG уже сжаты, поэтому без сжатия."""
        rows = [r for r in (self.ev.db.one("SELECT * FROM photos WHERE id=? AND deleted=0 AND hidden=0", (int(i),))
                            for i in ids) if r]
        tmp = self.ev.data_dir / "tmp"
        tmp.mkdir(parents=True, exist_ok=True)
        out = tmp / f"photos-{secrets.token_hex(6)}.zip"
        with zipfile.ZipFile(out, "w", zipfile.ZIP_STORED) as z:
            for n, r in enumerate(rows, 1):
                p = self.root / r["path"]
                if p.exists():
                    z.write(p, f"tykvenny-spas-{n:02d}-{r['kind']}.jpg")
            for p, name in pumpkin_files or []:
                if p.exists():
                    z.write(p, name)
        return out
