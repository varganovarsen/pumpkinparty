"""Квиз (модуль 02): 4 раунда, приём ответов по времени сервера, начисления в ledger.

Фазы: idle → intro (заставка раунда) → question → [judging, только раунд 4] → reveal
→ … → rating (итоги раунда) → intro следующего раунда … → после 4-го раунда квиз окончен.

Состояние хранится в настройке `quiz` (JSON), ответы — в таблице answers;
после перезапуска фаза и таймер восстанавливаются по серверному времени.
"""
from __future__ import annotations

import random
from typing import TYPE_CHECKING

from .state import CmdError

if TYPE_CHECKING:
    from .state import Evening

LETTERS = "ABCD"
ROUNDS = 4
TEXT_MAX = 200
LIVE_PHASES = {"question", "judging"}
ROUND4_TITLE = "Факты"


def _empty() -> dict:
    return {
        "round": 0,          # текущий (или последний сыгранный) раунд 1..4
        "phase": "idle",
        "rounds": {},        # "1": {"title", "questions": [...]} — фиксируется при старте раунда
        "q": -1,             # индекс вопроса в раунде
        "started_at": None,
        "deadline": None,
        "eligible": [],      # кто мог отвечать (был в игре на старте вопроса)
        "all_answered_at": None,
        "skipped": [],       # пропущенные вопросы (без начислений)
        "done": False,       # все 4 раунда сыграны
    }


