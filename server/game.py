"""Игра «Падающие тыквы» (модуль 05).

Сервер генерирует детерминированное расписание падений по seed и шлёт его всем одинаковым;
телефон симулирует игру локально и в конце присылает номера пойманных предметов. Сервер
пересчитывает счёт по расписанию (счёт не ниже 0, максимум 500) и пишет его в ledger.

Предмет: {i, t (появление, с от старта), x (0..1), kind, fall (с до линии корзины), land = t + fall}.
"""
from __future__ import annotations

import random
from typing import TYPE_CHECKING

from .state import CmdError

if TYPE_CHECKING:
    from .state import Evening

COUNTDOWN = 3.5        # с: отсчёт 3-2-1 перед стартом
GRACE = 5.0            # с после конца: ждём результаты с телефонов
MIN_GOOD_GAP = 0.45    # с между приземлениями «хороших» предметов: идеальная игра достижима
ROTTEN_GAP = 0.3       # с от гнилой до ближайшей хорошей
LIVE_EMIT = 1.0        # с: живой рейтинг на ТВ раз в секунду

PLANS = {
    # режим: (секунд, обычных, золотых, гнилых)
    "scored": (45, 30, 4, 12),
    "practice": (15, 8, 1, 3),
}


def fall_time(progress: float, kind: str) -> float:
    """Время падения: со временем быстрее; золотая падает быстрее остальных."""
    base = 3.2 - 1.5 * progress
    return round(base * (0.7 if kind == "golden" else 1.0), 3)


