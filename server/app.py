"""FastAPI-приложение: страницы, статика, REST для входа и загрузок, WebSocket."""
from __future__ import annotations

import asyncio
import json
import logging
import logging.handlers
import os
import re
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, Request, UploadFile, WebSocket
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask

from . import assets, carve, images, qr, webcam
from .backup import make_backup
from .checks import INFO, OK, FAIL, WARN, static_checks
from .clock import Clock
from .config import ROOT, Config, load_config
from .content import Content
from .db import DB
from .state import CmdError, Evening
from .ws import LOCALHOST, Hub

log = logging.getLogger("pumpkin")

WEB = ROOT / "web"
MAX_UPLOAD = 30 * 1024 * 1024
UPLOAD_RE = re.compile(r"^[0-9a-f]{16}$")
MEDIA_RE = re.compile(r"^[a-z0-9_]+\.(png|jpg)$")


def setup_logging(data_dir: Path) -> None:
    root = logging.getLogger("pumpkin")
    if root.handlers:
        return
    (data_dir / "logs").mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    fh = logging.handlers.RotatingFileHandler(
        data_dir / "logs" / "server.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    fh.setFormatter(fmt)
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    root.addHandler(fh)
    root.addHandler(sh)
    root.setLevel(logging.INFO)


def err(e: CmdError, status: int = 409) -> JSONResponse:
    return JSONResponse({"ok": False, "code": e.code, "error": str(e), **e.extra}, status_code=status)


def create_app(cfg: Config | None = None) -> FastAPI:
    cfg = cfg or load_config()
    data_dir = cfg.data_dir
    data_dir.mkdir(parents=True, exist_ok=True)
    setup_logging(data_dir)

    db = DB(data_dir / "pumpkin.db")
    # При ускорении (симулятор) время сервера продолжается с сохранённой точки, иначе после
    # перезапуска дедлайны квиза оказались бы в «будущем». При speed = 1 это просто часы.
    start = None
    if float(cfg["speed"]) != 1:
        last_event = db.one("SELECT MAX(ts) AS ts FROM event_log")["ts"]
        start = max(float(db.get_setting("clock_now") or 0), float(last_event or 0)) or None
    clock = Clock(cfg["speed"], start=start)
    content = Content(cfg.content_dir)
    ev = Evening(cfg, db, clock, content)
    hub = Hub(ev)
    created = assets.ensure_assets(ROOT / "assets")
    if created:
        log.info("Заглушки созданы: %s", ", ".join(created))

    def join_url() -> str:
        return qr.base_url(cfg["public_host"], int(cfg["port"])) + "/"

    hub.join_url = join_url
    hub.stubs = lambda: assets.stub_paths(ROOT / "assets")

    async def backup_loop():
        while True:
            await clock.sleep(float(cfg["backup_interval_minutes"]) * 60)
            try:
                make_backup(db, data_dir)
            except Exception:  # noqa: BLE001
                log.exception("Резервная копия не удалась")

    async def tick_loop():
        """Таймеры сцен (квиз, игра, таймер, кадры вебки, голова) по серверному времени."""
        last_save = 0.0
        while True:
            await clock.sleep(0.2)
            try:
                ev.tick()
                if clock.speed != 1 and time.monotonic() - last_save > 1:
                    db.set_setting("clock_now", clock.now())
                    last_save = time.monotonic()
            except Exception:  # noqa: BLE001 — сбой одного тика не должен останавливать таймеры
                log.exception("Сбой таймера")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        (data_dir / "server.pid").write_text(str(os.getpid()), encoding="utf-8")
        task = asyncio.create_task(backup_loop())
        ticker = asyncio.create_task(tick_loop())
        log.info("Сервер запущен: %s (скорость времени x%s)", join_url(), clock.speed)
        yield
        task.cancel()
        ticker.cancel()
        if clock.speed != 1:
            db.set_setting("clock_now", clock.now())
        try:
            make_backup(db, data_dir)
        except Exception:  # noqa: BLE001
            log.exception("Резервная копия при остановке не удалась")

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.ev, app.state.hub, app.state.cfg, app.state.db, app.state.clock = ev, hub, cfg, db, clock

    def is_local(request: Request) -> bool:
        return (request.client.host if request.client else "") in LOCALHOST

    @app.middleware("http")
    async def no_cache(request: Request, call_next):
        resp = await call_next(request)
        if not request.url.path.startswith(("/media/", "/content/")):
            resp.headers["Cache-Control"] = "no-cache"
        return resp

    # ------------------------------------------------------------------ страницы
    def page(rel: str) -> FileResponse:
        return FileResponse(WEB / rel, media_type="text/html; charset=utf-8")

    @app.get("/tv")
    async def tv_page(request: Request):
        if cfg["tv_localhost_only"] and not is_local(request):
            return Response("Экран ТВ открывается только на самом ноутбуке.", status_code=403,
                            media_type="text/plain; charset=utf-8")
        return page("tv/index.html")

    @app.get("/host")
    @app.get("/check")
    async def host_page():
        return page("host/index.html")

    @app.get("/")
    async def play_page():
        return page("play/index.html")

    @app.get("/carve")
    async def carve_page():
        return page("carve/index.html")

    @app.get("/download")
    async def download_page():
        return page("play/download.html")

    @app.get("/tools/lipsync-preview")
    async def lipsync_page():
        return page("tools/lipsync-preview.html")

    # ------------------------------------------------------------------ статика
    app.mount("/web", StaticFiles(directory=WEB), name="web")
    (ROOT / "assets").mkdir(exist_ok=True)
    app.mount("/assets", StaticFiles(directory=ROOT / "assets"), name="assets")
    for sub in ("images", "audio"):  # quiz.yaml и facts.yaml наружу не отдаются
        (cfg.content_dir / sub).mkdir(parents=True, exist_ok=True)
        app.mount(f"/content/{sub}", StaticFiles(directory=cfg.content_dir / sub), name=f"content-{sub}")

    @app.get("/media/pumpkins/{pid}/{name}")
    async def pumpkin_media(pid: int, name: str):
        if name not in carve.FILES:
            return Response(status_code=404)
        p = carve.pumpkin_dir(ev, pid) / name
        if not p.exists():
            return Response(status_code=404)
        return FileResponse(p, headers={"Cache-Control": "no-cache"})

    @app.get("/media/vote/{n}/{name}")
    async def vote_media(n: int, name: str):
        p = ev.vote.file_for(n, name)
        return FileResponse(p, headers={"Cache-Control": "no-cache"}) if p else Response(status_code=404)

    @app.get("/media/photos/{name}")
    @app.get("/media/photos/thumb/{name}")
    async def photo_media(request: Request, name: str):
        rel = ("thumb/" if "/thumb/" in request.url.path else "") + name
        p = ev.photos.file_path(rel, include_hidden=request.query_params.get("all") == "1") if MEDIA_RE.match(name) else None
        if not p:
            return Response(status_code=404)
        headers = {"Content-Disposition": f'attachment; filename="{name}"'} if request.query_params.get("dl") else None
        return FileResponse(p, headers=headers)

    @app.get("/media/{kind}/{name}")
    async def media(kind: str, name: str):
        if kind not in ("avatars", "uploads") or not MEDIA_RE.match(name):
            return Response(status_code=404)
        p = data_dir / kind / name
        if not p.exists():
            return Response(status_code=404)
        return FileResponse(p)

    # ------------------------------------------------------------------ API
    @app.get("/favicon.ico")
    async def favicon():
        svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
               '<text y=".9em" font-size="90">🎃</text></svg>')
        return Response(svg, media_type="image/svg+xml")

    @app.get("/api/health")
    async def health():
        return {"ok": True, "server_ms": clock.now_ms(), "speed": clock.speed}

    @app.get("/api/info")
    async def info():
        taken = set(ev.taken_avatars())
        return {
            "join_url": join_url(),
            "name_max": 20,
            "avatars": [
                {"id": a, "url": f"/assets/avatars/{a}.png", "taken": a in taken} for a in assets.AVATARS
            ],
            "stickers": [f"/assets/{s}" for s in assets.stickers(ROOT / "assets")],
        }

    @app.get("/api/qr.svg")
    async def qr_svg(path: str = "/"):
        if not path.startswith("/"):
            path = "/"
        return Response(qr.svg(join_url().rstrip("/") + path), media_type="image/svg+xml")

    @app.post("/api/upload_avatar")
    async def upload_avatar(file: UploadFile = File(...)):
        data = await file.read(MAX_UPLOAD + 1)
        if len(data) > MAX_UPLOAD:
            return err(CmdError("Файл слишком большой", "too_big"), 413)
        loop = asyncio.get_running_loop()
        try:
            img = await loop.run_in_executor(None, images.open_upload, data)
            preview = await loop.run_in_executor(None, images.make_preview, img)
        except Exception:  # noqa: BLE001
            log.exception("Не удалось открыть загруженную картинку")
            return err(CmdError("Не получилось открыть фото, попробуйте другое", "bad_image"), 400)
        uid = secrets.token_hex(8)
        (data_dir / "uploads").mkdir(parents=True, exist_ok=True)
        (data_dir / "uploads" / f"{uid}.jpg").write_bytes(preview)
        return {"ok": True, "upload_id": uid, "preview_url": f"/media/uploads/{uid}.jpg"}

    @app.post("/api/avatar_crop")
    async def avatar_crop(request: Request):
        body = await request.json()
        uid = str(body.get("upload_id", ""))
        src = data_dir / "uploads" / f"{uid}.jpg"
        if not UPLOAD_RE.match(uid) or not src.exists():
            return err(CmdError("Фото не найдено, загрузите ещё раз", "not_found"), 404)
        try:
            cx, cy, size = float(body["cx"]), float(body["cy"]), float(body["size"])
        except (KeyError, TypeError, ValueError):
            return err(CmdError("Неверные параметры обрезки", "bad_request"), 400)
        loop = asyncio.get_running_loop()
        img = await loop.run_in_executor(None, images.open_upload, src.read_bytes())
        png = await loop.run_in_executor(None, images.make_avatar, img, cx, cy, size)
        ref = f"p_{secrets.token_hex(8)}.png"
        (data_dir / "avatars").mkdir(parents=True, exist_ok=True)
        (data_dir / "avatars" / ref).write_bytes(png)
        return {"ok": True, "avatar_ref": ref, "avatar_url": f"/media/avatars/{ref}"}

    @app.post("/api/join")
    async def join(request: Request):
        body = await request.json()
        try:
            p = ev.join(
                str(body.get("name", "")), str(body.get("avatar_kind", "")),
                str(body.get("avatar_ref", "")), bool(body.get("as_host")),
            )
        except CmdError as e:
            return err(e)
        return {"ok": True, "token": p.token, "me": ev.me(p.id)}

    @app.post("/api/claim")
    async def claim(request: Request):
        body = await request.json()
        try:
            p = ev.claim(str(body.get("name", "")))
        except CmdError as e:
            return err(e)
        return {"ok": True, "token": p.token, "me": ev.me(p.id)}

    @app.get("/api/pumpkin/{pid}")
    async def pumpkin_get(pid: int):
        if pid not in ev.players:
            return err(CmdError("Нет такого игрока", "not_found"), 404)
        return carve.info(ev, pid)

    @app.post("/api/pumpkin/{pid}")
    async def pumpkin_save(pid: int, request: Request):
        form = await request.form(max_part_size=carve.SHOT_MAX_BYTES * 2)
        files: dict[str, bytes] = {}
        for name in carve.FILES:
            f = form.get(name)
            if f is not None and hasattr(f, "read"):
                if (getattr(f, "size", 0) or 0) > carve.SHOT_MAX_BYTES * 4:
                    return err(CmdError(f"Файл {name} слишком большой", "too_big"), 413)
                files[name] = await f.read()
        try:
            camera = json.loads(str(form.get("camera", "{}")))
        except ValueError:
            camera = {}
        loop = asyncio.get_running_loop()
        try:
            # обработка картинок в потоке, запись в базу — в цикле событий
            checked = await loop.run_in_executor(None, carve.prepare, ev, pid, files, camera)
            return carve.commit(ev, pid, checked)
        except CmdError as e:
            return err(e, 404 if e.code == "not_found" else 409 if e.code == "locked" else 400)

    # ------------------------------------------------------------------ фото (модуль 03)
    def player_from(token: str | None):
        p = ev.player_by_token(token)
        if not p:
            raise CmdError("Войдите в игру заново", "auth")
        return p

    async def read_upload(file: UploadFile) -> bytes:
        data = await file.read(MAX_UPLOAD + 1)
        if len(data) > MAX_UPLOAD:
            raise CmdError("Файл слишком большой", "too_big")
        return data

    @app.post("/api/convert_image")
    async def convert_image(file: UploadFile = File(...)):
        """Картинка, которую браузер не открывает сам (HEIC на Android): вернуть JPEG до 2048 px."""
        try:
            data = await read_upload(file)
            loop = asyncio.get_running_loop()
            img = await loop.run_in_executor(None, images.open_upload, data)
            out = await loop.run_in_executor(None, images.make_preview, img, 2048)
        except CmdError as e:
            return err(e, 413)
        except Exception:  # noqa: BLE001
            return err(CmdError("Не получилось открыть фото", "bad_image"), 400)
        return Response(out, media_type="image/jpeg")

    @app.post("/api/photo")
    async def upload_selfie(token: str = Form(""), file: UploadFile = File(...)):
        try:
            p = player_from(token)
            data = await read_upload(file)
            loop = asyncio.get_running_loop()
            img = await loop.run_in_executor(None, images.open_upload, data)
            files = await loop.run_in_executor(None, ev.photos.prepare, img)
        except CmdError as e:
            return err(e, 403 if e.code == "auth" else 400)
        except Exception:  # noqa: BLE001
            log.exception("Селфи не сохранилось")
            return err(CmdError("Фото не сохранилось, попробуйте ещё раз", "bad_image"), 400)
        return {"ok": True, "photo": ev.photos.commit(files, "selfie", p.id)}

    @app.post("/api/final_photo")
    async def upload_final(file: UploadFile = File(...)):
        try:
            data = await read_upload(file)
            files = await asyncio.get_running_loop().run_in_executor(None, ev.photos.prepare_final, data)
        except CmdError as e:
            return err(e, 413)
        except Exception:  # noqa: BLE001
            log.exception("Финальное фото не обработалось")
            return err(CmdError("Фото не обработалось, переснимите", "bad_image"), 400)
        photo = ev.photos.commit(files, "final", None)
        ev.finale.set_final_photo(photo["id"])
        return {"ok": True, "photo": photo}

    @app.get("/api/photos")
    async def list_photos(all: int = 0, final_first: int = 0):
        return {"photos": ev.photos.list(include_hidden=bool(all), final_first=bool(final_first))}

    @app.get("/api/me")
    async def me(token: str = ""):
        p = ev.player_by_token(token)
        return {"me": ev.me(p.id) if p else None}

    @app.get("/api/pumpkins")
    async def list_pumpkins():
        """Снимки всех тыкв с авторами — только после раскрытия итогов резьбы."""
        if not ev.vote.st["revealed"]:
            return {"revealed": False, "pumpkins": []}
        out = []
        for r in ev.vote.st["results"]:
            pl = ev.players.get(r["player_id"])
            info = carve.info(ev, r["player_id"])
            if info["exists"]:
                out.append({"player_id": r["player_id"], "name": pl.name if pl else "?", "votes": r["votes"],
                            "place": r["place"], "shots": info["shots"]})
        return {"revealed": True, "pumpkins": out}

    @app.post("/api/download_zip")
    async def download_zip(request: Request):
        form = await request.form()
        ids = [int(x) for x in str(form.get("ids", "")).split(",") if x.strip().isdigit()]
        pumpkin_ids = [int(x) for x in str(form.get("pumpkins", "")).split(",") if x.strip().isdigit()]
        extra = []
        if ev.vote.st["revealed"]:
            for pid in pumpkin_ids:
                pl = ev.players.get(pid)
                for shot in carve.SHOT_NAMES:
                    safe = re.sub(r"[^\w-]+", "_", pl.name if pl else str(pid)).strip("_") or str(pid)
                    extra.append((carve.pumpkin_dir(ev, pid) / f"{shot}.jpg", f"tykva-{safe}-{shot}.jpg"))
        if not ids and not extra:
            return err(CmdError("Ничего не выбрано", "empty"), 400)
        path = await asyncio.get_running_loop().run_in_executor(None, ev.photos.zip_file, ids, extra)
        return FileResponse(path, media_type="application/zip", filename="tykvenny-spas.zip",
                            background=BackgroundTask(path.unlink, missing_ok=True))

    # ------------------------------------------------------------------ липсинк (модуль 04)
    @app.get("/api/lipsync")
    async def lipsync_list():
        d = cfg.content_dir / "audio"
        out = []
        for mp3 in sorted(d.glob("*.mp3")):
            js = mp3.with_suffix(".lipsync.json")
            out.append({"name": mp3.name, "audio_url": f"/content/audio/{mp3.name}",
                        "lipsync_url": f"/content/audio/{js.name}" if js.exists() else None})
        return {"files": out}

    @app.get("/api/check")
    async def check():
        loop = asyncio.get_running_loop()
        items = await loop.run_in_executor(None, static_checks, cfg)
        phones = sum(1 for p in ev.players.values() if p.connected)
        tv = hub.count("tv")
        items[:0] = [
            {"id": "address", "title": "Адрес для гостей", "status": INFO, "detail": join_url(), "items": []},
            {"id": "tv", "title": "Экран ТВ подключён", "status": OK if tv else FAIL,
             "detail": f"окон /tv: {tv}", "items": []},
            {"id": "phones", "title": "Подключено телефонов", "status": INFO,
             "detail": f"{phones} из {len(ev.players)} игроков", "items": []},
        ]
        if ev.photos.last_shot_error:
            items.append({"id": "webcam_runtime", "title": "Случайные кадры вебки", "status": FAIL,
                          "detail": f"последний кадр не снят: {ev.photos.last_shot_error}", "items": []})
        return {"items": items, "summary": {
            "fail": sum(i["status"] == FAIL for i in items), "warn": sum(i["status"] == WARN for i in items),
        }}

    @app.get("/api/webcam_test")
    async def webcam_test():
        loop = asyncio.get_running_loop()
        try:
            jpg = await loop.run_in_executor(None, webcam.snapshot, int(cfg["webcam_device"]))
        except webcam.WebcamError as e:
            ev.log(f"Вебка: {e}")
            return JSONResponse({"ok": False, "error": str(e)}, status_code=503)
        return Response(jpg, media_type="image/jpeg")

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket):
        await hub.serve(ws)

    return app
