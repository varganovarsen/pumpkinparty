"""Игра «Бомба» (модуль 10).

ТВ выбирает случайную тему (content/bomb.yaml). Бомба ходит по кругу в порядке, который
задаёт ведущий: у кого бомба, тот вслух называет слово на тему и жмёт «Передать» на
телефоне. Не успел — взорвался и выбыл. Время на ход уменьшается с каждым кругом
(5 → 4 → 3 … до минимума, настраивается на /host). Последний оставшийся — победитель.
Первые пять мест раунда получают очки (ledger, source «bomb»), раундов три.
"""
from __future__ import annotations

import random
from typing import TYPE_CHECKING

from .state import CmdError

if TYPE_CHECKING:
    from .state import Evening

COUNTDOWN = 3.5    # с: отсчёт 3-2-1 перед первым ходом
ROULETTE = 4.0     # с: рулетка тем на ТВ, потом тема видна всем
BOOM_PAUSE = 3.0   # с: взрыв на экране, потом бомба у следующего
LIVE_PHASES = ("countdown", "running", "boom")


def _empty() -> dict:
    return {
        "phase": "idle",          # idle | topic | countdown | running | boom | round_over
        "round": 0,
        "topic": None, "topic_reveal_at": None, "topics_used": [],
        "order": [],              # порядок хода, задаёт ведущий (все игроки)
        "alive": [],              # кто ещё в раунде, по порядку хода
        "out": [],                # выбывшие в порядке взрыва
        "holder": None, "next_holder": None,
        "start_at": None, "turn_started": None, "deadline": None, "turn_seconds": None,
        "lap": 0, "lap_passes": 0, "passes": 0,
        "boom": None, "resume_at": None,
        "results": {},            # номер раунда -> [{player_id, place, points}]
        "cfg": None,              # время на ход: правки ведущего поверх config.yaml
    }


