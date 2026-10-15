"""Аллея тыкв, голосование и раскрытие (модуль 06, сцены carve_vote и carve_reveal).

Во время голосования тыквы анонимны: номера перемешаны, файлы отдаются по номеру
(/media/vote/<n>/<файл>), а не по игроку. Места: соревновательное ранжирование (1, 1, 3 …),
бонусы 500/300/100 за места 1-3; тыквы без голосов мест и бонусов не получают.
"""
from __future__ import annotations

import random
from pathlib import Path
from typing import TYPE_CHECKING

from . import carve
from .state import CmdError

if TYPE_CHECKING:
    from .state import Evening


def _empty() -> dict:
    return {"phase": "idle", "entries": [], "results": [], "reveal_step": -1, "revealed": False}


class Vote:
    def __init__(self, ev: Evening):
        self.ev = ev
        self.reload()

    def reload(self) -> None:
        self.st = self.ev.settings.get("vote") or _empty()

    def save(self) -> None:
        self.ev._set("vote", self.st)

    @property
    def phase(self) -> str:
        return self.st["phase"]

    def is_live(self) -> bool:
        return self.phase == "open"

    def _changed(self, log: str | None = None) -> None:
        self.save()
        if log:
            self.ev.log(log)
        self.ev.emit_module("vote")

    def entry_player(self, n: int) -> int | None:
        return next((e["player_id"] for e in self.st["entries"] if e["n"] == n), None)

    def file_for(self, n: int, name: str) -> Path | None:
        """Файл тыквы по анонимному номеру (только пока есть голосование)."""
        pid = self.entry_player(n)
        if pid is None or name not in carve.FILES:
            return None
        p = carve.pumpkin_dir(self.ev, pid) / name
        return p if p.exists() else None

    # ------------------------------------------------------------------ ведущий
    def start(self) -> None:
        if self.phase == "open":
            raise CmdError("Голосование уже идёт", "busy")
        if self.st["results"]:
            raise CmdError("Голосование уже прошло", "done")
        rows = self.ev.db.all("SELECT player_id, version FROM pumpkins WHERE version > 0")
        ids = [r["player_id"] for r in rows if r["player_id"] in self.ev.players]
        if not ids:
            raise CmdError("Нет ни одной сохранённой тыквы", "empty")
        random.shuffle(ids)
        versions = {r["player_id"]: r["version"] for r in rows}
        self.st.update(phase="open", entries=[{"n": i, "player_id": pid, "v": versions[pid]}
                                              for i, pid in enumerate(ids, 1)])
        self.ev.db.execute("DELETE FROM votes")
        self.ev._set("carve_locked", True)
        self._changed(f"Голосование за резьбу открыто, тыкв: {len(ids)}")

    def close(self) -> None:
        if self.phase != "open":
            raise CmdError("Голосование не идёт", "wrong_phase")
        counts = {e["n"]: 0 for e in self.st["entries"]}
        by_player = {e["player_id"]: e["n"] for e in self.st["entries"]}
        for r in self.ev.db.all("SELECT pumpkin_player_id FROM votes WHERE pumpkin_player_id IS NOT NULL"):
            n = by_player.get(r["pumpkin_player_id"])
            if n is not None:
                counts[n] += 1
        bonus = list(self.ev.cfg["carve"]["bonus"])
        ordered = sorted(self.st["entries"], key=lambda e: -counts[e["n"]])
        results = []
        place, prev = 0, None
        for i, e in enumerate(ordered, 1):
            v = counts[e["n"]]
            if v != prev:
                place, prev = i, v
            got = place if v > 0 else None
            b = bonus[got - 1] if got and got <= len(bonus) else 0
            results.append({"n": e["n"], "player_id": e["player_id"], "votes": v, "place": got, "bonus": b})
            if b and e["player_id"] in self.ev.players:
                self.ev.add_points(e["player_id"], "carve", b, ref="carve", notify=False)
        self.ev.scores_changed({r["player_id"] for r in results})
        self.st.update(phase="closed", results=results, reveal_step=-1)
        self._changed("Голосование закрыто: " + ", ".join(
            f"№{r['n']} {r['votes']} гол." for r in results))

    def reveal_next(self) -> None:
        if self.phase != "closed":
            raise CmdError("Сначала закройте голосование", "wrong_phase")
        n = len(self.st["results"])
        if self.st["reveal_step"] >= n:
            raise CmdError("Все тыквы уже раскрыты", "done")
        self.st["reveal_step"] += 1
        if self.st["reveal_step"] >= n:
            self.st["revealed"] = True
        self._changed()

    # ------------------------------------------------------------------ игроки
    def vote(self, voter_id: int, n) -> None:
        if self.phase != "open":
            raise CmdError("Голосование закрыто", "closed")
        target = None
        if n is not None:
            target = self.entry_player(int(n))
            if target is None:
                raise CmdError("Нет такой тыквы", "not_found")
            if target == voter_id:
                raise CmdError("За свою тыкву голосовать нельзя", "own")
        self.ev.db.execute(
            "INSERT INTO votes(voter_id, pumpkin_player_id) VALUES(?, ?) "
            "ON CONFLICT(voter_id) DO UPDATE SET pumpkin_player_id=excluded.pumpkin_player_id",
            (voter_id, target))
        self.ev.emit_module("vote", roles={"tv", "host"})
        self.ev.emit_module("vote", roles={"player"}, player_id=voter_id)

    # ------------------------------------------------------------------ для клиентов
    def _entry(self, e: dict, role: str) -> dict:
        base = f"/media/vote/{e['n']}"
        v = e.get("v", 0)
        d = {"n": e["n"], "shots": {k: f"{base}/{k}.jpg?v={v}" for k in carve.SHOT_NAMES}}
        if role in ("tv", "host"):
            d["masks"] = {k: f"{base}/{k}.png?v={v}" for k in carve.MASK_NAMES}
        return d

    def _result(self, r: dict) -> dict:
        p = self.ev.players.get(r["player_id"])
        return {**r, "name": p.name if p else "?", "avatar_url": p.avatar_url if p else ""}

    def public(self, role: str, player_id: int | None = None) -> dict:
        st = self.st
        out = {"phase": st["phase"], "entries": [self._entry(e, role) for e in st["entries"]],
               "revealed": st["revealed"], "reveal_step": st["reveal_step"]}
        votes = self.ev.db.all("SELECT voter_id, pumpkin_player_id FROM votes")
        out["voted_count"] = sum(1 for v in votes if v["pumpkin_player_id"] is not None)
        out["voters_total"] = len(self.ev.players)
        if st["phase"] == "closed":
            # порядок раскрытия: от последнего места к первому
            order = sorted(st["results"], key=lambda r: (r["place"] is not None, -(r["place"] or 0)))
            shown = order[: max(0, st["reveal_step"] + 1)] if role != "host" else order
            out["results"] = [self._result(r) for r in shown]
            out["total"] = len(order)
        if role == "player" and player_id is not None:
            own = next((e["n"] for e in st["entries"] if e["player_id"] == player_id), None)
            mine = next((v["pumpkin_player_id"] for v in votes if v["voter_id"] == player_id), "none")
            out["my"] = {"own": own,
                         "vote": None if mine in ("none", None) else next(
                             (e["n"] for e in st["entries"] if e["player_id"] == mine), None),
                         "abstained": mine is None}
        if role == "host":
            out["next"] = self.next_action()
        return out

    def next_action(self) -> dict | None:
        scene = self.ev.settings["scene"]
        if scene == "carve_vote":
            if self.phase == "idle":
                return {"label": "Открыть голосование", "cmd": "vote_start"}
            if self.phase == "open":
                return {"label": "Закрыть голосование", "cmd": "vote_close"}
        if scene == "carve_reveal" and self.phase == "closed" and not self.st["revealed"]:
            return {"label": "Раскрыть следующую", "cmd": "vote_reveal"}
        return None
