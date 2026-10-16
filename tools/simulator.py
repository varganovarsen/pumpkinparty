"""Симулятор вечера (модуль 08): виртуальные игроки по WebSocket, как настоящие телефоны.

    python tools/simulator.py --players 8 --speed 30 --scenario evening

По умолчанию поднимает свой сервер на свободном порту с временной папкой данных
(настоящий data/ не трогается) и в середине прогона перезапускает его.
С --url работает с уже запущенным сервером (без перезапуска).

Сценарии:
  core     — вход, профили, переключение всех сцен, обрывы и возвраты, ручные правки очков,
             перезапуск сервера, сверка очков.
  evening  — весь вечер: core + квиз (4 раунда на тестовом контенте tests/fixtures/content,
             перезапуск посреди вопроса) + игра (тренировка и зачёт, обрыв посреди игры) + охота за семечками + резьба
             (тыквы, голосование, итоги) + таймер + общий рейтинг + финальное фото + скачивание.
             Итоговые очки сверяются до единицы.
"""
from __future__ import annotations

import argparse
import asyncio
import io
import json
import os
import random
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
import websockets

ROOT = Path(__file__).resolve().parent.parent
SCENES = ["ambient", "quiz", "game", "seeds", "timer", "carve_vote", "carve_reveal",
          "rating_reveal", "final_photo", "slideshow", "download"]
TEST_CONTENT = ROOT / "tests" / "fixtures" / "content"


class Report:
    def __init__(self):
        self.problems: list[str] = []
        self.steps: list[str] = []

    def step(self, text: str) -> None:
        self.steps.append(text)
        print(f"  ✓ {text}")

    def fail(self, text: str) -> None:
        self.problems.append(text)
        print(f"  ✗ {text}")

    def check(self, cond: bool, ok: str, bad: str) -> None:
        self.step(ok) if cond else self.fail(bad)


# ---------------------------------------------------------------------- сервер
class ServerProc:
    def __init__(self, speed: float):
        self.speed = speed
        self.port = _free_port()
        self.data = Path(tempfile.mkdtemp(prefix="pumpkin-sim-"))
        self.proc: subprocess.Popen | None = None
        self.url = f"http://127.0.0.1:{self.port}"
        self.log = open(self.data / "sim-server.out", "ab")

    async def start(self) -> None:
        cmd = [sys.executable, "-m", "server", "--port", str(self.port), "--data", str(self.data),
               "--speed", str(self.speed), "--bind", "127.0.0.1"]
        env = {**os.environ, "PUMPKIN_CONTENT": str(TEST_CONTENT)}
        self.proc = subprocess.Popen(cmd, cwd=ROOT, stdout=self.log, stderr=subprocess.STDOUT, env=env)
        await wait_health(self.url)

    async def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()

    def crashed(self) -> bool:
        return self.proc is not None and self.proc.poll() is not None


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def wait_health(url: str, timeout: float = 30) -> None:
    deadline = time.monotonic() + timeout
    async with httpx.AsyncClient() as c:
        while time.monotonic() < deadline:
            try:
                if (await c.get(f"{url}/api/health", timeout=1)).status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            await asyncio.sleep(0.2)
    raise RuntimeError(f"сервер {url} не поднялся за {timeout} с")


