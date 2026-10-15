"""WebSocket: подключения, снимки состояния по ролям, команды (SPEC 11, docs/PROTOCOL.md)."""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Callable

from fastapi import WebSocket, WebSocketDisconnect

from .state import SCENE_TITLES, SCENES, CmdError, Evening

log = logging.getLogger("pumpkin.ws")

ROLES = {"tv", "host", "player", "carve"}
LOCALHOST = {"127.0.0.1", "::1", "localhost"}


@dataclass(eq=False)
class Conn:
    ws: WebSocket
    role: str
    player_id: int | None = None
    queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=1000))
    closed: bool = False

    def send(self, msg: dict) -> None:
        if self.closed:
            return
        try:
            self.queue.put_nowait(msg)
        except asyncio.QueueFull:  # клиент завис: отключаем, он переподключится и получит снимок
            self.closed = True
            asyncio.get_event_loop().create_task(self._drop())

    async def _drop(self) -> None:
        try:
            await self.ws.close(code=4002)
        except Exception:  # noqa: BLE001
            pass


class Hub:
    def __init__(self, ev: Evening):
        self.ev = ev
        self.conns: set[Conn] = set()
        ev.hub = self

    def emit(self, roles, msg: dict, player_id: int | None = None) -> None:
        roles = {roles} if isinstance(roles, str) else set(roles)
        for c in list(self.conns):
            if c.role in roles and (player_id is None or c.player_id == player_id):
                c.send(msg)

    def count(self, role: str) -> int:
        return sum(1 for c in self.conns if c.role == role and not c.closed)

    def reset_all(self) -> None:
        """После «Сбросить вечер»: все получают reset, игроки теряют токены."""
        for c in list(self.conns):
            c.send({"t": "reset"})
            if c.role == "player":
                c.player_id = None
                c.send(None)  # закрыть соединение после доставки
            else:
                c.send(self.snapshot(c))

    # ------------------------------------------------------------------ снимки
    def snapshot(self, c: Conn) -> dict:
        ev = self.ev
        snap = {
            "t": "snapshot",
            "role": c.role,
            "server_ms": ev.clock.now_ms(),
            "speed": ev.clock.speed,
            "scene": ev.scene_info(),
            "settings": ev.public_settings(),
            "join_url": self.join_url(),
        }
        if c.role == "player":
            snap["me"] = ev.me(c.player_id)
            snap["facts"] = ev.facts_public()
            snap["avatars_taken"] = ev.taken_avatars()
        if c.role in ("tv", "host"):
            snap["players"] = ev.players_public(with_scores=True)
        if c.role == "tv":
            snap["head"] = ev.head_snapshot()
            snap["stubs"] = self.stubs()
        if c.role == "host":
            snap["log"] = ev.recent_log()
            snap["scenes"] = [{"id": s, "title": SCENE_TITLES[s]} for s in SCENES]
            snap["next_step"] = ev.next_step()
            snap["tv_count"] = self.count("tv")
        if c.role == "carve":
            snap["players"] = ev.players_public(with_scores=False)
        return snap

    # подставляются из app.py
    join_url: Callable[[], str] = staticmethod(lambda: "")
    stubs: Callable[[], list] = staticmethod(lambda: [])

    # ------------------------------------------------------------------ соединение
    async def serve(self, ws: WebSocket) -> None:
        role = ws.query_params.get("role", "")
        token = ws.query_params.get("token")
        await ws.accept()
        if role not in ROLES:
            await ws.send_json({"t": "error", "code": "bad_role", "error": "Неизвестная роль"})
            await ws.close(code=4400)
            return
        if role == "tv" and self.ev.cfg["tv_localhost_only"] and (ws.client.host if ws.client else "") not in LOCALHOST:
            await ws.send_json({"t": "error", "code": "tv_localhost_only", "error": "Экран ТВ открывается только на ноутбуке"})
            await ws.close(code=4403)
            return
        conn = Conn(ws, role)
        if role == "player":
            p = self.ev.player_by_token(token)
            if not p:
                await ws.send_json({"t": "auth_failed"})
                await ws.close(code=4401)
                return
            conn.player_id = p.id
        self.conns.add(conn)
        if conn.player_id:
            self.ev.set_connected(conn.player_id, +1)
        if role == "tv":
            self.ev.emit("host", {"t": "tv_count", "count": self.count("tv")})
        conn.send(self.snapshot(conn))
        writer = asyncio.create_task(self._writer(conn))
        try:
            while True:
                raw = await ws.receive_text()
                try:
                    msg = json.loads(raw)
                except ValueError:
                    continue
                if not isinstance(msg, dict):
                    continue
                self._handle(conn, msg)
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            conn.closed = True
            self.conns.discard(conn)
            writer.cancel()
            if conn.player_id:
                self.ev.set_connected(conn.player_id, -1)
            if role == "tv":
                self.ev.emit("host", {"t": "tv_count", "count": self.count("tv")})

    async def _writer(self, conn: Conn) -> None:
        try:
            while True:
                msg = await conn.queue.get()
                if msg is None:
                    await conn.ws.close(code=4001)
                    return
                await conn.ws.send_text(json.dumps(msg, ensure_ascii=False))
        except Exception:  # noqa: BLE001 — обрыв: читающая сторона закроет соединение
            conn.closed = True

    # ------------------------------------------------------------------ команды
    def _handle(self, conn: Conn, msg: dict) -> None:
        t = msg.get("t")
        if t == "ping":
            conn.send({"t": "pong", "c": msg.get("c"), "s": self.ev.clock.now_ms()})
            return
        if t != "cmd":
            return
        name = msg.get("cmd", "")
        rid = msg.get("id")
        handler = COMMANDS.get(conn.role, {}).get(name)
        if not handler:
            conn.send({"t": "reply", "id": rid, "ok": False, "code": "forbidden", "error": "Команда недоступна"})
            return
        try:
            result = handler(self, conn, msg) or {}
            conn.send({"t": "reply", "id": rid, "ok": True, **result})
        except CmdError as e:
            conn.send({"t": "reply", "id": rid, "ok": False, "code": e.code, "error": str(e), **e.extra})
        except (KeyError, TypeError, ValueError) as e:
            log.warning("bad cmd %s: %s", name, e)
            conn.send({"t": "reply", "id": rid, "ok": False, "code": "bad_request", "error": "Неверная команда"})


