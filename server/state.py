"""Состояние вечера: игроки, сцены, журнал начислений, настройки, журнал событий.

Сервер главный (SPEC 3.3): клиенты только присылают команды, состояние меняется
здесь и сразу пишется в SQLite (SPEC 3.4). Рассылка событий идёт через Hub.
"""
from __future__ import annotations

import logging
import random
import re
import secrets
import shutil
import unicodedata
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from . import assets
from .backup import copy_before_reset
from .clock import Clock
from .config import Config
from .content import Content
from .db import DB

if TYPE_CHECKING:
    from .ws import Hub

log = logging.getLogger("pumpkin.state")

SCENES = [
    "ambient", "quiz", "game", "seeds", "bomb", "timer", "carve_vote", "carve_reveal",
    "rating_reveal", "final_photo", "slideshow", "download",
]
SCENE_TITLES = {
    "ambient": "Ambient",
    "quiz": "Квиз",
    "game": "Падающие тыквы",
    "seeds": "Охота за семечками",
    "bomb": "Бомба",
    "timer": "Перерыв",
    "carve_vote": "Аллея тыкв",
    "carve_reveal": "Итоги резьбы",
    "rating_reveal": "Общий рейтинг",
    "final_photo": "Финальное фото",
    "slideshow": "Слайд-шоу",
    "download": "Скачивание фото",
}
# Сцены с участием: телефон уходит в полноэкранный режим без вкладок.
PARTICIPATING = {"quiz", "game", "seeds", "bomb", "carve_vote"}
# Сцены с живой фазой: уход из них требует подтверждения на /host.
# Квиз живой только во время вопроса и вердиктов; игра и голосование пока целиком (модули 05/06).
LIVE = {"game", "seeds", "bomb", "carve_vote"}
# Рекомендуемый порядок вечера (подсказка «Следующий шаг», SPEC 8).
RECOMMENDED = [
    "ambient", "quiz", "timer", "game", "seeds", "bomb", "carve_vote", "carve_reveal",
    "rating_reveal", "final_photo", "slideshow", "download",
]

LEDGER_SOURCES = {"quiz", "quiz_bonus", "game", "seeds", "bomb", "carve", "manual"}

HEAD_QUIET_SECONDS = 22

NAME_MAX = 20


class CmdError(Exception):
    """Ошибка команды, текст показывается пользователю."""

    def __init__(self, message: str, code: str = "error", **extra):
        super().__init__(message)
        self.code = code
        self.extra = extra


@dataclass
class Player:
    id: int
    token: str
    name: str
    avatar_kind: str
    avatar_ref: str
    is_host: bool
    in_scoring: bool
    created_at: float
    connections: int = field(default=0, compare=False)

    @property
    def connected(self) -> bool:
        return self.connections > 0

    @property
    def avatar_url(self) -> str:
        if self.avatar_kind == "photo":
            return f"/media/avatars/{self.avatar_ref}"
        return f"/assets/avatars/{self.avatar_ref}.png"


def normalize_name(raw: str) -> str:
    name = unicodedata.normalize("NFC", str(raw or ""))
    name = "".join(ch for ch in name if unicodedata.category(ch)[0] != "C")
    return re.sub(r"\s+", " ", name).strip()