def generate(seed: int, mode: str) -> list[dict]:
    duration, n_regular, n_golden, n_rotten = PLANS[mode]
    rnd = random.Random(f"{mode}:{seed}")
    n_good = n_regular + n_golden
    first, last = 3.6, duration - 0.6
    # приземления хороших предметов: чаще к концу (частота растёт)
    lands = [first + (last - first) * (k / (n_good - 1)) ** 0.85 for k in range(n_good)]
    lands = [round(x + rnd.uniform(-0.12, 0.12), 3) for x in lands]
    lands.sort()
    for k in range(1, n_good):  # гарантированный зазор
        lands[k] = max(lands[k], round(lands[k - 1] + MIN_GOOD_GAP, 3))
    golden = set(rnd.sample(range(n_good // 3, n_good), n_golden))
    items = []
    for k, land in enumerate(lands):
        kind = "golden" if k in golden else "regular"
        fall = fall_time(land / duration, kind)
        items.append({"t": round(land - fall, 3), "x": round(rnd.uniform(0.08, 0.92), 3), "kind": kind,
                      "fall": fall, "land": land})
    # гнилые — в промежутках между хорошими, не ближе ROTTEN_GAP по времени
    gaps = [(lands[k], lands[k + 1]) for k in range(n_good - 1) if lands[k + 1] - lands[k] >= 2 * ROTTEN_GAP + 0.1]
    for a, b in rnd.sample(gaps, min(n_rotten, len(gaps))):
        land = round(rnd.uniform(a + ROTTEN_GAP, b - ROTTEN_GAP), 3)
        fall = fall_time(land / duration, "rotten")
        items.append({"t": round(land - fall, 3), "x": round(rnd.uniform(0.08, 0.92), 3), "kind": "rotten",
                      "fall": fall, "land": land})
    items.sort(key=lambda it: it["land"])
    for i, it in enumerate(items):
        it["i"] = i
    return items


def score_of(items: list[dict], caught: set[int], points: dict) -> int:
    """Счёт по пойманным предметам в порядке приземления; не опускается ниже 0."""
    s = 0
    for it in items:
        if it["i"] in caught:
            s = max(0, s + int(points[it["kind"]]))
    return s


def _empty() -> dict:
    return {"mode": None, "phase": "idle", "seed": None, "start_at": None, "end_at": None,
            "eligible": [], "results": {}, "live": {}, "scored_done": False}


class Game:
    def __init__(self, ev: Evening):
        self.ev = ev
        self.cfg = ev.cfg["game"]
        self.reload()
        self._last_live = 0.0
        self._live_dirty = False

    def reload(self) -> None:
        self.st = self.ev.settings.get("game") or _empty()
        self.items = generate(self.st["seed"], self.st["mode"]) if self.st["mode"] else []

    def save(self) -> None:
        self.ev._set("game", self.st)

    @property
    def phase(self) -> str:
        return self.st["phase"]

    def is_live(self) -> bool:
        return self.phase in ("countdown", "running")

    def _changed(self, log: str | None = None) -> None:
        self.save()
        if log:
            self.ev.log(log)
        self.ev.emit_module("game")

    # ------------------------------------------------------------------ команды ведущего
    def start(self, mode: str) -> None:
        if mode not in PLANS:
            raise CmdError("Неизвестный режим игры", "bad_mode")
        if self.is_live():
            raise CmdError("Игра уже идёт", "busy")
        if mode == "scored" and self.st["scored_done"]:
            raise CmdError("Зачётная попытка уже сыграна (сброс — в аварийном разделе)", "done")
        now = self.ev.clock.now()
        duration = PLANS[mode][0]
        seed = random.randrange(1, 10**9)
        eligible = [p.id for p in self.ev.players.values() if p.connected]
        self.st.update(mode=mode, phase="countdown", seed=seed, start_at=now + COUNTDOWN,
                       end_at=now + COUNTDOWN + duration, eligible=eligible, results={}, live={})
        self.items = generate(seed, mode)
        self._changed(f"Игра: {'тренировка' if mode == 'practice' else 'зачёт'}, игроков {len(eligible)}")

    def reset(self) -> None:
        self.ev.db.execute("DELETE FROM ledger WHERE source='game'")
        self.st = _empty()
        self.items = []
        self.ev.scores_changed(set(self.ev.players))
        self._changed("Аварийно: игра сброшена, очки за игру удалены")

    # ------------------------------------------------------------------ игроки
    def progress(self, player_id: int, score) -> None:
        if self.phase != "running" or player_id not in self.st["eligible"]:
            return
        try:
            s = max(0, min(int(score), int(self.cfg["max_points"])))
        except (TypeError, ValueError):
            return
        if self.st["live"].get(str(player_id)) != s:
            self.st["live"][str(player_id)] = s
            self._live_dirty = True

    def result(self, player_id: int, caught) -> dict:
        if self.phase not in ("running", "countdown") or player_id not in self.st["eligible"]:
            raise CmdError("Результат уже не принимается", "closed")
        if self.ev.clock.now() > self.st["end_at"] + GRACE:
            raise CmdError("Время игры вышло", "closed")
        if str(player_id) in self.st["results"]:
            return {"score": self.st["results"][str(player_id)]}
        valid = {it["i"] for it in self.items}
        got = {int(i) for i in (caught or []) if isinstance(i, int) and int(i) in valid}
        s = min(score_of(self.items, got, self.cfg["points"]), int(self.cfg["max_points"]))
        self.st["results"][str(player_id)] = s
        self.st["live"][str(player_id)] = s
        self._live_dirty = True
        self.save()
        p = self.ev.players.get(player_id)
        if p:
            self.ev.log(f"{p.name}: игра {s} очков" + (" (тренировка)" if self.st["mode"] == "practice" else ""), p.id)
        if all(str(pid) in self.st["results"] for pid in self.st["eligible"]):
            self._finish()
        return {"score": s}

    # ------------------------------------------------------------------ таймер
    def tick(self) -> None:
        now = self.ev.clock.now()
        if self.phase == "countdown" and now >= self.st["start_at"]:
            self.st["phase"] = "running"
            self._changed()
        elif self.phase == "running" and now >= self.st["end_at"] + GRACE:
            self._finish()
        if self._live_dirty and now - self._last_live >= LIVE_EMIT:
            self._live_dirty = False
            self._last_live = now
            self.ev.emit({"tv", "host"}, {"t": "game_live", "board": self.board()})

    def _finish(self) -> None:
        if self.phase not in ("running", "countdown"):
            return
        self.st["phase"] = "finished"
        if self.st["mode"] == "scored":
            for pid in self.st["eligible"]:
                s = self.st["results"].get(str(pid), 0)
                if s > 0 and pid in self.ev.players:
                    self.ev.add_points(pid, "game", s, ref="game", notify=False)
            self.st["scored_done"] = True
            self.ev.scores_changed(set(self.st["eligible"]))
        self._changed("Игра окончена")

    # ------------------------------------------------------------------ для клиентов
    def board(self) -> list[dict]:
        rows = []
        for pid in self.st["eligible"]:
            p = self.ev.players.get(pid)
            if p:
                rows.append({"player_id": pid, "name": p.name, "avatar_url": p.avatar_url,
                             "score": self.st["live"].get(str(pid), 0), "in_scoring": p.in_scoring,
                             "done": str(pid) in self.st["results"]})
        rows.sort(key=lambda r: -r["score"])
        return rows

    def public(self, role: str, player_id: int | None = None) -> dict:
        st = self.st
        out = {
            "mode": st["mode"], "phase": st["phase"], "scored_done": st["scored_done"],
            "start_at_ms": int(st["start_at"] * 1000) if st["start_at"] else None,
            "end_at_ms": int(st["end_at"] * 1000) if st["end_at"] else None,
            "board": self.board(),
        }
        if role == "player" and player_id is not None:
            eligible = player_id in st["eligible"]
            out["my"] = {"eligible": eligible, "result": st["results"].get(str(player_id))}
            if eligible and self.is_live():
                out["items"] = self.items
                out["points"] = self.cfg["points"]
        if role == "host":
            out["next"] = self.next_action()
        return out

    def next_action(self) -> dict | None:
        if self.is_live():
            return None
        if not self.st["scored_done"]:
            if self.st["mode"] is None:
                return {"label": "Тренировка (15 с)", "cmd": "game_start", "args": {"mode": "practice"}}
            return {"label": "Старт зачёта (45 с)", "cmd": "game_start", "args": {"mode": "scored"}}
        return None