# ---------------------------------------------------------------------- обработчики
def _host_set_scene(hub: Hub, c: Conn, m: dict):
    hub.ev.set_scene(m["scene"], m.get("payload"), bool(m.get("force")))


def _host_set_setting(hub: Hub, c: Conn, m: dict):
    hub.ev.set_setting(m["key"], m["value"])


def _host_adjust(hub: Hub, c: Conn, m: dict):
    hub.ev.adjust_score(m["player_id"], m["amount"], m.get("note", ""))


def _host_reset(hub: Hub, c: Conn, m: dict):
    if m.get("confirm") != "СБРОС":
        raise CmdError("Нужно двойное подтверждение", "confirm_required")
    return {"backup": hub.ev.reset_evening()}


def _host_reload_scene(hub: Hub, c: Conn, m: dict):
    hub.ev.log("Аварийно: перезагрузка сцены на ТВ")
    hub.ev.emit("tv", {"t": "reload"})


def _host_skip_question(hub: Hub, c: Conn, m: dict):
    raise CmdError("Сейчас нет идущего вопроса", "no_question")


def _host_log(hub: Hub, c: Conn, m: dict):
    pid = m.get("player_id")
    return {"log": hub.ev.recent_log(50, int(pid) if pid else None)}


def _host_sound_test(hub: Hub, c: Conn, m: dict):
    if not hub.count("tv"):
        raise CmdError("ТВ не подключён", "no_tv")
    hub.ev.emit("tv", {"t": "sound_test"})


def _host_head_call(hub: Hub, c: Conn, m: dict):
    hub.ev.head_call()


def _host_head_skip(hub: Hub, c: Conn, m: dict):
    hub.ev.head_skip()


def _tv_head_shown(hub: Hub, c: Conn, m: dict):
    hub.ev.head_shown(str(m["fact_id"]))


def _tv_head_done(hub: Hub, c: Conn, m: dict):
    hub.ev.head_done(str(m["fact_id"]))


def _player_profile(hub: Hub, c: Conn, m: dict):
    hub.ev.update_profile(c.player_id, m["avatar_kind"], m["avatar_ref"])


def _snapshot(hub: Hub, c: Conn, m: dict):
    c.send(hub.snapshot(c))


COMMANDS: dict[str, dict[str, Callable]] = {
    "host": {
        "set_scene": _host_set_scene,
        "set_setting": _host_set_setting,
        "adjust_score": _host_adjust,
        "reset_evening": _host_reset,
        "reload_scene": _host_reload_scene,
        "skip_question": _host_skip_question,
        "get_log": _host_log,
        "sound_test": _host_sound_test,
        "head_call": _host_head_call,
        "head_skip": _host_head_skip,
        "snapshot": _snapshot,
    },
    "tv": {"head_shown": _tv_head_shown, "head_done": _tv_head_done, "snapshot": _snapshot},
    "player": {"update_profile": _player_profile, "snapshot": _snapshot},
    "carve": {"snapshot": _snapshot},
}