# ---------------------------------------------------------------------- клиенты
class Client:
    """Одно WebSocket-подключение с фоновым чтением и автопереподключением."""

    def __init__(self, base: str, role: str, token: str | None = None, name: str = ""):
        self.base = base
        self.role = role
        self.token = token
        self.name = name or role
        self.ws = None
        self.task: asyncio.Task | None = None
        self.scene: str | None = None
        self.snapshot: dict | None = None
        self.messages: list[dict] = []
        self.replies: dict[int, asyncio.Future] = {}
        self.next_id = 1
        self.connected = asyncio.Event()
        self.quiz: dict | None = None
        self.state: dict = {}  # последние состояния модулей: game, seeds, vote, timer, finale
        self.reconnects = 0
        self.want = True

    def ws_url(self) -> str:
        u = self.base.replace("http://", "ws://") + f"/ws?role={self.role}"
        return u + (f"&token={self.token}" if self.token else "")

    async def run(self) -> None:
        while self.want:
            try:
                async with websockets.connect(self.ws_url(), open_timeout=5) as ws:
                    self.ws = ws
                    async for raw in ws:
                        self._on(json.loads(raw))
            except (OSError, websockets.WebSocketException, asyncio.TimeoutError):
                pass
            self.ws = None
            self.connected.clear()
            if self.want:
                self.reconnects += 1
                await asyncio.sleep(0.3)

    def start(self) -> None:
        self.want = True
        self.task = asyncio.create_task(self.run())

    async def drop(self) -> None:
        """Обрыв связи (как телефон, ушедший из wifi)."""
        self.want = False
        if self.ws:
            await self.ws.close()
        if self.task:
            await asyncio.wait([self.task], timeout=3)

    def _on(self, m: dict) -> None:
        self.messages.append(m)
        t = m.get("t")
        if t == "snapshot":
            self.snapshot = m
            self.scene = m["scene"]["scene"]
            self.quiz = m.get("quiz")
            self.state.update({k: m[k] for k in ("game", "seeds", "vote", "timer", "finale") if k in m})
            self.connected.set()
        elif t in ("game", "seeds", "vote", "timer", "finale"):
            self.state[t] = m[t]
        elif t == "quiz":
            self.quiz = m["quiz"]
        elif t == "head" and self.role == "tv" and m.get("head"):
            # как настоящий ТВ: пузырь появился — факт показан
            asyncio.get_running_loop().create_task(self.cmd("head_shown", fact_id=m["head"]["fact_id"]))
        elif t == "scene":
            self.scene = m["scene"]
        elif t == "reply":
            fut = self.replies.pop(m.get("id"), None)
            if fut and not fut.done():
                fut.set_result(m)
        elif t == "players" and self.snapshot is not None:
            self.snapshot["players"] = m["players"]
        elif t == "settings" and self.snapshot is not None:
            self.snapshot["settings"] = m["settings"]

    async def cmd(self, name: str, **args) -> dict:
        await asyncio.wait_for(self.connected.wait(), 10)
        rid = self.next_id
        self.next_id += 1
        fut = asyncio.get_running_loop().create_future()
        self.replies[rid] = fut
        await self.ws.send(json.dumps({"t": "cmd", "cmd": name, "id": rid, **args}))
        return await asyncio.wait_for(fut, 10)


async def wait_for(cond, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cond():
            return True
        await asyncio.sleep(0.05)
    return cond()


def tiny_jpeg() -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (320, 240), (random.randint(0, 255), 120, 60)).save(buf, "JPEG")
    return buf.getvalue()


