"""Таймер перерывов и финал (модуль 07): сцены timer, rating_reveal, slideshow, final_photo."""
from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING

from .state import CmdError

if TYPE_CHECKING:
    from .state import Evening

LABEL_MAX = 60


class Timer:
    """Обратный отсчёт; по нулю ничего не переключает сам."""

    def __init__(self, ev: Evening):
        self.ev = ev
        self.reload()

    def reload(self) -> None:
        self.st = self.ev.settings.get("timer") or {
            "label": "Перерыв", "end_at": None, "left": None, "running": False, "finished": False}

    def _changed(self, log: str | None = None) -> None:
        self.ev._set("timer", self.st)
        if log:
            self.ev.log(log)
        self.ev.emit_module("timer")

    def set(self, minutes, label: str | None = None) -> None:
        m = float(minutes)
        if not math.isfinite(m) or not 0 < m <= 180:
            raise CmdError("От 1 секунды до 3 часов", "bad_value")
        if label is not None:
            self.st["label"] = str(label).strip()[:LABEL_MAX]
        self.st.update(end_at=self.ev.clock.now() + m * 60, left=None, running=True, finished=False)
        self._changed(f"Таймер: {m:g} мин, «{self.st['label']}»")

    def pause(self, paused: bool) -> None:
        now = self.ev.clock.now()
        if paused and self.st["running"]:
            self.st.update(left=max(0.0, self.st["end_at"] - now), running=False)
        elif not paused and not self.st["running"] and self.st["left"] is not None:
            self.st.update(end_at=now + self.st["left"], left=None, running=True)
        else:
            return
        self._changed("Таймер на паузе" if paused else "Таймер продолжен")

    def add(self, seconds) -> None:
        s = float(seconds)
        if not math.isfinite(s) or not -3600 <= s <= 3600:
            raise CmdError("Неверное число секунд", "bad_value")
        if self.st["finished"]:  # время вышло, а ведущий дал ещё минуту — снова идёт
            self.st.update(end_at=self.ev.clock.now() + s, left=None, running=True, finished=False)
        elif self.st["running"]:
            self.st["end_at"] = max(self.ev.clock.now(), self.st["end_at"]) + s
        elif self.st["left"] is not None:
            self.st["left"] += s
        else:
            raise CmdError("Таймер не запущен", "wrong_phase")
        self.st["finished"] = False
        self._changed(f"Таймер: +{s:g} с")

    def label(self, text: str) -> None:
        self.st["label"] = str(text or "").strip()[:LABEL_MAX]
        self._changed()

    def tick(self) -> None:
        if self.st["running"] and not self.st["finished"] and self.ev.clock.now() >= self.st["end_at"]:
            self.st.update(finished=True, running=False, left=0.0)
            self._changed("Таймер: время вышло")

    def public(self, role: str, player_id: int | None = None) -> dict:
        st = self.st
        return {"label": st["label"], "running": st["running"], "finished": st["finished"],
                "end_at_ms": int(st["end_at"] * 1000) if st["end_at"] and st["running"] else None,
                "left_ms": int(st["left"] * 1000) if st["left"] is not None else None}


class Finale:
    """Общий рейтинг по одному (rating_reveal), пауза слайд-шоу, финальное фото на ТВ."""

    def __init__(self, ev: Evening):
        self.ev = ev
        self.reload()

    def reload(self) -> None:
        self.st = self.ev.settings.get("finale") or {"groups": [], "step": -1, "slideshow_paused": False,
                                                     "final_photo_id": None}

    def _changed(self, log: str | None = None) -> None:
        self.ev._set("finale", self.st)
        if log:
            self.ev.log(log)
        self.ev.emit_module("finale")

    # ------------------------------------------------------------------ общий рейтинг
    def build_groups(self) -> list[list[dict]]:
        totals = self.ev.totals()
        rows = []
        for p in self.ev.players.values():
            if not p.in_scoring:
                continue
            b = self.ev.breakdown(p.id)
            rows.append({
                "player_id": p.id, "name": p.name, "avatar_url": p.avatar_url, "total": totals.get(p.id, 0),
                "breakdown": {"quiz": b.get("quiz", 0) + b.get("quiz_bonus", 0), "game": b.get("game", 0),
                              "seeds": b.get("seeds", 0), "bomb": b.get("bomb", 0), "carve": b.get("carve", 0), "manual": b.get("manual", 0)},
            })
        groups: dict[int, list] = {}
        for r in rows:
            groups.setdefault(r["total"], []).append(r)
        ordered = []
        place = 1
        for total in sorted(groups, reverse=True):
            g = groups[total]
            random.shuffle(g)  # внутри ничьей порядок случайный
            for r in g:
                r["place"] = place
            place += len(g)
            ordered.append(g)
        ordered.reverse()  # раскрываем от последнего места к первому
        return ordered

    def build_and_save(self) -> None:
        self.st.update(groups=self.build_groups(), step=-1)
        self.ev._set("finale", self.st)

    def rating_start(self) -> None:
        self.build_and_save()
        self._changed("Общий рейтинг: готов к раскрытию")

    def rating_next(self) -> None:
        if not self.st["groups"]:
            self.rating_start()
        if self.st["step"] >= len(self.st["groups"]) - 1:
            raise CmdError("Все места уже раскрыты", "done")
        self.st["step"] += 1
        g = self.st["groups"][self.st["step"]]
        if self.st["step"] == len(self.st["groups"]) - 1 and self.ev.settings["hide_total"]:
            self.ev.set_setting("hide_total", False)  # интрига раскрыта: телефоны снова видят суммы
        self._changed(f"Рейтинг: {g[0]['place']} место — " + ", ".join(r["name"] for r in g))

    # ------------------------------------------------------------------ слайд-шоу и финальное фото
    def slideshow_pause(self, paused: bool) -> None:
        self.st["slideshow_paused"] = bool(paused)
        self._changed("Слайд-шоу на паузе" if paused else "Слайд-шоу продолжено")

    def set_final_photo(self, photo_id: int) -> None:
        self.st["final_photo_id"] = photo_id
        self._changed()

    def public(self, role: str, player_id: int | None = None) -> dict:
        st = self.st
        out = {"step": st["step"], "groups_total": len(st["groups"]),
               "slideshow_paused": st["slideshow_paused"], "final_photo": None}
        if st["final_photo_id"]:
            photo = self.ev.photos.get(st["final_photo_id"])
            out["final_photo"] = photo if photo and not photo["hidden"] else None  # скрытое ведущим не показываем
        shown = st["groups"] if role == "host" else st["groups"][: st["step"] + 1]
        out["groups"] = shown
        if role == "host":
            out["next"] = self.next_action()
        return out

    def next_action(self) -> dict | None:
        if self.ev.settings["scene"] == "rating_reveal":
            if not self.st["groups"] or self.st["step"] < len(self.st["groups"]) - 1:
                return {"label": "Раскрыть следующее место", "cmd": "rating_next"}
        return None