class Bomb:
    def __init__(self, ev: Evening):
        self.ev = ev
        self.cfg = ev.cfg["bomb"]
        self.reload()

    def reload(self) -> None:
        self.st = self.ev.settings.get("bomb") or _empty()

    def save(self) -> None:
        self.ev._set("bomb", self.st)

    @property
    def phase(self) -> str:
        return self.st["phase"]

    @property
    def rounds(self) -> int:
        return int(self.cfg["rounds"])

    def is_live(self) -> bool:
        return self.phase in LIVE_PHASES

    def done(self) -> bool:
        return self.phase == "round_over" and self.st["round"] >= self.rounds

    def timing(self) -> dict:
        """Время на ход: стартовое, на сколько короче каждый круг, минимум."""
        base = {k: float(self.cfg[k]) for k in ("start_seconds", "step_seconds", "min_seconds")}
        return {**base, **(self.st["cfg"] or {})}

    def turn_seconds(self) -> float:
        t = self.timing()
        return max(t["min_seconds"], t["start_seconds"] - self.st["lap"] * t["step_seconds"])

    def points(self) -> list[int]:
        return [int(x) for x in self.cfg["points"]]

    def can_play(self, player_id: int) -> bool:
        p = self.ev.players.get(player_id)
        return bool(p) and (not p.is_host or bool(self.cfg["host_can_play"]))

    def _changed(self, log: str | None = None) -> None:
        self.save()
        if log:
            self.ev.log(log)
        self.ev.emit_module("bomb")

    # ------------------------------------------------------------------ порядок хода
    def order(self) -> list[int]:
        """Порядок ведущего + новые игроки в конце (по времени входа)."""
        known = [pid for pid in self.st["order"] if pid in self.ev.players]
        return known + [pid for pid in self.ev.players if pid not in known]

    def lineup(self) -> list[int]:
        """Кто сыграет, если стартовать сейчас: в сети и может играть, в порядке ведущего."""
        return [pid for pid in self.order() if self.ev.players[pid].connected and self.can_play(pid)]

    def set_order(self, ids) -> None:
        if self.is_live():
            raise CmdError("Порядок меняется между раундами", "busy")
        try:
            ids = [int(x) for x in ids]
        except (TypeError, ValueError):
            raise CmdError("Неверный порядок", "bad_order") from None
        if sorted(ids) != sorted(set(ids)) or not set(ids) <= set(self.ev.players):
            raise CmdError("Неверный порядок", "bad_order")
        self.st["order"] = ids
        self._changed()

    def set_timing(self, start_seconds, step_seconds, min_seconds) -> None:
        try:
            t = {"start_seconds": float(start_seconds), "step_seconds": float(step_seconds),
                 "min_seconds": float(min_seconds)}
        except (TypeError, ValueError):
            raise CmdError("Нужны числа", "bad_timing") from None
        if not 2 <= t["start_seconds"] <= 60:
            raise CmdError("Время первого круга — от 2 до 60 с", "bad_timing")
        if not 0 <= t["step_seconds"] <= 10:
            raise CmdError("Шаг — от 0 до 10 с", "bad_timing")
        if not 1 <= t["min_seconds"] <= t["start_seconds"]:
            raise CmdError("Минимум — от 1 с и не больше первого круга", "bad_timing")
        self.st["cfg"] = t
        self._changed(f"Бомба: время на ход {t['start_seconds']:g} с, −{t['step_seconds']:g} за круг, "
                      f"минимум {t['min_seconds']:g} с")

    # ------------------------------------------------------------------ раунд
    def pick_topic(self) -> None:
        """Новый раунд (или другая тема до старта): рулетка тем на ТВ."""
        if self.is_live():
            raise CmdError("Раунд уже идёт", "busy")
        if self.phase == "topic":
            pass  # другая тема для того же раунда
        elif self.st["round"] >= self.rounds:
            raise CmdError(f"Все {self.rounds} раунда сыграны (сброс — в аварийном разделе)", "done")
        else:
            self.st["round"] += 1
        topics = self.ev.content.bomb_topics()
        if not topics:
            raise CmdError("Нет тем: заполните content/bomb.yaml", "no_topics")
        used = set(self.st["topics_used"])
        pool = [t for t in topics if t not in used and t != self.st["topic"]] or \
               [t for t in topics if t != self.st["topic"]] or topics
        topic = random.choice(pool)
        self.st.update(phase="topic", topic=topic, topic_reveal_at=self.ev.clock.now() + ROULETTE,
                       alive=[], out=[], holder=None, boom=None)
        self._changed(f"Бомба: раунд {self.st['round']}, тема «{topic}»")

    def start(self) -> None:
        if self.phase != "topic":
            raise CmdError("Сначала выберите тему", "no_topic")
        alive = self.lineup()
        if len(alive) < 2:
            raise CmdError("Нужно хотя бы двое игроков в сети", "few_players")
        shift = (self.st["round"] - 1) % len(alive)  # каждый раунд начинает следующий по кругу
        alive = alive[shift:] + alive[:shift]
        now = self.ev.clock.now()
        self.st["topics_used"] = self.st["topics_used"] + [self.st["topic"]]
        self.st.update(phase="countdown", alive=alive, out=[], start_at=now + COUNTDOWN, holder=None,
                       next_holder=alive[0], lap=0, lap_passes=0, passes=0, boom=None, resume_at=None,
                       topic_reveal_at=min(self.st["topic_reveal_at"] or now, now))
        self._changed(f"Бомба: старт раунда {self.st['round']}, игроков {len(alive)}")

    def _turn(self, pid: int) -> None:
        now = self.ev.clock.now()
        sec = self.turn_seconds()
        self.st.update(phase="running", holder=pid, next_holder=None, turn_started=now,
                       deadline=now + sec, turn_seconds=sec, boom=None, resume_at=None)

    def _after(self, pid: int, alive: list[int]) -> int:
        i = alive.index(pid)
        return alive[(i + 1) % len(alive)]

    def pass_bomb(self, player_id: int) -> dict:
        if self.phase != "running":
            raise CmdError("Бомба сейчас не ходит", "closed")
        if self.st["holder"] != player_id:
            raise CmdError("Бомба не у тебя", "not_holder")
        if self.ev.clock.now() >= self.st["deadline"]:
            raise CmdError("Не успел — бомба взорвалась!", "late")
        alive = self.st["alive"]
        nxt = self._after(player_id, alive)
        self.st["passes"] += 1
        self.st["lap_passes"] += 1
        if self.st["lap_passes"] >= len(alive):  # бомба обошла всех: следующий круг короче
            self.st["lap"] += 1
            self.st["lap_passes"] = 0
        self._turn(nxt)
        self._changed()
        return {"to": nxt}

    def explode(self, by_host: bool = False) -> None:
        if self.phase != "running":
            raise CmdError("Бомба сейчас не ходит", "closed")
        now = self.ev.clock.now()
        pid = self.st["holder"]
        alive = list(self.st["alive"])
        nxt = self._after(pid, alive)
        alive.remove(pid)
        self.st["alive"] = alive
        self.st["out"] = self.st["out"] + [pid]
        place = len(alive) + 1
        self.st["boom"] = {"player_id": pid, "at": now, "place": place}
        p = self.ev.players.get(pid)
        name = p.name if p else "?"
        self.ev.log(f"Бомба: взрыв у игрока {name}" + (" (взорвал ведущий)" if by_host else "") + f", {place} место", pid)
        if self.st["lap_passes"] >= len(alive):
            self.st["lap"] += 1
            self.st["lap_passes"] = 0
        if len(alive) <= 1:
            self._finish_round()
            return
        self.st.update(phase="boom", holder=None, next_holder=nxt, deadline=None, resume_at=now + BOOM_PAUSE)
        self._changed()

    def _finish_round(self) -> None:
        r = self.st["round"]
        finishers = self.st["alive"] + list(reversed(self.st["out"]))  # 1 место — выживший
        pts = self.points()
        awards = iter(pts)
        rows = []
        for place, pid in enumerate(finishers, 1):
            p = self.ev.players.get(pid)
            amount = next(awards, 0) if p and p.in_scoring else 0
            rows.append({"player_id": pid, "place": place, "points": amount})
            if amount:
                self.ev.add_points(pid, "bomb", amount, ref=f"r{r}", notify=False)
        self.ev.scores_changed({row["player_id"] for row in rows})
        self.st["results"] = {**self.st["results"], str(r): rows}
        winner = self.ev.players.get(finishers[0]) if finishers else None
        self.st.update(phase="round_over", holder=None, next_holder=None, deadline=None, resume_at=None)
        self._changed(f"Бомба: раунд {r} окончен, победитель {winner.name if winner else '?'}")

    def abort(self) -> None:
        """Прервать раунд без очков: тема остаётся, раунд можно начать заново."""
        if not self.is_live():
            raise CmdError("Раунд не идёт", "not_live")
        self.st["topics_used"] = [t for t in self.st["topics_used"] if t != self.st["topic"]]
        self.st.update(phase="topic", alive=[], out=[], holder=None, next_holder=None, boom=None,
                       deadline=None, resume_at=None)
        self._changed(f"Бомба: раунд {self.st['round']} прерван ведущим, без очков")

    def reset(self) -> None:
        self.ev.db.execute("DELETE FROM ledger WHERE source='bomb'")
        keep = {"order": self.st["order"], "cfg": self.st["cfg"]}
        self.st = {**_empty(), **keep}
        self.ev.scores_changed(set(self.ev.players))
        self._changed("Аварийно: «Бомба» сброшена, очки за бомбу удалены")

    # ------------------------------------------------------------------ таймер
    def tick(self) -> None:
        now = self.ev.clock.now()
        if self.is_live() and self.ev.settings["scene"] != "bomb":
            self.abort()  # ведущий ушёл из сцены посреди раунда: за кадром никто не взрывается
        elif self.phase == "countdown" and now >= self.st["start_at"]:
            self._turn(self.st["next_holder"])
            self._changed()
        elif self.phase == "running" and now >= self.st["deadline"]:
            self.explode()
        elif self.phase == "boom" and now >= self.st["resume_at"]:
            self._turn(self.st["next_holder"])
            self._changed()

    # ------------------------------------------------------------------ для клиентов
    def _who(self, pid: int | None) -> dict | None:
        p = self.ev.players.get(pid) if pid is not None else None
        if not p:
            return None
        return {"player_id": p.id, "name": p.name, "avatar_url": p.avatar_url, "in_scoring": p.in_scoring}

    def places(self) -> dict[int, int]:
        """Места выбывших в текущем раунде (и выжившего после конца раунда)."""
        n = len(self.st["alive"]) + len(self.st["out"])
        out = {pid: n - i for i, pid in enumerate(self.st["out"])}
        if self.phase == "round_over" and self.st["alive"]:
            out[self.st["alive"][0]] = 1
        return out

    def ring(self) -> list[dict]:
        """Игроки раунда по порядку хода (до старта — кто сыграет)."""
        if self.phase in ("idle", "topic"):
            ids = self.lineup()
        else:
            # выбывшие остаются на своих местах в круге
            ids = [pid for pid in self.order() if pid in self.st["alive"] or pid in self.st["out"]]
        places = self.places()
        out = []
        for pid in ids:
            w = self._who(pid)
            if w:
                p = self.ev.players[pid]
                out.append({**w, "alive": pid not in self.st["out"], "place": places.get(pid),
                            "connected": p.connected})
        return out

    def totals(self) -> list[dict]:
        sums: dict[int, int] = {}
        for rows in self.st["results"].values():
            for r in rows:
                sums[r["player_id"]] = sums.get(r["player_id"], 0) + r["points"]
        out = [{**w, "points": s} for pid, s in sums.items() if (w := self._who(pid))]
        return sorted(out, key=lambda r: (-r["points"], r["name"]))

    def public(self, role: str, player_id: int | None = None) -> dict:
        st = self.st
        ms = lambda t: int(t * 1000) if t else None  # noqa: E731
        boom = st["boom"]
        last = st["results"].get(str(st["round"])) or []
        out = {
            "phase": st["phase"], "round": st["round"], "rounds": self.rounds, "done": self.done(),
            "topic": st["topic"], "topic_reveal_at_ms": ms(st["topic_reveal_at"]),
            "start_at_ms": ms(st["start_at"]), "deadline_ms": ms(st["deadline"]),
            "turn_started_ms": ms(st["turn_started"]), "turn_seconds": st["turn_seconds"],
            "resume_at_ms": ms(st["resume_at"]), "lap": st["lap"] + 1, "passes": st["passes"],
            "holder": self._who(st["holder"]), "next_holder": self._who(st["next_holder"]),
            "boom": {**(self._who(boom["player_id"]) or {}), "place": boom["place"]} if boom else None,
            "players": self.ring(), "alive_count": len(st["alive"]),
            "results": [{**(self._who(r["player_id"]) or {}), **r} for r in last if self._who(r["player_id"])]
            if st["phase"] == "round_over" else [],
            "totals": self.totals(), "timing": self.timing(), "points": self.points(),
        }
        if role == "player" and player_id is not None:
            in_round = player_id in st["alive"] or player_id in st["out"]
            out["my"] = {
                "player_id": player_id, "can_play": self.can_play(player_id),
                "in_round": in_round if st["phase"] not in ("idle", "topic") else player_id in self.lineup(),
                "alive": player_id in st["alive"],
                "holder": st["holder"] == player_id,
                "place": self.places().get(player_id),
                "points": sum(r["points"] for rows in st["results"].values() for r in rows if r["player_id"] == player_id),
            }
        if role == "tv" and st["phase"] == "topic":
            others = [t for t in self.ev.content.bomb_topics() if t != st["topic"]]
            out["reel"] = random.sample(others, min(12, len(others)))  # рулетка: мелькают перед выбранной
        if role == "host":
            out["order"] = [{"player_id": pid, "name": self.ev.players[pid].name,
                             "connected": self.ev.players[pid].connected, "can_play": self.can_play(pid)}
                            for pid in self.order()]
            out["next"] = self.next_action()
        return out

    def next_action(self) -> dict | None:
        if self.phase == "idle" or (self.phase == "round_over" and not self.done()):
            return {"label": f"Бомба: раунд {self.st['round'] + 1} — выбрать тему", "cmd": "bomb_topic"}
        if self.phase == "topic":
            return {"label": f"Старт раунда {self.st['round']}", "cmd": "bomb_start"}
        if self.is_live():
            return {"label": f"Идёт раунд {self.st['round']}…", "cmd": "bomb_start", "disabled": True}
        return None