# ---------------------------------------------------------------------- сценарий
async def scenario_core(base: str, n_players: int, rep: Report, server: ServerProc | None) -> None:
    http = httpx.AsyncClient(base_url=base, timeout=10)
    expected: dict[int, int] = {}

    print("Вход и профили")
    host = Client(base, "host")
    tv = Client(base, "tv")
    host.start()
    tv.start()
    await asyncio.wait_for(host.connected.wait(), 10)
    tv_ok = await wait_for(lambda: tv.connected.is_set(), 5)
    rep.check(tv_ok, "ТВ подключился с localhost", "ТВ не подключился")
    # чистый старт: если сервер внешний, сбрасываем вечер
    if server is None:
        await host.cmd("reset_evening", confirm="СБРОС")
        await asyncio.sleep(0.5)

    players: list[Client] = []
    for i in range(n_players):
        name = f"Игрок {i + 1}"
        if i == n_players - 1:  # последний — с фото-профилем
            up = (await http.post("/api/upload_avatar", files={"file": ("p.jpg", tiny_jpeg(), "image/jpeg")})).json()
            crop = (await http.post("/api/avatar_crop", json={"upload_id": up["upload_id"], "cx": .5, "cy": .5, "size": .8})).json()
            body = {"name": name, "avatar_kind": "photo", "avatar_ref": crop["avatar_ref"]}
        else:
            body = {"name": name, "avatar_kind": "pumpkin", "avatar_ref": f"pumpkin-{i % 8 + 1}"}
        r = (await http.post("/api/join", json=body)).json()
        if not r.get("ok"):
            rep.fail(f"{name}: вход не удался: {r}")
            continue
        c = Client(base, "player", r["token"], name)
        c.pid = r["me"]["id"]
        expected[c.pid] = 0
        players.append(c)
        c.start()
    ok = await wait_for(lambda: all(p.connected.is_set() for p in players), 10)
    rep.check(ok and len(players) == n_players, f"{len(players)} игроков вошли и подключились", "не все игроки подключились")

    r = (await http.post("/api/join", json={"name": "игрок 1", "avatar_kind": "pumpkin", "avatar_ref": "pumpkin-8"})).json()
    rep.check(r.get("code") == "name_taken", "дубль имени отклонён", f"дубль имени принят: {r}")
    if n_players > 1:
        r = (await http.post("/api/join", json={"name": "Новенький", "avatar_kind": "pumpkin", "avatar_ref": "pumpkin-1"})).json()
        rep.check(r.get("code") == "avatar_taken", "занятый аватар отклонён", f"занятый аватар принят: {r}")

    print("Сцены, обрывы связи, правки очков")
    rnd = random.Random(42)
    for round_no in range(2):
        for scene in SCENES:
            dropped = rnd.sample(players, k=min(2, len(players)))
            for p in dropped:
                await p.drop()
            r = await host.cmd("set_scene", scene=scene, force=True)
            if not r["ok"]:
                rep.fail(f"сцена {scene}: {r}")
                continue
            target = rnd.choice(players)
            amount = rnd.choice([-50, 25, 100, 200])
            r = await host.cmd("adjust_score", player_id=target.pid, amount=amount, note="симулятор")
            if r["ok"]:
                expected[target.pid] += amount
            for p in dropped:
                p.start()
            synced = await wait_for(lambda: all(p.scene == scene for p in players) and tv.scene == scene, 5)
            if not synced:
                lag = [p.name for p in players if p.scene != scene]
                rep.fail(f"сцена {scene}: не дошла до {lag or ['ТВ']}")
        rep.step(f"круг {round_no + 1}: все {len(SCENES)} сцен дошли до ТВ и всех телефонов (с обрывами)")
    await host.cmd("set_scene", scene="ambient", force=True)

    def scores_ok() -> bool:
        got = {p["id"]: p["score"] for p in host.snapshot["players"]}
        return all(got.get(pid) == exp for pid, exp in expected.items())

    rep.check(await wait_for(scores_ok, 5), "очки на /host совпадают с ожидаемыми", "очки на /host расходятся")

    if server is not None:
        print("Перезапуск сервера посреди сцены")
        await host.cmd("set_scene", scene="timer")
        await server.stop()
        await asyncio.sleep(0.5)
        for c in [host, tv, *players]:
            c.connected.clear()
        await server.start()
        ok = await wait_for(lambda: all(c.connected.is_set() for c in [host, tv, *players]), 15)
        rep.check(ok, "после перезапуска все переподключились сами", "не все переподключились после перезапуска")
        rep.check(all(c.scene == "timer" for c in [tv, *players]), "сцена восстановлена", "сцена потеряна при перезапуске")
        snap_players = {p["id"]: p for p in host.snapshot["players"]}
        rep.check(len(snap_players) == n_players, "игроки сохранены", "игроки потеряны при перезапуске")
        rep.check(await wait_for(scores_ok, 5), "очки сохранены", "очки потеряны при перезапуске")
        await host.cmd("set_scene", scene="ambient")

    print("Голова-тыква")
    r = await host.cmd("head_call")
    if r["ok"]:
        got = await wait_for(lambda: any(m.get("t") == "head" and m.get("head") for m in tv.messages), 3)
        rep.check(got, "голова показала факт на ТВ", "факт не дошёл до ТВ")
    else:
        rep.step(f"голова: {r.get('error')}")

    if server is not None:
        rep.check(not server.crashed(), "сервер не упал", "сервер упал")
    for c in [host, tv, *players]:
        await c.drop()
    await http.aclose()
    return [(p.name, p.token, p.pid) for p in players], expected


