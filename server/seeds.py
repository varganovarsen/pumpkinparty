"""Охота за семечками (модуль 09).

Ведущий заранее прячет по комнате бумажные семечки с кодом из цифр (content/seeds.yaml,
лист для печати — /seeds/print). Отдельный раунд по таймеру: гости вводят найденные коды
на телефоне. Каждую семечку засчитывают только первому, кто ввёл код; очки сразу идут в
общий зачёт (ledger, source «seeds»). Подбор наугад гасится паузой после нескольких
неверных кодов подряд.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

from .state import CmdError

if TYPE_CHECKING:
    from .state import Evening

COUNTDOWN = 3.5   # с: отсчёт 3-2-1 перед стартом
FEED_MAX = 8      # последних находок в ленте на ТВ
KINDS = ("regular", "golden", "rainbow")
KIND_TITLES = {"regular": "семечка", "golden": "золотая семечка", "rainbow": "радужная мегасемка"}


def normalize_code(raw) -> str:
    return re.sub(r"\D", "", str(raw or ""))


def _empty() -> dict:
    return {"phase": "idle", "start_at": None, "end_at": None, "found": {}, "fails": {}, "feed": []}


class Seeds:
    def __init__(self, ev: Evening):
        self.ev = ev
        self.cfg = ev.cfg["seeds"]
        self.reload()

    def reload(self) -> None:
        self.st = self.ev.settings.get("seeds") or _empty()

    def save(self) -> None:
        self.ev._set("seeds", self.st)

    @property
    def phase(self) -> str:
        return self.st["phase"]

    def is_live(self) -> bool:
        return self.phase in ("countdown", "running")

    def seeds(self) -> dict[str, dict]:
        """Семечки из контента по коду."""
        return {s["code"]: s for s in self.ev.content.seeds()}

    def points(self, kind: str) -> int:
        return int(self.cfg["points"].get(kind, 0))

    def _changed(self, log: str | None = None) -> None:
        self.save()
        if log:
            self.ev.log(log)
        self.ev.emit_module("seeds")

    # ------------------------------------------------------------------ команды ведущего
    def start(self) -> None:
        if self.is_live():
            raise CmdError("Охота уже идёт", "busy")
        if self.phase == "finished":
            raise CmdError("Охота уже прошла (сброс — в аварийном разделе)", "done")
        if not self.seeds():
            raise CmdError("Нет семечек: заполните content/seeds.yaml (tools/make_seeds.py)", "no_seeds")
        now = self.ev.clock.now()
        seconds = float(self.cfg["minutes"]) * 60
        self.st.update(phase="countdown", start_at=now + COUNTDOWN, end_at=now + COUNTDOWN + seconds)
        self._changed(f"Охота за семечками: старт, {self.cfg['minutes']:g} мин")

    def add_time(self, seconds: float) -> None:
        if not self.is_live():
            raise CmdError("Охота не идёт", "not_live")
        seconds = float(seconds)
        if not -600 <= seconds <= 600:
            raise CmdError("Слишком большое изменение", "bad_amount")
        self.st["end_at"] = max(self.ev.clock.now() + 1, self.st["end_at"] + seconds)
        self._changed(f"Охота: время {'+' if seconds > 0 else ''}{seconds:g} с")

    def stop(self) -> None:
        if not self.is_live():
            raise CmdError("Охота не идёт", "not_live")
        self._finish("Охота за семечками: остановлена ведущим")

    def reset(self) -> None:
        self.ev.db.execute("DELETE FROM ledger WHERE source='seeds'")
        self.st = _empty()
        self.ev.scores_changed(set(self.ev.players))
        self._changed("Аварийно: охота за семечками сброшена, очки за семечки удалены")

    # ------------------------------------------------------------------ игроки
    def enter(self, player_id: int, raw) -> dict:
        p = self.ev.players.get(player_id)
        if not p:
            raise CmdError("Нет такого игрока", "not_found")
        if self.phase == "countdown":
            raise CmdError("Ещё не началось — ждём старта", "not_started")
        if self.phase != "running":
            raise CmdError("Охота сейчас не идёт", "closed")
        if p.is_host and not self.cfg["host_can_play"]:
            raise CmdError("Ведущий прятал семечки — искать их нельзя", "host")
        now = self.ev.clock.now()
        fail = self.st["fails"].setdefault(str(player_id), {"n": 0, "until": 0})
        if now < fail["until"]:
            raise CmdError("Пауза после неверных кодов", "cooldown", until_ms=int(fail["until"] * 1000))
        code = normalize_code(raw)
        seed = self.seeds().get(code)
        if not seed:
            fail["n"] += 1
            extra = {}
            if fail["n"] >= int(self.cfg["wrong_limit"]):
                fail["n"] = 0
                fail["until"] = now + float(self.cfg["cooldown_seconds"])
                extra["until_ms"] = int(fail["until"] * 1000)
            self.save()
            raise CmdError("Нет такой семечки", "wrong", **extra)
        got = self.st["found"].get(code)
        if got:
            if got["player_id"] == player_id:
                raise CmdError("Эта семечка уже твоя", "mine")
            who = self.ev.players.get(got["player_id"])
            raise CmdError(f"Эту уже нашли: {who.name if who else 'кто-то'}", "taken")
        fail["n"] = 0
        kind = seed["kind"]
        pts = self.points(kind)
        self.st["found"][code] = {"player_id": player_id, "ts": now, "kind": kind}
        self.st["feed"] = (self.st["feed"] + [{"player_id": player_id, "kind": kind, "points": pts, "ts": now}])[-FEED_MAX:]
        if p.in_scoring and pts:
            self.ev.add_points(player_id, "seeds", pts, ref=code)
        self.save()
        self.ev.log(f"{p.name}: {KIND_TITLES[kind]} {code} (+{pts})", p.id)
        self.ev.emit({"tv", "host"}, {"t": "seed_found", "name": p.name, "avatar_url": p.avatar_url,
                                      "kind": kind, "points": pts})
        if len(self.st["found"]) >= len(self.seeds()):
            self._finish("Охота за семечками: найдены все")
        else:
            self.ev.emit_module("seeds")
        return {"kind": kind, "points": pts}

    # ------------------------------------------------------------------ таймер
    def tick(self) -> None:
        now = self.ev.clock.now()
        if self.phase == "countdown" and now >= self.st["start_at"]:
            self.st["phase"] = "running"
            self._changed()
        elif self.phase == "running" and now >= self.st["end_at"]:
            self._finish("Охота за семечками: время вышло")

    def _finish(self, log: str) -> None:
        self.st["phase"] = "finished"
        self.st["end_at"] = min(self.st["end_at"], self.ev.clock.now())  # досрочно: таймер на экранах встаёт
        self._changed(log)

    # ------------------------------------------------------------------ для клиентов
    def board(self) -> list[dict]:
        rows: dict[int, dict] = {}
        for f in self.st["found"].values():
            p = self.ev.players.get(f["player_id"])
            if not p:
                continue
            r = rows.setdefault(p.id, {"player_id": p.id, "name": p.name, "avatar_url": p.avatar_url,
                                       "in_scoring": p.in_scoring, "count": 0, "points": 0,
                                       "kinds": {k: 0 for k in KINDS}})
            r["count"] += 1
            r["points"] += self.points(f["kind"])
            r["kinds"][f["kind"]] += 1
        return sorted(rows.values(), key=lambda r: (-r["points"], -r["count"], r["name"]))

    def counts(self) -> dict:
        out = {k: {"total": 0, "found": 0} for k in KINDS}
        for code, s in self.seeds().items():
            out[s["kind"]]["total"] += 1
            if code in self.st["found"]:
                out[s["kind"]]["found"] += 1
        return out

    def public(self, role: str, player_id: int | None = None) -> dict:
        st = self.st
        feed = []
        for f in st["feed"]:
            p = self.ev.players.get(f["player_id"])
            feed.append({**f, "name": p.name if p else "?", "avatar_url": p.avatar_url if p else ""})
        out = {
            "phase": st["phase"],
            "start_at_ms": int(st["start_at"] * 1000) if st["start_at"] else None,
            "end_at_ms": int(st["end_at"] * 1000) if st["end_at"] else None,
            "minutes": float(self.cfg["minutes"]), "points": dict(self.cfg["points"]),
            "counts": self.counts(), "board": self.board(), "feed": feed,
            "code_len": max((len(c) for c in self.seeds()), default=4),
        }
        if role == "player" and player_id is not None:
            p = self.ev.players.get(player_id)
            mine = [f for f in st["found"].values() if f["player_id"] == player_id]
            fail = st["fails"].get(str(player_id)) or {}
            out["my"] = {
                "can_play": bool(p) and (not p.is_host or bool(self.cfg["host_can_play"])),
                "count": len(mine), "points": sum(self.points(f["kind"]) for f in mine),
                "kinds": {k: sum(1 for f in mine if f["kind"] == k) for k in KINDS},
                "cooldown_until_ms": int(fail["until"] * 1000) if fail.get("until", 0) > self.ev.clock.now() else None,
            }
        if role == "host":
            names = {pid: p.name for pid, p in self.ev.players.items()}
            out["seeds"] = [{"code": s["code"], "kind": s["kind"], "place": s.get("place", ""),
                             "found_by": names.get(st["found"][s["code"]]["player_id"]) if s["code"] in st["found"] else None}
                            for s in self.ev.content.seeds()]
            out["next"] = self.next_action()
        return out

    def next_action(self) -> dict | None:
        if self.phase == "idle":
            return {"label": f"Старт охоты ({self.cfg['minutes']:g} мин)", "cmd": "seeds_start"}
        return None