class Quiz:
    def __init__(self, ev: Evening):
        self.ev = ev
        self.cfg = ev.cfg["quiz"]
        self.st = ev.settings.get("quiz") or _empty()

    # ------------------------------------------------------------------ служебное
    def reload(self) -> None:
        self.st = self.ev.settings.get("quiz") or _empty()

    def save(self) -> None:
        self.ev._set("quiz", self.st)

    @property
    def phase(self) -> str:
        return self.st["phase"]

    def round_data(self, r: int | None = None) -> dict | None:
        return self.st["rounds"].get(str(r or self.st["round"]))

    def question(self) -> dict | None:
        rd = self.round_data()
        if not rd or not 0 <= self.st["q"] < len(rd["questions"]):
            return None
        return rd["questions"][self.st["q"]]

    def is_live(self) -> bool:
        return self.phase in LIVE_PHASES

    def facts_locked(self) -> bool:
        """Вкладка «Факты» закрыта, пока идёт раунд 4."""
        return self.st["round"] == 4 and self.phase in ("intro", "question", "judging", "reveal")

    def _answers(self, qid: str) -> list:
        # порядок прихода на сервер = порядковый номер записи (не зависит от часов)
        return self.ev.db.all("SELECT * FROM answers WHERE qid=? ORDER BY id", (qid,))

    def _changed(self, log: str | None = None) -> None:
        self.save()
        if log:
            self.ev.log(log)
        self.ev.emit_quiz()

    # ------------------------------------------------------------------ подготовка раунда
    def _build_round(self, r: int) -> dict:
        if r <= 3:
            rounds = self.ev.content.quiz().get("rounds") or []
            if len(rounds) < r or not isinstance(rounds[r - 1], dict):
                raise CmdError(f"В quiz.yaml нет раунда {r}", "no_round")
            src = rounds[r - 1]
            qs = []
            for i, q in enumerate(src.get("questions") or [], 1):
                if not isinstance(q, dict) or not isinstance(q.get("options"), list) or len(q["options"]) != 4:
                    continue
                if not isinstance(q.get("correct"), int) or not 0 <= q["correct"] <= 3:
                    continue
                qs.append({
                    "id": str(q.get("id") or f"r{r}q{i:02d}"),
                    "kind": "choice",
                    "text": str(q.get("text", "")),
                    "options": [str(o) for o in q["options"]],
                    "correct": q["correct"],
                    "image": q.get("image"),
                    "explain": q.get("explain"),
                })
            title = str(src.get("title") or f"Раунд {r}")
        else:
            shown = {row["id"] for row in self.ev.db.all("SELECT id FROM facts WHERE shown_at IS NOT NULL")}
            pool = [f for f in self.ev.content.facts()
                    if f["id"] in shown and isinstance(f.get("quiz"), dict)
                    and f["quiz"].get("question") and f["quiz"].get("answer")]
            random.shuffle(pool)
            qs = [{
                "id": f"r4q{i}",
                "kind": "text",
                "fact_id": f["id"],
                "text": str(f["quiz"]["question"]),
                "answer": str(f["quiz"]["answer"]),
            } for i, f in enumerate(pool[:5], 1)]
            title = ROUND4_TITLE
        if not qs:
            hint = "показанных фактов с вопросом" if r == 4 else "вопросов"
            raise CmdError(f"В раунде {r} нет {hint}", "empty_round")
        return {"title": title, "questions": qs}

    # ------------------------------------------------------------------ команды ведущего
    def start_round(self) -> None:
        if self.st["done"]:
            raise CmdError("Квиз уже закончен", "quiz_done")
        if self.phase not in ("idle", "rating"):
            raise CmdError("Сначала закончите текущий раунд", "wrong_phase")
        r = self.st["round"] + 1
        rd = self._build_round(r)
        self.st.update(round=r, phase="intro", q=-1, started_at=None, deadline=None, eligible=[],
                       all_answered_at=None)
        self.st["rounds"][str(r)] = rd
        if not self.ev.settings["quiz_started"]:
            self.ev._set("quiz_started", True)
            self.ev.emit_settings()
        if r == 4:
            self.ev.emit_facts()
        self._changed(f"Квиз: раунд {r} «{rd['title']}», вопросов {len(rd['questions'])}")

    def show_question(self) -> None:
        rd = self.round_data()
        if self.phase not in ("intro", "reveal") or not rd:
            raise CmdError("Сейчас нельзя показать вопрос", "wrong_phase")
        if self.st["q"] + 1 >= len(rd["questions"]):
            raise CmdError("Вопросы раунда закончились", "no_more")
        now = self.ev.clock.now()
        self.st.update(
            q=self.st["q"] + 1, phase="question", started_at=now,
            deadline=now + float(self.cfg["answer_seconds"]),
            eligible=[p.id for p in self.ev.players.values()], all_answered_at=None,
        )
        q = self.question()
        self._changed(f"Квиз: вопрос {self.st['q'] + 1} раунда {self.st['round']} ({q['id']})")

    def close(self, reason: str = "ведущий") -> None:
        if self.phase != "question":
            raise CmdError("Приём ответов уже закрыт", "wrong_phase")
        q = self.question()
        if q["kind"] == "text":
            self.st["phase"] = "judging"
            self._changed(f"Квиз: приём закрыт ({reason}), ждём вердиктов")
            return
        self._score(q)
        self.st["phase"] = "reveal"
        self._changed(f"Квиз: приём закрыт ({reason}), разбор")

    def skip(self) -> None:
        if self.phase not in ("question", "judging"):
            raise CmdError("Сейчас нет идущего вопроса", "no_question")
        q = self.question()
        self.st["skipped"].append(q["id"])
        self.st["phase"] = "reveal"
        self._changed(f"Аварийно: вопрос {q['id']} пропущен, без начислений")

    def verdict(self, player_id: int, ok: bool | None) -> None:
        if self.phase != "judging":
            raise CmdError("Вердикты выставляются после закрытия приёма", "wrong_phase")
        q = self.question()
        cur = self.ev.db.execute(
            "UPDATE answers SET verdict=? WHERE qid=? AND player_id=?",
            (None if ok is None else int(bool(ok)), q["id"], int(player_id)),
        )
        if not cur.rowcount:
            raise CmdError("Этот игрок не отвечал", "not_found")
        p = self.ev.players.get(int(player_id))
        if p and ok is not None:
            self.ev.log(f"{p.name}: ответ {'принят' if ok else 'не принят'} "
                        f"(раунд 4, вопрос {self.st['q'] + 1})", p.id)
        self.ev.emit_quiz(roles={"host"})

    def verdict_rest(self, ok: bool = False) -> None:
        if self.phase != "judging":
            raise CmdError("Вердикты выставляются после закрытия приёма", "wrong_phase")
        q = self.question()
        self.ev.db.execute("UPDATE answers SET verdict=? WHERE qid=? AND verdict IS NULL", (int(bool(ok)), q["id"]))
        self.ev.log(f"Квиз: остальные ответы отмечены {'✓' if ok else '✗'}")
        self.ev.emit_quiz(roles={"host"})

    def reveal(self) -> None:
        if self.phase != "judging":
            raise CmdError("Сейчас нечего раскрывать", "wrong_phase")
        q = self.question()
        if any(a["verdict"] is None for a in self._answers(q["id"])):
            raise CmdError("Сначала вынесите вердикт по всем ответам", "verdicts_missing")
        self._score(q)
        self.st["phase"] = "reveal"
        self._changed("Квиз: ответы раунда 4 раскрыты")

    def next(self) -> None:
        """«Дальше» после разбора: следующий вопрос или итоги раунда."""
        if self.phase != "reveal":
            raise CmdError("Сейчас нельзя идти дальше", "wrong_phase")
        rd = self.round_data()
        if self.st["q"] + 1 < len(rd["questions"]):
            self.show_question()
        else:
            self.round_rating()

    def round_rating(self) -> None:
        rd = self.round_data()
        if self.phase != "reveal" or self.st["q"] + 1 < len(rd["questions"]):
            raise CmdError("Раунд ещё не закончен", "wrong_phase")
        r = self.st["round"]
        self.st["phase"] = "rating"
        if r == ROUNDS:
            self.st["done"] = True
        if r == 3 and self.cfg.get("hide_total_after_round3") and not self.ev.settings["hide_total"]:
            self.ev.set_setting("hide_total", True)
        if r == 4:
            self.ev.emit_facts()
        self._changed(f"Квиз: итоги раунда {r}")

    # ------------------------------------------------------------------ ответы игроков
    def answer(self, player_id: int, qid: str, choice=None, text=None) -> dict:
        q = self.question()
        if self.phase != "question" or not q or q["id"] != qid:
            raise CmdError("Приём ответов на этот вопрос закрыт", "closed")
        now = self.ev.clock.now()
        if now > self.st["deadline"]:
            raise CmdError("Время вышло", "closed")
        if player_id not in self.st["eligible"]:
            raise CmdError("Идёт вопрос, подключишься со следующего", "late")
        if q["kind"] == "choice":
            if not isinstance(choice, int) or isinstance(choice, bool) or not 0 <= choice <= 3:
                raise CmdError("Неверный вариант", "bad_answer")
            text = None
        else:
            text = " ".join(str(text or "").split())[:TEXT_MAX]
            if not text:
                raise CmdError("Пустой ответ", "bad_answer")
            choice = None
        cur = self.ev.db.execute(
            "INSERT OR IGNORE INTO answers(qid, player_id, choice, text, server_ts) VALUES(?, ?, ?, ?, ?)",
            (qid, player_id, choice, text, now),
        )
        if not cur.rowcount:
            raise CmdError("Ответ уже принят, изменить нельзя", "already")
        p = self.ev.players[player_id]
        secs = now - self.st["started_at"]
        self.ev.log(f"{p.name} ответил(а) на вопрос {self.st['q'] + 1} за {secs:.0f} с", p.id)
        self.ev.emit_quiz()
        return {"accepted": True}

    # ------------------------------------------------------------------ таймер
    def tick(self) -> None:
        if self.phase != "question":
            return
        now = self.ev.clock.now()
        if now >= self.st["deadline"]:
            self.close("время вышло")
            return
        answered = {a["player_id"] for a in self._answers(self.question()["id"])}
        online = [pid for pid in self.st["eligible"]
                  if pid in self.ev.players and self.ev.players[pid].connected]
        if online and all(pid in answered for pid in online):
            if self.st["all_answered_at"] is None:
                self.st["all_answered_at"] = now
                self.save()
            elif now >= self.st["all_answered_at"] + float(self.cfg["auto_close_delay_seconds"]):
                self.close("ответили все")
        elif self.st["all_answered_at"] is not None:
            self.st["all_answered_at"] = None  # вернулся игрок без ответа
            self.save()

    # ------------------------------------------------------------------ очки
    def _score(self, q: dict) -> None:
        if q["id"] in self.st["skipped"]:
            return
        if self.ev.db.one("SELECT 1 FROM ledger WHERE ref=? AND source IN ('quiz','quiz_bonus')", (q["id"],)):
            return  # уже начислено (повторное закрытие после сбоя)
        ok = [a for a in self._answers(q["id"]) if self._is_correct(q, a)]
        bonus = list(self.cfg["bonus"])
        for a in ok:
            self.ev.add_points(a["player_id"], "quiz", int(self.cfg["points_correct"]), ref=q["id"], notify=False)
        ranked = [a for a in ok if self.ev.players.get(a["player_id"]) and self.ev.players[a["player_id"]].in_scoring]
        for a, b in zip(ranked, bonus):
            self.ev.add_points(a["player_id"], "quiz_bonus", int(b), ref=q["id"], notify=False)
        self.ev.scores_changed({a["player_id"] for a in ok})

    @staticmethod
    def _is_correct(q: dict, a) -> bool:
        if q["kind"] == "choice":
            return a["choice"] == q["correct"]
        return a["verdict"] == 1

    def _results(self, q: dict) -> dict[int, dict]:
        rows = self.ev.db.all(
            "SELECT player_id, source, amount FROM ledger WHERE ref=? AND source IN ('quiz','quiz_bonus')", (q["id"],))
        out: dict[int, dict] = {}
        for r in rows:
            d = out.setdefault(r["player_id"], {"points": 0, "bonus": 0})
            d["points" if r["source"] == "quiz" else "bonus"] += r["amount"]
        return out

    # ------------------------------------------------------------------ рейтинги
    def _rank(self, scores: dict[int, int]) -> list[dict]:
        rows = []
        for pid, pts in scores.items():
            p = self.ev.players.get(pid)
            if p and p.in_scoring:
                rows.append({"player_id": pid, "name": p.name, "avatar_url": p.avatar_url, "points": pts})
        # внутри ничьей — стабильно по имени (рейтинг рассылается каждому отдельно и не должен «прыгать»)
        rows.sort(key=lambda x: (-x["points"], x["name"].casefold()))
        place, prev = 0, None
        for i, row in enumerate(rows, 1):
            if row["points"] != prev:
                place, prev = i, row["points"]
            row["place"] = place
        return rows

    def rating(self, r: int) -> dict:
        rd = self.round_data(r) or {"questions": []}
        ids = [q["id"] for q in rd["questions"]]
        scores = {pid: 0 for pid in self.ev.players}
        if ids:
            marks = ",".join("?" * len(ids))
            for row in self.ev.db.all(
                f"SELECT player_id, SUM(amount) AS s FROM ledger WHERE source IN ('quiz','quiz_bonus') "
                f"AND ref IN ({marks}) GROUP BY player_id", tuple(ids)):
                scores[row["player_id"]] = row["s"]
        out = {"round": self._rank(scores), "total": None}
        if not self.ev.settings["hide_total"]:
            out["total"] = self._rank(self.ev.totals())
        return out

    # ------------------------------------------------------------------ для клиентов
    def next_action(self) -> dict | None:
        ph = self.phase
        r = self.st["round"]
        rd = self.round_data()
        if ph in ("idle", "rating"):
            if self.st["done"]:
                return None
            return {"label": f"Начать раунд {r + 1}", "cmd": "quiz_start_round"}
        if ph == "intro":
            return {"label": "Показать вопрос", "cmd": "quiz_show"}
        if ph == "question":
            return {"label": "Закрыть приём", "cmd": "quiz_close"}
        if ph == "judging":
            missing = any(a["verdict"] is None for a in self._answers(self.question()["id"]))
            return {"label": "Раскрыть ответы", "cmd": "quiz_reveal", "disabled": missing,
                    "hint": "Сначала вердикты по всем ответам" if missing else None}
        if ph == "reveal":
            last = self.st["q"] + 1 >= len(rd["questions"])
            return {"label": "Итоги раунда" if last else "Следующий вопрос", "cmd": "quiz_next"}
        return None

    def public(self, role: str, player_id: int | None = None) -> dict:
        st = self.st
        rd = self.round_data()
        q = self.question()
        out = {
            "round": st["round"], "rounds_total": ROUNDS, "phase": st["phase"], "done": st["done"],
            "round_title": rd["title"] if rd else None,
            "q_index": st["q"], "q_count": len(rd["questions"]) if rd else 0,
            "started_at_ms": int(st["started_at"] * 1000) if st["started_at"] else None,
            "deadline_ms": int(st["deadline"] * 1000) if st["deadline"] else None,
            "warn_seconds": self.cfg["warn_seconds"],
            "answer_seconds": self.cfg["answer_seconds"],
            "facts_locked": self.facts_locked(),
        }
        answers = self._answers(q["id"]) if q and st["phase"] in ("question", "judging", "reveal") else []
        if q and st["phase"] in ("question", "judging", "reveal"):
            pub = {"id": q["id"], "kind": q["kind"], "text": q["text"]}
            if q["kind"] == "choice":
                pub["options"] = q["options"]
            if role in ("tv", "host") and q.get("image"):
                pub["image_url"] = f"/content/images/{q['image']}"
            out["question"] = pub
            out["answered_count"] = len(answers)
            out["eligible_count"] = len(st["eligible"])
        if q and st["phase"] == "reveal":
            out["reveal"] = self._reveal(q, answers)
        if st["phase"] == "rating":
            out["rating"] = self.rating(st["round"])
        if role == "host":
            out["next"] = self.next_action()
            if q:
                out["question_full"] = q
                out["answers"] = [self._answer_row(a) for a in answers]
                answered = {a["player_id"] for a in answers}
                out["waiting"] = [self.ev.players[pid].name for pid in st["eligible"]
                                  if pid in self.ev.players and pid not in answered]
        if role == "player" and player_id is not None:
            out["my"] = self._my(player_id, q, answers)
        return out

    def _answer_row(self, a) -> dict:
        p = self.ev.players.get(a["player_id"])
        return {
            "player_id": a["player_id"], "name": p.name if p else "?", "avatar_url": p.avatar_url if p else "",
            "choice": a["choice"], "text": a["text"], "verdict": a["verdict"],
            "t": round(a["server_ts"] - (self.st["started_at"] or a["server_ts"]), 1),
        }

    def _reveal(self, q: dict, answers: list) -> dict:
        skipped = q["id"] in self.st["skipped"]
        res = self._results(q)
        top = sorted((a for a in answers if res.get(a["player_id"], {}).get("bonus")),
                     key=lambda a: a["id"])
        out = {"skipped": skipped, "top": [{**self._answer_row(a), "bonus": res[a["player_id"]]["bonus"]} for a in top]}
        if q["kind"] == "choice":
            counts = [0, 0, 0, 0]
            for a in answers:
                if a["choice"] is not None:
                    counts[a["choice"]] += 1
            out.update(correct=q["correct"], counts=counts, explain=q.get("explain"))
        else:
            out.update(answer=q["answer"], answers=[self._answer_row(a) for a in answers])
        return out

    def _my(self, player_id: int, q: dict | None, answers: list) -> dict:
        my = {"eligible": bool(q) and player_id in self.st["eligible"]}
        a = next((x for x in answers if x["player_id"] == player_id), None)
        my["answered"] = a is not None
        if a is not None:
            my["choice"], my["text"] = a["choice"], a["text"]
        if q and self.st["phase"] == "reveal":
            r = self._results(q).get(player_id, {"points": 0, "bonus": 0})
            my["result"] = {**r, "correct": r["points"] > 0, "skipped": q["id"] in self.st["skipped"]}
            if q["kind"] == "text" and a is not None:
                my["verdict"] = a["verdict"]
        if self.st["phase"] == "rating":
            rt = self.rating(self.st["round"])
            mine = next((x for x in rt["round"] if x["player_id"] == player_id), None)
            my["round_points"] = mine["points"] if mine else sum(
                v for k, v in self._round_points_raw().items() if k == player_id)
            my["round_place"] = mine["place"] if mine else None
        return my

    def _round_points_raw(self) -> dict[int, int]:
        rd = self.round_data() or {"questions": []}
        ids = [q["id"] for q in rd["questions"]]
        if not ids:
            return {}
        marks = ",".join("?" * len(ids))
        return {r["player_id"]: r["s"] for r in self.ev.db.all(
            f"SELECT player_id, SUM(amount) AS s FROM ledger WHERE source IN ('quiz','quiz_bonus') "
            f"AND ref IN ({marks}) GROUP BY player_id", tuple(ids))}