# ---------------------------------------------------------------------- квиз
def correct_choice(qid: str) -> int:
    """Правильный вариант в тестовом контенте (tools/make_test_content.py): (раунд + номер) % 4."""
    r, i = qid[1:].split("q")
    return (int(r) + int(i)) % 4


async def scenario_quiz(base: str, roster: list, expected: dict[int, int], rep: Report,
                        server: ServerProc | None) -> None:
    http = httpx.AsyncClient(base_url=base, timeout=10)
    rnd = random.Random(7)
    print("Квиз: подготовка")
    r = (await http.post("/api/join", json={"name": "Ведущий", "avatar_kind": "pumpkin",
                                            "avatar_ref": "pumpkin-8", "as_host": True})).json()
    if not r.get("ok"):
        rep.fail(f"профиль ведущего не создан: {r}")
        return
    host_player = (r["me"]["name"], r["token"], r["me"]["id"])
    expected[host_player[2]] = 0
    host = Client(base, "host")
    tv = Client(base, "tv")
    clients = []
    for name, token, pid in [host_player, *roster]:
        c = Client(base, "player", token, name)
        c.pid = pid
        c.in_scoring = pid != host_player[2]
        # характер игрока: точность и вероятность промолчать
        c.accuracy = 1.0 if not c.in_scoring else rnd.uniform(0.4, 0.95)
        clients.append(c)
    everyone = [host, tv, *clients]
    for c in everyone:
        c.start()
    rep.check(await wait_for(lambda: all(c.connected.is_set() for c in everyone), 10),
              "все подключились к квизу", "не все подключились к квизу")

    # голова показывает все факты (нужны для раунда 4)
    await host.cmd("set_scene", scene="ambient", force=True)
    for _ in range(20):
        await host.cmd("head_call")
        await asyncio.sleep(0.05)
    await asyncio.sleep(0.3)

    await host.cmd("set_scene", scene="quiz", force=True)
    restarted = False

    async def wait_phase(pred, timeout=15.0) -> bool:
        return await wait_for(lambda: host.quiz is not None and pred(host.quiz), timeout)

    for rno in range(1, 5):
        r = await host.cmd("quiz_start_round")
        if not r["ok"]:
            rep.fail(f"раунд {rno} не начался: {r.get('error')}")
            return
        await wait_phase(lambda q: q["phase"] == "intro" and q["round"] == rno)
        count = host.quiz["q_count"]
        if rno == 4:
            rep.check(host.quiz["facts_locked"], "вкладка «Факты» закрыта в раунде 4", "факты не закрыты в раунде 4")
        for k in range(count):
            if k == 0:  # дальше вопросы показывает «Следующий вопрос» (quiz_next)
                r = await host.cmd("quiz_show")
                if not r["ok"]:
                    rep.fail(f"раунд {rno}, вопрос {k + 1}: {r.get('error')}")
                    return
            if not await wait_phase(lambda q: q["phase"] == "question" and q["q_index"] == k):
                rep.fail(f"раунд {rno}, вопрос {k + 1} не показан")
                return
            qid = host.quiz["question"]["id"]
            kind = host.quiz["question"]["kind"]
            order = clients[:]
            rnd.shuffle(order)
            silent = {c.pid for c in order if c.in_scoring and rnd.random() < 0.08}
            plan = []  # (клиент, ответ, верно ли)
            for c in order:
                if c.pid in silent:
                    continue
                good = rnd.random() < c.accuracy
                if kind == "choice":
                    ok = correct_choice(qid)
                    plan.append((c, {"choice": ok if good else (ok + 1 + rnd.randrange(3)) % 4}, good))
                else:
                    plan.append((c, {"text": "верно" if good else "не знаю"}, good))
            # обрыв и возврат посреди вопроса: ответ после возврата принимается
            if rno == 1 and k == 4 and plan:
                c = plan[-1][0]
                await c.drop()
                c.connected.clear()
                c.start()
                await wait_for(lambda: c.connected.is_set(), 5)
            sent = []
            for i, (c, ans, good) in enumerate(plan):
                if server is not None and not restarted and rno == 2 and k == 3 and i == len(plan) // 2:
                    print("Квиз: перезапуск сервера посреди вопроса")
                    await server.stop()
                    for x in everyone:
                        x.connected.clear()
                    await server.start()
                    restarted = True
                    ok = await wait_for(lambda: all(x.connected.is_set() for x in everyone), 15)
                    rep.check(ok and host.quiz["phase"] == "question" and host.quiz["answered_count"] == len(sent),
                              "перезапуск посреди вопроса: фаза и ответы сохранены",
                              f"после перезапуска квиз в фазе {host.quiz and host.quiz['phase']}, "
                              f"ответов {host.quiz and host.quiz.get('answered_count')} вместо {len(sent)}")
                rr = await c.cmd("quiz_answer", qid=qid, **ans)
                if rr["ok"]:
                    sent.append((c, good))
                else:
                    rep.fail(f"{qid}: ответ {c.name} не принят: {rr.get('error')}")
            # ожидаемые очки: 200 за верный, бонус первым трём верным в зачёте
            bonus = [50, 25, 10]
            for c, good in sent:
                if good:
                    expected[c.pid] += 200
                    if c.in_scoring and bonus:
                        expected[c.pid] += bonus.pop(0)
            if silent and kind == "choice":
                await wait_phase(lambda q: q["phase"] == "reveal" and q["q_index"] == k, timeout=70 / server.speed + 10
                                 if server else 70)
            if kind == "text":
                await wait_phase(lambda q: q["phase"] == "judging" and q["q_index"] == k,
                                 timeout=(70 / server.speed + 10) if server else 70)
                for a in host.quiz.get("answers", []):
                    await host.cmd("quiz_verdict", player_id=a["player_id"], ok=a["text"] == "верно")
                await host.cmd("quiz_reveal")
            ok = await wait_phase(lambda q: q["phase"] == "reveal" and q["q_index"] == k,
                                  timeout=(70 / server.speed + 10) if server else 70)
            if not ok:
                rep.fail(f"{qid}: разбор не наступил (фаза {host.quiz['phase']})")
                return
            await host.cmd("quiz_next")
        ok = await wait_phase(lambda q: q["phase"] == "rating" and q["round"] == rno)
        rating = host.quiz.get("rating") or {}
        rep.check(ok and all(row["player_id"] != host_player[2] for row in rating.get("round", [])),
                  f"раунд {rno}: {count} вопросов, итоги без ведущего вне зачёта",
                  f"раунд {rno}: итоги не показаны или ведущий в рейтинге")
        if rno == 3:
            rep.check(rating.get("total") is None and host.snapshot["settings"]["hide_total"] is True,
                      "после раунда 3 общий рейтинг скрыт", "общий рейтинг не скрыт после раунда 3")
    rep.check(host.quiz["done"] and not host.quiz["facts_locked"], "квиз окончен, факты снова открыты",
              "квиз не закончился или факты закрыты")

    def scores_ok() -> bool:
        got = {p["id"]: p["score"] for p in host.snapshot["players"]}
        return all(got.get(pid) == exp for pid, exp in expected.items())

    ok = await wait_for(scores_ok, 5)
    if ok:
        rep.step(f"очки после квиза совпали у всех {len(expected)} игроков (включая ведущего вне зачёта)")
    else:
        got = {p["id"]: p["score"] for p in host.snapshot["players"]}
        for pid, exp in expected.items():
            if got.get(pid) != exp:
                rep.fail(f"игрок {pid}: ожидалось {exp}, на сервере {got.get(pid)}")
    for c in everyone:
        await c.drop()
    await http.aclose()
    return host_player