class Evening:
    def __init__(self, cfg: Config, db: DB, clock: Clock, content: Content):
        self.cfg = cfg
        self.db = db
        self.clock = clock
        self.content = content
        self.hub: Hub | None = None
        self.players: dict[int, Player] = {}
        self.head_current: dict | None = None
        self.assets_dir = cfg.root / "assets"
        self.data_dir = cfg.data_dir
        self._load()
        # модули сцен импортируются здесь, чтобы не было циклического импорта
        from .bomb import Bomb
        from .finale import Finale, Timer
        from .game import Game
        from .photos import Photos
        from .quiz import Quiz
        from .seeds import Seeds
        from .vote import Vote

        self.quiz = Quiz(self)
        self.photos = Photos(self)
        self.game = Game(self)
        self.seeds = Seeds(self)
        self.bomb = Bomb(self)
        self.vote = Vote(self)
        self.timer = Timer(self)
        self.finale = Finale(self)
        # модули с собственным состоянием для клиентов: имя события = имя модуля
        self.modules = {"quiz": self.quiz, "game": self.game, "seeds": self.seeds, "bomb": self.bomb,
                        "vote": self.vote, "timer": self.timer, "finale": self.finale}
        self._head_schedule(initial=True)

    # ------------------------------------------------------------------ загрузка
    def _defaults(self) -> dict:
        c = self.cfg
        return {
            "scene": "ambient",
            "scene_payload": {},
            "scene_started_at": self.clock.now(),
            "last_scene_end_at": None,
            "host_in_scoring": bool(c["host_in_scoring"]),
            "hide_total": False,
            "quiz_started": False,
            "head_mode": c["head"]["mode"],
            "head_enabled": True,
            "head_interval_minutes": c["head"]["interval_minutes"],
            "light_mode": bool(c["ambient"]["light_mode"]),
            "new_photo_card": bool(c["ambient"]["new_photo_card"]),
            "shots_enabled": True,
            "shots_min_minutes": float(c["random_shots"]["interval_minutes"][0]),
            "shots_max_minutes": float(c["random_shots"]["interval_minutes"][1]),
            "alley_slides": False,
            "carve_locked": False,
            "head_next_at": None,
        }

    def _load(self) -> None:
        stored = self.db.all_settings()
        self.settings = {**self._defaults(), **stored}
        for k, v in self.settings.items():
            if k not in stored:
                self.db.set_setting(k, v)
        if self.settings["scene"] not in SCENES:
            self.settings["scene"] = "ambient"
        self.players = {}
        for r in self.db.all("SELECT * FROM players ORDER BY id"):
            self.players[r["id"]] = Player(
                id=r["id"], token=r["token"], name=r["name"], avatar_kind=r["avatar_kind"],
                avatar_ref=r["avatar_ref"], is_host=bool(r["is_host"]),
                in_scoring=bool(r["in_scoring"]), created_at=r["created_at"],
            )

    # ------------------------------------------------------------------ рассылка
    def emit(self, roles: str | set[str], msg: dict, player_id: int | None = None) -> None:
        if self.hub:
            self.hub.emit(roles, msg, player_id=player_id)

    def _set(self, key: str, value: Any) -> None:
        self.settings[key] = value
        self.db.set_setting(key, value)

    # ------------------------------------------------------------------ журнал событий
    def log(self, text: str, player_id: int | None = None) -> None:
        ts = self.clock.now()
        cur = self.db.execute(
            "INSERT INTO event_log(ts, player_id, text) VALUES(?, ?, ?)", (ts, player_id, text)
        )
        self.emit("host", {"t": "log", "entry": {"id": cur.lastrowid, "ts": ts, "player_id": player_id, "text": text}})

    def recent_log(self, limit: int = 50, player_id: int | None = None) -> list[dict]:
        if player_id:
            rows = self.db.all(
                "SELECT * FROM event_log WHERE player_id=? ORDER BY id DESC LIMIT ?", (player_id, limit)
            )
        else:
            rows = self.db.all("SELECT * FROM event_log ORDER BY id DESC LIMIT ?", (limit,))
        return [dict(r) for r in reversed(rows)]

    # ------------------------------------------------------------------ очки (ledger)
    def add_points(self, player_id: int, source: str, amount: int, ref: str = "", note: str = "",
                   notify: bool = True) -> None:
        if source not in LEDGER_SOURCES:
            raise ValueError(source)
        self.db.execute(
            "INSERT INTO ledger(player_id, source, ref, amount, note, ts) VALUES(?, ?, ?, ?, ?, ?)",
            (player_id, source, ref, int(amount), note, self.clock.now()),
        )
        if notify:
            self.scores_changed({player_id})

    def totals(self) -> dict[int, int]:
        rows = self.db.all("SELECT player_id, COALESCE(SUM(amount), 0) AS s FROM ledger GROUP BY player_id")
        out = {pid: 0 for pid in self.players}
        out.update({r["player_id"]: r["s"] for r in rows})
        return out

    def breakdown(self, player_id: int) -> dict[str, int]:
        rows = self.db.all(
            "SELECT source, SUM(amount) AS s FROM ledger WHERE player_id=? GROUP BY source", (player_id,)
        )
        return {r["source"]: r["s"] for r in rows}

    def total(self, player_id: int) -> int:
        r = self.db.one("SELECT COALESCE(SUM(amount), 0) AS s FROM ledger WHERE player_id=?", (player_id,))
        return int(r["s"])

    def scores_changed(self, ids: set[int]) -> None:
        self.emit({"host", "tv"}, {"t": "players", "players": self.players_public(with_scores=True)})
        for pid in ids:
            if pid in self.players:
                self.emit("player", {"t": "me", "me": self.me(pid)}, player_id=pid)

    # ------------------------------------------------------------------ игроки
    def player_by_token(self, token: str | None) -> Player | None:
        if not token:
            return None
        return next((p for p in self.players.values() if p.token == token), None)

    def player_by_name(self, name: str) -> Player | None:
        key = normalize_name(name).casefold()
        return next((p for p in self.players.values() if p.name.casefold() == key), None)

    def taken_avatars(self, exclude_player: int | None = None) -> list[str]:
        return sorted(
            p.avatar_ref for p in self.players.values()
            if p.avatar_kind == "pumpkin" and p.id != exclude_player
        )

    def _check_avatar(self, kind: str, ref: str, player_id: int | None = None) -> None:
        if kind == "pumpkin":
            if ref not in assets.AVATARS:
                raise CmdError("Нет такого аватара", "bad_avatar")
            if ref in self.taken_avatars(exclude_player=player_id):
                raise CmdError("Этот аватар уже занят", "avatar_taken")
        elif kind == "photo":
            if not re.fullmatch(r"p_[0-9a-f]{16}\.png", ref or "") or not (self.data_dir / "avatars" / ref).exists():
                raise CmdError("Фото профиля не найдено, загрузите ещё раз", "bad_avatar")
        else:
            raise CmdError("Неизвестный тип профиля", "bad_avatar")

    def join(self, name: str, avatar_kind: str, avatar_ref: str, as_host: bool = False) -> Player:
        name = normalize_name(name)
        if not 1 <= len(name) <= NAME_MAX:
            raise CmdError(f"Имя должно быть от 1 до {NAME_MAX} символов", "bad_name")
        existing = self.player_by_name(name)
        if existing:
            raise CmdError(
                "Это имя уже занято", "name_taken", can_claim=not existing.connected, name=existing.name
            )
        self._check_avatar(avatar_kind, avatar_ref)
        if as_host and any(p.is_host for p in self.players.values()):
            raise CmdError("Профиль ведущего уже есть", "host_exists")
        in_scoring = self.settings["host_in_scoring"] if as_host else True
        token = secrets.token_urlsafe(18)
        now = self.clock.now()
        cur = self.db.execute(
            "INSERT INTO players(token, name, name_key, avatar_kind, avatar_ref, is_host, in_scoring, created_at) "
            "VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
            (token, name, name.casefold(), avatar_kind, avatar_ref, int(as_host), int(in_scoring), now),
        )
        p = Player(cur.lastrowid, token, name, avatar_kind, avatar_ref, as_host, bool(in_scoring), now)
        self.players[p.id] = p
        self.log(f"{p.name} вошёл в игру" + (" (ведущий)" if as_host else ""), p.id)
        self.players_changed()
        return p

    def claim(self, name: str) -> Player:
        """«Это я?»: вернуть токен отключённого игрока с этим именем."""
        p = self.player_by_name(name)
        if not p:
            raise CmdError("Игрок с таким именем не найден", "not_found")
        if p.connected:
            raise CmdError("Этот игрок сейчас в сети", "name_taken", can_claim=False)
        self.log(f"{p.name} вернулся на новом устройстве", p.id)
        return p

    def update_profile(self, player_id: int, avatar_kind: str, avatar_ref: str) -> None:
        p = self.players[player_id]
        self._check_avatar(avatar_kind, avatar_ref, player_id)
        p.avatar_kind, p.avatar_ref = avatar_kind, avatar_ref
        self.db.execute(
            "UPDATE players SET avatar_kind=?, avatar_ref=? WHERE id=?", (avatar_kind, avatar_ref, player_id)
        )
        self.log(f"{p.name} сменил аватар", p.id)
        self.players_changed()
        self.emit("player", {"t": "me", "me": self.me(player_id)}, player_id=player_id)

    def set_connected(self, player_id: int, delta: int) -> None:
        p = self.players.get(player_id)
        if not p:
            return
        was = p.connected
        p.connections = max(0, p.connections + delta)
        if was != p.connected:
            self.players_changed()

    def players_changed(self) -> None:
        self.emit({"host", "tv"}, {"t": "players", "players": self.players_public(with_scores=True)})
        self.emit("carve", {"t": "players", "players": self.players_public(with_scores=False)})
        self.emit("player", {"t": "avatars_taken", "taken": self.taken_avatars()})
        if self.settings["scene"] == "bomb":
            self.emit_module("bomb")  # круг игроков на ТВ и порядок на /host зависят от того, кто в сети

    def players_public(self, with_scores: bool) -> list[dict]:
        totals = self.totals() if with_scores else {}
        pumpkins = {r["player_id"]: r["version"] for r in self.db.all("SELECT player_id, version FROM pumpkins")}
        out = []
        for p in self.players.values():
            d = {
                "id": p.id, "name": p.name, "avatar_url": p.avatar_url, "avatar_kind": p.avatar_kind,
                "is_host": p.is_host, "in_scoring": p.in_scoring, "connected": p.connected,
                "pumpkin_version": pumpkins.get(p.id, 0),
            }
            if with_scores:
                d["score"] = totals.get(p.id, 0)
            out.append(d)
        return out

    def me(self, player_id: int) -> dict:
        p = self.players[player_id]
        return {
            "id": p.id, "name": p.name, "avatar_url": p.avatar_url, "avatar_kind": p.avatar_kind,
            "avatar_ref": p.avatar_ref, "is_host": p.is_host, "in_scoring": p.in_scoring,
            "score": None if self.settings["hide_total"] else self.total(p.id),
        }

    # ------------------------------------------------------------------ сцены
    def set_scene(self, scene: str, payload: dict | None = None, force: bool = False) -> None:
        if scene not in SCENES:
            raise CmdError("Неизвестная сцена", "bad_scene")
        cur = self.settings["scene"]
        if self.scene_is_live(cur) and scene != cur and not force:
            raise CmdError(
                f"Сейчас идёт «{SCENE_TITLES[cur]}». Точно выйти?", "confirm_required"
            )
        now = self.clock.now()
        if cur != scene:
            if cur != "ambient":
                self._set("last_scene_end_at", now)
            if scene != "ambient":
                self.head_current = None
        self._set("scene", scene)
        self._set("scene_payload", payload or {})
        self._set("scene_started_at", now)
        self.log(f"Сцена: {SCENE_TITLES[scene]}")
        if scene == "rating_reveal" and self.finale.st["step"] < 0:
            self.finale.build_and_save()  # места считаются заново при каждом входе до первого раскрытия
        self.emit({"tv", "host", "player", "carve"}, {"t": "scene", **self.scene_info()})
        module = {"quiz": "quiz", "game": "game", "seeds": "seeds", "bomb": "bomb", "carve_vote": "vote", "carve_reveal": "vote",
                  "timer": "timer", "rating_reveal": "finale", "slideshow": "finale",
                  "final_photo": "finale"}.get(scene)
        if module:
            self.emit_module(module)  # содержит и next_step для /host
        else:
            self.emit("host", {"t": "next_step", "next_step": self.next_step()})

    def scene_info(self) -> dict:
        return {
            "scene": self.settings["scene"],
            "payload": self.settings["scene_payload"],
            "started_at": self.settings["scene_started_at"],
            "participating": self.settings["scene"] in PARTICIPATING,
            "title": SCENE_TITLES[self.settings["scene"]],
        }

    def scene_is_live(self, scene: str) -> bool:
        if scene == "quiz":
            return self.quiz.is_live()
        if scene == "game":
            return self.game.is_live()
        if scene == "seeds":
            return self.seeds.is_live()
        if scene == "bomb":
            return self.bomb.is_live()
        if scene == "carve_vote":
            return self.vote.is_live()
        return False

    def next_step(self) -> dict | None:
        """Контекстная кнопка «Следующий шаг» на /host: {label, cmd, args?, disabled?, hint?}."""
        cur = self.settings["scene"]
        owner = {"quiz": self.quiz, "game": self.game, "seeds": self.seeds, "bomb": self.bomb,
                 "carve_vote": self.vote,
                 "carve_reveal": self.vote,
                 "rating_reveal": self.finale}.get(cur)
        if owner:
            action = owner.next_action()
            if action:
                return action
        if cur == "ambient" and not self.quiz.st["done"]:
            return {"label": "Квиз →", "cmd": "set_scene", "args": {"scene": "quiz"}}
        i = RECOMMENDED.index(cur) if cur in RECOMMENDED else -1
        if i + 1 >= len(RECOMMENDED):
            return None
        nxt = RECOMMENDED[i + 1]
        return {"label": f"{SCENE_TITLES[nxt]} →", "cmd": "set_scene", "args": {"scene": nxt}}

    # ------------------------------------------------------------------ рассылки
    def emit_settings(self) -> None:
        self.emit({"tv", "host", "player", "carve"}, {"t": "settings", "settings": self.public_settings()})

    def emit_facts(self) -> None:
        self.emit("player", {"t": "facts", "facts": self.facts_public(), "locked": self.quiz.facts_locked()})

    def emit_module(self, name: str, roles: set[str] | None = None, player_id: int | None = None) -> None:
        """Разослать состояние модуля сцены: tv и host — общий вид, каждому игроку — свой."""
        mod = self.modules[name]
        roles = roles or {"tv", "host", "player"}
        for role in ("tv", "host"):
            if role in roles:
                self.emit(role, {"t": name, name: mod.public(role)})
        if "player" in roles:
            for pid in ([player_id] if player_id else list(self.players)):
                self.emit("player", {"t": name, name: mod.public("player", pid)}, player_id=pid)
        if "host" in roles:
            self.emit("host", {"t": "next_step", "next_step": self.next_step()})

    def emit_quiz(self, roles: set[str] | None = None) -> None:
        self.emit_module("quiz", roles)

    def modules_snapshot(self, role: str, player_id: int | None = None) -> dict:
        return {name: mod.public(role, player_id) for name, mod in self.modules.items()}

    def tick(self) -> None:
        """Таймеры всех модулей (вызывается из app.tick_loop по серверному времени)."""
        # каждый модуль отдельно: сбой одного не должен останавливать остальные таймеры
        for name, fn in (("quiz", self.quiz.tick), ("game", self.game.tick), ("seeds", self.seeds.tick),
                         ("bomb", self.bomb.tick),
                         ("timer", self.timer.tick),
                         ("photos", self.photos.tick), ("head", self.head_tick)):
            try:
                fn()
            except Exception:  # noqa: BLE001
                log.exception("Сбой таймера модуля %s", name)

    # ------------------------------------------------------------------ настройки ведущего
    HOST_SETTINGS = {
        "host_in_scoring": bool, "hide_total": bool, "head_mode": str, "head_enabled": bool,
        "head_interval_minutes": float, "light_mode": bool, "new_photo_card": bool, "shots_enabled": bool,
        "alley_slides": bool, "shots_min_minutes": float, "shots_max_minutes": float,
    }

    def set_setting(self, key: str, value: Any) -> None:
        if key not in self.HOST_SETTINGS:
            raise CmdError("Неизвестная настройка", "bad_setting")
        value = self.HOST_SETTINGS[key](value)
        if key == "head_mode" and value not in ("quiet", "loud"):
            raise CmdError("Режим головы: quiet или loud", "bad_setting")
        if key == "head_interval_minutes" and not 1 <= value <= 60:
            raise CmdError("Интервал от 1 до 60 минут", "bad_setting")
        if key in ("shots_min_minutes", "shots_max_minutes") and not 1 <= value <= 120:
            raise CmdError("Интервал кадров от 1 до 120 минут", "bad_setting")
        if key == "host_in_scoring":
            if self.settings["quiz_started"]:
                raise CmdError("Квиз уже начался, зачёт ведущего менять нельзя", "locked")
            for p in self.players.values():
                if p.is_host:
                    p.in_scoring = value
                    self.db.execute("UPDATE players SET in_scoring=? WHERE id=?", (int(value), p.id))
            self.players_changed()
        self._set(key, value)
        if key == "head_interval_minutes":
            self._head_schedule()
        # «от» больше «до»: подтянуть вторую границу, затем пересчитать срок следующего кадра
        if key == "shots_min_minutes" and value > self.settings["shots_max_minutes"]:
            self._set("shots_max_minutes", value)
        if key == "shots_max_minutes" and value < self.settings["shots_min_minutes"]:
            self._set("shots_min_minutes", value)
        if key in ("shots_min_minutes", "shots_max_minutes", "shots_enabled"):
            self.photos.schedule_next()
        self.log(f"Настройка {key} = {value}")
        self.emit_settings()
        if key == "hide_total":
            for pid in self.players:
                self.emit("player", {"t": "me", "me": self.me(pid)}, player_id=pid)
            if self.settings["scene"] == "quiz":
                self.emit_quiz()  # рейтинг на экране мог показывать общий итог

    def public_settings(self) -> dict:
        keys = list(self.HOST_SETTINGS) + ["quiz_started", "carve_locked", "shot_next_at"]
        return {k: self.settings[k] for k in keys}

    def adjust_score(self, player_id: int, amount: int, note: str) -> None:
        p = self.players.get(int(player_id))
        if not p:
            raise CmdError("Нет такого игрока", "not_found")
        amount = int(amount)
        if amount == 0:
            raise CmdError("Укажите число, отличное от нуля", "bad_amount")
        note = str(note or "").strip()[:200]
        self.add_points(p.id, "manual", amount, ref="host", note=note)
        sign = "+" if amount > 0 else ""
        self.log(f"Ручная правка: {p.name} {sign}{amount}" + (f" ({note})" if note else ""), p.id)

    # ------------------------------------------------------------------ голова-тыква (модуль 04)
    def _head_schedule(self, initial: bool = False) -> None:
        """Следующее появление головы: через интервал ± разброс (минуты)."""
        if initial and self.settings.get("head_next_at"):
            return
        h = self.cfg["head"]
        minutes = float(self.settings["head_interval_minutes"]) + random.uniform(
            -float(h["interval_jitter_minutes"]), float(h["interval_jitter_minutes"]))
        self._set("head_next_at", self.clock.now() + max(0.5, minutes) * 60)

    def head_tick(self) -> None:
        if not self.settings["head_enabled"] or self.settings["scene"] != "ambient":
            return
        if self.head_snapshot() or self.photos.shot_running:
            return
        now = self.clock.now()
        gap = float(self.cfg["head"]["min_gap_after_scene_minutes"]) * 60
        if now < self.settings["head_next_at"] or now < (self.settings["last_scene_end_at"] or 0) + gap:
            return
        try:
            self.head_call()
        except CmdError as e:
            self.log(f"Голова: {e}")
            self._head_schedule()

    def head_speak(self) -> None:
        """«Озвучить»: проиграть озвучку текущего факта с начала и продлить показ."""
        h = self.head_snapshot()
        if not h:
            raise CmdError("Сейчас на экране нет факта", "no_head")
        if not h.get("audio_url"):
            raise CmdError("У этого факта нет озвучки", "no_audio")
        self.emit("tv", {"t": "head_speak"})

    def head_call(self) -> dict:
        if self.settings["scene"] != "ambient":
            raise CmdError("Голова работает только в ambient", "wrong_scene")
        facts = self.content.facts()
        if not facts:
            raise CmdError("В content/facts.yaml нет фактов", "no_facts")
        shown = {r["id"] for r in self.db.all("SELECT id FROM facts WHERE shown_at IS NOT NULL")}
        pool = [f for f in facts if f["id"] not in shown]
        if not pool:  # показаны все: цикл заново (но отметки для раунда 4 остаются)
            pool = facts
        if self.head_current:
            pool = [f for f in pool if f["id"] != self.head_current["fact_id"]] or pool
        fact = random.choice(pool)
        audio = fact.get("audio")
        audio_path = self.content.dir / "audio" / str(audio) if audio else None
        has_audio = bool(audio_path) and audio_path.exists()
        lipsync = audio_path.with_suffix(".lipsync.json") if has_audio else None
        self.head_current = {
            "fact_id": fact["id"],
            "text": fact["text"],
            "audio_url": f"/content/audio/{audio}" if has_audio else None,
            "lipsync_url": f"/content/audio/{lipsync.name}" if lipsync and lipsync.exists() else None,
            "mode": self.settings["head_mode"],
            "seconds": HEAD_QUIET_SECONDS,
            "called_at": self.clock.now(),
        }
        self.log(f"Голова: факт {fact['id']}")
        self.emit({"tv", "host"}, {"t": "head", "head": self.head_current})
        self._head_schedule()
        return self.head_current

    def head_skip(self) -> None:
        self.head_current = None
        self.emit({"tv", "host"}, {"t": "head", "head": None})

    def head_shown(self, fact_id: str) -> None:
        """Пузырь появился на /tv: факт считается показанным."""
        if not self.content.fact(fact_id):
            return
        row = self.db.one("SELECT shown_at FROM facts WHERE id=?", (fact_id,))
        if row and row["shown_at"]:
            return
        self.db.execute(
            "INSERT INTO facts(id, shown_at) VALUES(?, ?) ON CONFLICT(id) DO UPDATE SET shown_at=excluded.shown_at",
            (fact_id, self.clock.now()),
        )
        self.emit_facts()

    def head_done(self, fact_id: str) -> None:
        if self.head_current and self.head_current["fact_id"] == fact_id:
            self.head_current = None
            self.emit("host", {"t": "head", "head": None})

    def facts_public(self) -> list[dict]:
        # во время раунда 4 тексты не отдаются вовсе (вкладка «Факты» закрыта)
        locked = self.quiz.facts_locked()
        shown = set() if locked else {r["id"] for r in self.db.all("SELECT id FROM facts WHERE shown_at IS NOT NULL")}
        out = []
        for i, f in enumerate(self.content.facts(), 1):
            out.append({"n": i, "text": f["text"] if f["id"] in shown else None})
        return out

    def head_snapshot(self) -> dict | None:
        h = self.head_current
        if h and self.clock.now() - h["called_at"] > h["seconds"] + 120:
            self.head_current = h = None
        return h

    # ------------------------------------------------------------------ сброс
    def reset_evening(self) -> str:
        dest = copy_before_reset(self.db, self.data_dir)
        self.db.wipe()
        for sub in ("avatars", "uploads", "photos", "pumpkins"):
            shutil.rmtree(self.data_dir / sub, ignore_errors=True)
        self.head_current = None
        self._load()
        for mod in (self.quiz, self.photos, self.game, self.seeds, self.bomb, self.vote, self.timer, self.finale):
            mod.reload()
        self._head_schedule()
        self.log(f"Вечер сброшен, копия: {dest.name}")
        if self.hub:
            self.hub.reset_all()
        return dest.name