# ---------------------------------------------------------------------- игра, резьба, финал
def tiny_png(size: int, spots: int) -> bytes:
    from PIL import Image, ImageDraw
    img = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(img)
    for i in range(spots):
        d.ellipse((100 + 120 * i, 600, 160 + 120 * i, 660), fill=255)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def competition_places(votes: dict[int, int], bonus: list[int], out_of_scoring: set[int]) -> dict[int, int]:
    """Независимый от сервера расчёт бонусов: места 1,1,3…, без голосов и вне зачёта — без места."""
    ranked = {pid: v for pid, v in votes.items() if pid not in out_of_scoring}
    out = {pid: 0 for pid in votes}
    for pid, v in ranked.items():
        if v <= 0:
            continue
        place = 1 + sum(1 for w in ranked.values() if w > v)
        out[pid] = bonus[place - 1] if place <= len(bonus) else 0
    return out


async def scenario_finale(base: str, roster: list, host_player: tuple, expected: dict[int, int], rep: Report) -> None:
    sys.path.insert(0, str(ROOT))
    from server.game import score_of  # тот же счёт, что у сервера

    http = httpx.AsyncClient(base_url=base, timeout=20)
    rnd = random.Random(11)
    host = Client(base, "host")
    tv = Client(base, "tv")
    clients = []
    for name, token, pid in [host_player, *roster]:
        c = Client(base, "player", token, name)
        c.pid = pid
        clients.append(c)
    everyone = [host, tv, *clients]
    for c in everyone:
        c.start()
    await wait_for(lambda: all(c.connected.is_set() for c in everyone), 10)
    points = {"regular": 10, "golden": 50, "rotten": -30}

    def module(c, name):
        return c.state.get(name)

    print("Игра «Падающие тыквы»")
    await host.cmd("set_scene", scene="game", force=True)
    for mode in ("practice", "scored"):
        r = await host.cmd("game_start", mode=mode)
        if not r["ok"]:
            rep.fail(f"игра ({mode}) не стартовала: {r.get('error')}")
            return
        await wait_for(lambda: all((module(c, "game") or {}).get("phase") == "running" for c in clients), 10)
        dropped = clients[2]
        await dropped.drop()  # обрыв посреди игры: результат уйдёт после возврата
        for c in clients:
            if c is dropped:
                continue
            g = module(c, "game")
            items = g["items"]
            caught = [it["i"] for it in items if rnd.random() < 0.7]
            r = await c.cmd("game_result", caught=caught)
            if mode == "scored" and r["ok"]:
                expected[c.pid] += min(500, score_of(items, set(caught), points))
        dropped.connected.clear()
        dropped.start()
        await wait_for(lambda: dropped.connected.is_set(), 10)
        g = dropped.state["game"]
        if g.get("items"):
            caught = [it["i"] for it in g["items"] if it["kind"] == "golden"]
            r = await dropped.cmd("game_result", caught=caught)
            if mode == "scored" and r["ok"]:
                expected[dropped.pid] += min(500, score_of(g["items"], set(caught), points))
            rep.check(r["ok"], f"игра ({mode}): результат после обрыва принят", f"результат после обрыва не принят: {r}")
        ok = await wait_for(lambda: (module(host, "game") or {}).get("phase") == "finished", 15)
        rep.check(ok, f"игра ({mode}) закончилась", f"игра ({mode}) не закончилась")

    print("Охота за семечками")
    await host.cmd("set_scene", scene="seeds", force=True)
    r = await host.cmd("seeds_start")
    rep.check(r["ok"], "охота началась", f"охота не стартовала: {r}")
    await wait_for(lambda: (module(host, "seeds") or {}).get("phase") == "running", 10)
    codes = [s["code"] for s in (module(host, "seeds") or {}).get("seeds", [])]
    seekers = clients[1:]  # clients[0] — ведущий, он прятал
    r = await clients[0].cmd("seeds_enter", code=codes[0])
    rep.check(r.get("code") == "host", "ведущему искать нельзя", f"ведущий смог ввести код: {r}")
    for c in seekers[:2]:
        r = await c.cmd("seeds_enter", code="0000")
        if r.get("code") != "wrong":
            rep.fail(f"неверный код не отклонён: {r}")
    winners: dict[str, list] = {}

    async def hunt(c):
        for code in rnd.sample(codes, len(codes)):
            r = await c.cmd("seeds_enter", code=code)
            if r["ok"]:
                winners.setdefault(code, []).append(c.name)
                expected[c.pid] += r["points"]
            elif r.get("code") not in ("taken", "closed"):
                rep.fail(f"{c.name}: код {code} — {r}")
    await asyncio.gather(*(hunt(c) for c in seekers))
    rep.check(sorted(winners) == sorted(codes) and all(len(w) == 1 for w in winners.values()),
              f"все {len(codes)} семечек засчитаны ровно одному игроку", f"семечки засчитаны неверно: {winners}")
    ok = await wait_for(lambda: (module(host, "seeds") or {}).get("phase") == "finished", 10)
    rep.check(ok, "охота закончилась сама, когда нашли все", "охота не закончилась")

    print("Резьба: тыквы, голосование, итоги")
    with_pumpkin = clients[0:6]  # шестеро сохранили тыквы, включая ведущего вне зачёта
    from PIL import Image
    shot = io.BytesIO()
    Image.new("RGB", (64, 64), (120, 40, 10)).save(shot, "JPEG")
    for k, c in enumerate(with_pumpkin):
        files = {"through.png": ("t.png", tiny_png(512, k + 1), "image/png"),
                 "depth.png": ("d.png", tiny_png(512, 1), "image/png")}
        for s in ("lit", "dark", "side"):
            files[f"{s}.jpg"] = (f"{s}.jpg", shot.getvalue(), "image/jpeg")
        r = (await http.post(f"/api/pumpkin/{c.pid}", files=files,
                             data={"camera": json.dumps({"theta": 0, "phi": 1.3, "radius": 4.6})})).json()
        if not r.get("ok"):
            rep.fail(f"тыква {c.name} не сохранилась: {r}")
    await host.cmd("set_scene", scene="carve_vote", force=True)
    r = await host.cmd("vote_start")
    rep.check(r["ok"], "голосование открыто", f"голосование не открылось: {r}")
    await asyncio.sleep(0.3)
    entries = (module(host, "vote") or {}).get("entries", [])
    by_n = {}
    votes_for = {c.pid: 0 for c in with_pumpkin}
    for c in clients:
        own = (module(c, "vote") or {}).get("my", {}).get("own")
        choices = [e["n"] for e in entries if e["n"] != own]
        if rnd.random() < 0.15 or not choices:
            await c.cmd("vote", n=None)
            continue
        n = rnd.choice(choices[:3])  # голоса концентрируются — будут ничьи и места
        rr = await c.cmd("vote", n=n)
        if not rr["ok"]:
            rep.fail(f"голос {c.name} не принят: {rr.get('error')}")
        by_n.setdefault(c.pid, n)
    r = await c.cmd("vote", n=own) if own else {"code": "own"}
    rep.check(r.get("code") == "own", "голос за свою тыкву отклонён", "голос за свою тыкву принят")
    await host.cmd("vote_close")
    await asyncio.sleep(0.3)
    results = (module(host, "vote") or {}).get("results", [])
    for res in results:
        votes_for[res["player_id"]] = res["votes"]
    bonuses = competition_places(votes_for, [500, 300, 100], {host_player[2]})
    server_bonus = {res["player_id"]: res["bonus"] for res in results}
    rep.check(bonuses == server_bonus, "места и бонусы резьбы совпали с независимым расчётом",
              f"бонусы резьбы расходятся: ожидалось {bonuses}, сервер {server_bonus}")
    for pid, b in bonuses.items():
        expected[pid] += b
    await host.cmd("set_scene", scene="carve_reveal", force=True)
    for _ in range(len(results) + 1):
        await host.cmd("vote_reveal")
    rep.check((await http.get("/api/pumpkins")).json()["revealed"], "итоги резьбы раскрыты, тыквы в скачивании",
              "тыквы не появились в скачивании")

    print("Перерыв, общий рейтинг, финал")
    await host.cmd("set_scene", scene="timer", force=True)
    await host.cmd("timer_set", minutes=0.2, label="Скоро финал")
    ok = await wait_for(lambda: (module(host, "timer") or {}).get("finished"), 10)
    rep.check(ok and host.scene == "timer", "таймер дошёл до нуля, сцена не переключилась", "таймер не закончился")
    await host.cmd("set_scene", scene="rating_reveal", force=True)
    await asyncio.sleep(0.3)
    groups = (module(host, "finale") or {}).get("groups", [])
    in_scoring = {pid: exp for pid, exp in expected.items() if pid != host_player[2]}
    totals = sorted({exp for exp in in_scoring.values()})
    rep.check([g[0]["total"] for g in groups] == totals and all(r["player_id"] != host_player[2] for g in groups for r in g),
              "общий рейтинг: суммы и порядок верны, ведущего нет", f"рейтинг расходится: {[g[0]['total'] for g in groups]} vs {totals}")
    for _ in groups:
        await host.cmd("rating_next")
    await asyncio.sleep(0.3)
    rep.check(host.snapshot["settings"]["hide_total"] is False, "после раскрытия суммы снова видны на телефонах",
              "общий рейтинг так и остался скрытым")
    await host.cmd("set_scene", scene="final_photo", force=True)
    img = io.BytesIO()
    Image.new("RGB", (1600, 1200), (60, 80, 120)).save(img, "JPEG")
    r = (await http.post("/api/final_photo", files={"file": ("f.jpg", img.getvalue(), "image/jpeg")})).json()
    rep.check(r.get("ok"), "финальное фото обработано", f"финальное фото: {r}")
    await host.cmd("set_scene", scene="slideshow")
    await host.cmd("set_scene", scene="download")
    photos = (await http.get("/api/photos?final_first=1")).json()["photos"]
    z = await http.post("/api/download_zip", data={"ids": ",".join(str(p["id"]) for p in photos)})
    rep.check(z.status_code == 200 and photos and photos[0]["kind"] == "final",
              f"скачивание: финальное фото первым, ZIP из {len(photos)} фото", "скачивание не работает")

    def scores_ok() -> bool:
        got = {p["id"]: p["score"] for p in host.snapshot["players"]}
        return all(got.get(pid) == exp for pid, exp in expected.items())

    if await wait_for(scores_ok, 5):
        rep.step(f"итоговые очки вечера совпали у всех {len(expected)} игроков")
    else:
        got = {p["id"]: p["score"] for p in host.snapshot["players"]}
        for pid, exp in expected.items():
            if got.get(pid) != exp:
                rep.fail(f"игрок {pid}: ожидалось {exp}, на сервере {got.get(pid)}")
    for c in everyone:
        await c.drop()
    await http.aclose()
    print("\nИтог вечера (ожидаемые = фактические очки):")
    names = {pid: name for name, _, pid in [host_player, *roster]}
    for pid, exp in sorted(expected.items(), key=lambda x: -x[1]):
        print(f"  {names[pid]}: {exp}")


async def main_async(args) -> int:
    rep = Report()
    server = None
    base = args.url
    if not base:
        server = ServerProc(args.speed)
        print(f"Поднимаю сервер: {server.url}, данные {server.data}, ускорение x{args.speed}")
        await server.start()
        base = server.url
    try:
        roster, expected = await scenario_core(base, args.players, rep, server)
        if args.scenario == "evening":
            if server is None:
                print("\nКвиз пропущен: нужен свой сервер с тестовым контентом (запуск без --url)")
            else:
                host_player = await scenario_quiz(base, roster, expected, rep, server)
                if host_player:
                    await scenario_finale(base, roster, host_player, expected, rep)
    finally:
        if server:
            await server.stop()
            server.log.close()
    print("\n=== Отчёт ===")
    print(f"Шагов пройдено: {len(rep.steps)}, расхождений: {len(rep.problems)}")
    for p in rep.problems:
        print(f"  ✗ {p}")
    if server and rep.problems:
        print(f"Журнал сервера: {server.data / 'sim-server.out'}")
    elif server:
        shutil.rmtree(server.data, ignore_errors=True)
    return 1 if rep.problems else 0


def main() -> None:
    ap = argparse.ArgumentParser(description="Симулятор вечера «Тыквенный спас»")
    ap.add_argument("--players", type=int, default=8)
    ap.add_argument("--speed", type=float, default=30)
    ap.add_argument("--scenario", choices=["core", "evening"], default="evening")
    ap.add_argument("--url", help="адрес уже запущенного сервера (иначе поднимается свой)")
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # Windows: вывод в файл/pipe не в cp1251
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    os.chdir(ROOT)
    sys.exit(asyncio.run(main_async(args)))


if __name__ == "__main__":
    main()
