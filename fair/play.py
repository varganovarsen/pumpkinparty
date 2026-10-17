"""Плейтест в браузере: вы против ботов, решения кнопками вместо консоли.

    python -m fair web [--port 8766] [--role Повар] [--seed 7] [--set ключ=значение]

Партия идёт в отдельном потоке. WebHuman реализует интерфейс агента: на каждом решении кладёт вопрос
и снимок партии, ждёт ответ со страницы. Конфиг перечитывается с диска на каждую новую партию,
так что сохранения из редактора подхватываются. Только stdlib-сервер на 127.0.0.1.
"""
from __future__ import annotations

import json
import queue
import random
import threading
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import config
from .engine import Agent, Log, MarketOrder
from .runner import make_game

HTML = Path(__file__).with_name("play.html")


class Aborted(BaseException):
    """Партию сбросили со страницы — выходим из потока движка."""


class Session:
    """Общее между потоком движка и HTTP: журнал, текущий вопрос, снимок. Версия растёт на каждом изменении."""

    def __init__(self):
        self.cond = threading.Condition()
        self.version = 0
        self.log: list[dict] = []
        self.prompt: dict | None = None
        self.snap: dict | None = None
        self.answers: queue.Queue = queue.Queue()
        self.seed: int | None = None
        self.error: str | None = None
        self.over = False
        self.thread: threading.Thread | None = None

    def bump(self):
        with self.cond:
            self.version += 1
            self.cond.notify_all()

    def add(self, kind: str, text: str):
        with self.cond:
            self.log.append({"kind": kind, "text": text})
        self.bump()

    def state(self, since_log: int = 0) -> dict:
        with self.cond:
            return {"version": self.version, "seed": self.seed, "prompt": self.prompt, "snap": self.snap,
                    "log": self.log[since_log:], "log_total": len(self.log), "error": self.error, "over": self.over}

    def wait(self, version: int, timeout: float = 25):
        with self.cond:
            self.cond.wait_for(lambda: self.version != version, timeout)


class WebLog(Log):
    def __init__(self, s: Session):
        super().__init__(info=True, detail=True)
        self.s = s

    def info(self, msg=""):
        for line in str(msg).split("\n"):
            if not line.strip():
                continue
            kind = "h1" if line.startswith("══") else "h2" if line.startswith("— ") else "info"
            self.s.add(kind, line.strip("═— ").strip() if kind != "info" else line)

    def detail(self, msg):
        self.s.add("detail", msg)


def counts(c) -> dict:
    return {k: v for k, v in sorted(c.items()) if v > 0}


def has_items(g, p, items: dict) -> bool:
    for k, q in items.items():
        if k == "монеты":
            if p.coins < q:
                return False
        elif (p.raws if k in g.c.raws else p.dishes)[k] < q:
            return False
    return True


class WebHuman(Agent):
    human = True
    arch = "человек"

    def __init__(self, s: Session):
        self.s = s
        self.flash: list[str] = []   # итоги своих действий, показываются в журнале сразу
        self.next_id = 0

    # ------------------------------------------------------------ обмен со страницей
    def ask(self, g, me, kind: str, **data):
        self.next_id += 1
        prompt = {"id": self.next_id, "kind": kind, **data}
        snap = self.snapshot(g, me)
        with self.s.cond:
            self.s.prompt, self.s.snap = prompt, snap
        self.s.bump()
        while True:
            ans = self.s.answers.get()
            if ans is Aborted:
                raise Aborted
            if ans.get("id") == self.next_id:
                break
        with self.s.cond:
            self.s.prompt = None
        self.s.bump()
        return ans.get("value")

    def say(self, text: str):
        self.s.add("me", text)

    def snapshot(self, g, me) -> dict:
        s = g.stats
        tp = {i: round(sum(v) / len(v), 1) for i, v in sorted(g.stats.trade_prices.items()) if v}
        return {
            "phase": g.phase, "week": g.week, "weeks": g.cfg["weeks"], "day": g.day, "fair_days": g.cfg["fair_days"],
            "actions": g.A, "can_cook_later": g.can_cook_later,
            "me": {
                "idx": me.idx, "name": me.name, "role": me.role, "coins": me.coins, "profile": list(g.profile(me)),
                "raws": counts(me.raws), "dishes": counts(me.dishes),
                "orders": [{"id": o.id, "text": o.text(), "value": o.value, "can": g.can_fulfill(me, o)}
                           for o in me.open_orders],
            },
            "players": [{"idx": p.idx, "label": p.label, "name": p.name, "arch": p.agent.arch, "coins": p.coins,
                         "raws": sum(p.raws.values()), "dishes": sum(p.dishes.values()),
                         "orders": len(p.open_orders), "me": p is me} for p in g.players],
            "raws": [{"name": r, "base": b, "gain": g.gather_gain(me, r), "profile": r in g.profile(me)}
                     for r, b in g.c.raws.items()],
            "dishes": [{"name": d.name, "category": d.category, "base": d.base, "ingredients": d.ingredients,
                        "cost": g.cook_cost(me, d.name), "can": g.can_cook(me, d.name), "cheap": d.cheap,
                        "raw_cost": g.c.raw_cost(d.name)} for d in g.c.dishes.values()],
            "rumors": [f"{g.event_name(e)} — {e.window}" for e in g.rumors],
            "market_prices": {i: round(p, 1) for i, p in g.market.avg_prices().items()} if g.market else {},
            "game_prices": tp,
            "fair": None if g.phase == "prep" else {
                "sold": s.sold_units, "demand": s.demand_units, "push_ok": s.push_ok, "push_tries": s.push_tries,
                "stock": sum(sum(p.dishes.values()) for p in g.players)},
            "weather": g.weather_today,
            "order_deck": len(g.order_deck),
            "penalty": g.cfg["orders"]["penalty"],
        }

    # ------------------------------------------------------------ подготовка
    def on_week_start(self, g, me):
        if g.week == 1:
            cheap = [d.name for d in g.c.dishes.values() if d.cheap == me.role]
            self.say(f"Вы — {me.role}. Профильное сырьё: {', '.join(g.profile(me))} "
                     f"(+{g.cfg['gather_profile']} за действие, остальное +{g.cfg['gather_other']})."
                     + (f" Готовите за {g.cfg['cook_actions_cheap']} действие: {', '.join(cheap)}." if cheap else ""))

    def fulfill_by_id(self, g, me, oid) -> None:
        o = next((o for o in me.open_orders if o.id == oid), None)
        if o is None or not g.can_fulfill(me, o):
            self.say("Этот заказ сейчас не выполнить.")
        else:
            g.fulfill(me, o)

    def next_action(self, g, me, left):
        while True:
            v = self.ask(g, me, "action", left=left) or {}
            op = v.get("op")
            if op == "gather" and v.get("raw") in g.c.raws:
                return ("gather", v["raw"])
            if op == "cook" and v.get("dish") in g.c.dishes:
                d = v["dish"]
                if not g.can_cook(me, d):
                    self.say("Не хватает сырья.")
                elif g.cook_cost(me, d) > left:
                    self.say("Не хватает действий.")
                else:
                    return ("cook", d)
            elif op == "order":
                if g.order_deck:
                    return ("order",)
                self.say("Колода заказов пуста.")
            elif op == "fulfill":
                self.fulfill_by_id(g, me, v.get("order"))
            elif op == "end":
                return None

    def choose_order(self, g, me, cards):
        while True:
            i = self.ask(g, me, "choose_order",
                         cards=[{"text": c.text(), "items": c.items, "value": c.value} for c in cards])
            if isinstance(i, int) and 0 <= i < len(cards):
                return i

    # ------------------------------------------------------------ рынок
    def market_turn(self, g, me, market):
        while True:
            book = list(market.orders)
            v = self.ask(g, me, "market", book=[
                {"i": i, "player": o.player.name, "label": o.player.label, "mine": o.player is me,
                 "side": o.side, "item": o.item, "qty": o.qty, "price": o.price} for i, o in enumerate(book)
            ], bots=[{"idx": p.idx, "label": p.label, "coins": p.coins, "raws": counts(p.raws),
                      "dishes": counts(p.dishes)} for p in g.players if p is not me]) or {}
            op = v.get("op")
            if op == "hit":
                i, q = v.get("order"), int(v.get("qty") or 0)
                o = book[i] if isinstance(i, int) and 0 <= i < len(book) else None
                if o is None or o not in market.orders or o.player is me or q <= 0:
                    self.say("Заявка уже ушла.")
                elif not market.hit(me, o, q):
                    self.say("Не вышло: не хватает денег или товара.")
            elif op == "place":
                item, qty, price = v.get("item"), int(v.get("qty") or 0), int(v.get("price") or 0)
                if item in g.c.raws or item in g.c.dishes:
                    if qty > 0 and price > 0 and v.get("side") in ("buy", "sell"):
                        market.orders.append(MarketOrder(me, v["side"], item, qty, price))
                        market.match()
            elif op == "cancel":
                market.orders = [o for o in market.orders if o.player is not me]
            elif op == "propose":
                self.propose(g, me, v)
            elif op == "fulfill":
                self.fulfill_by_id(g, me, v.get("order"))
            elif op == "wait":
                return False
            elif op == "ready":
                return True

    def propose(self, g, me, v):
        bot = next((p for p in g.players if p.idx == v.get("bot") and p is not me), None)
        names = set(g.c.raws) | set(g.c.dishes) | {"монеты"}

        def clean(d):
            return {k: int(q) for k, q in (d or {}).items() if k in names and int(q) > 0}

        give, get = clean(v.get("give")), clean(v.get("get"))
        if bot is None or not (give or get):
            return
        what = f"вы отдаёте {fmt(give)}, получаете {fmt(get)}"
        if not has_items(g, me, give) or not has_items(g, bot, get):
            self.say(f"{bot.name}: сделка невозможна — у кого-то не хватает товара или денег ({what}).")
        elif not bot.agent.evaluate_deal(g, bot, give=get, get=give):
            self.say(f"{bot.name}: «Нет, мне невыгодно» ({what}).")
        elif not g.barter(me, bot, give, get):
            self.say("Сделка не прошла.")
        else:
            self.say(f"{bot.name}: «По рукам!» — {what}.")

    # ------------------------------------------------------------ продавец
    def seller_prices(self, g, me, card, stop_no):
        pos = [{"i": i, "dish": p.dish, "qty": p.qty, "base": g.c.dishes[p.dish].base,
                "category": g.c.dishes[p.dish].category, "have": me.dishes[p.dish]}
               for i, p in enumerate(card.positions) if p.qty > 0]
        v = self.ask(g, me, "seller_prices", buyer=card.player.name, stop=stop_no + 1,
                     stops=g.cfg["stops_per_buyer"], weather=g.weather_today, positions=pos) or {}
        return {int(i): int(p) for i, p in v.items() if p}

    def seller_accept_counter(self, g, me, card, dish, price):
        return bool(self.ask(g, me, "yesno", text=f"{card.player.name} предлагает {price} за «{dish}» "
                                                    f"(база {g.c.dishes[dish].base}). Принять?"))

    def seller_push(self, g, me, card):
        listed = {p.dish for p in card.positions}
        cands = [{"dish": d, "category": g.c.dishes[d].category, "base": g.c.dishes[d].base}
                 for d, q in me.dishes.items() if q > 0 and d not in listed]
        if not cands:
            return None
        v = self.ask(g, me, "seller_push", buyer=card.player.name, candidates=cands,
                     wanted=[f"{p.dish} ×{p.qty}" for p in card.positions if p.qty > 0])
        if not v or v.get("dish") not in {c["dish"] for c in cands} or not v.get("price"):
            return None
        return v["dish"], int(v["price"])

    # ------------------------------------------------------------ покупатель
    def card_data(self, g, card) -> dict:
        return {"weakness": card.weakness, "weak_mult": round(card.weak_mult, 2), "boost": card.boost,
                "boost_pct": round((card.boost_mult - 1) * 100),
                "positions": [{"i": i, "dish": p.dish, "qty": p.qty, "max": p.max, "base": g.c.dishes[p.dish].base}
                              for i, p in enumerate(card.positions) if p.qty > 0]}

    def buyer_respond(self, g, me, card, seller, offers, stop_no):
        v = self.ask(g, me, "buyer_respond", seller=seller.label, stop=stop_no + 1, stops=g.cfg["stops_per_buyer"],
                     card=self.card_data(g, card),
                     offers=[{"i": i, "price": p} for i, p in offers.items()]) or {}
        accepted = {int(i) for i in v.get("accept", []) if int(i) in offers}
        counter = v.get("counter")
        if counter and int(counter[0]) in offers and int(counter[0]) not in accepted and counter[1]:
            return accepted, (int(counter[0]), int(counter[1]))
        return accepted, None

    def buyer_push_counter(self, g, me, card, seller, dish, price, can_counter):
        wmax = card.weak_max(g.c.dishes[dish])
        if not can_counter:
            self.say(f"{seller.name} втюхивает {dish} за {price} — ваша слабость, но выше максимума {wmax}. "
                     "Встречную вы уже называли.")
            return None
        v = self.ask(g, me, "push_counter", seller=seller.name, dish=dish, price=price, max=wmax)
        return int(v) if v else None

    # ------------------------------------------------------------ события
    def tender_bid(self, g, me, dish, price, max_bid, first):
        v = self.ask(g, me, "tender", dish=dish, price=price, max_bid=max_bid, first=first,
                     count=g.cfg["tender"]["count"], base=g.c.dishes[dish].base)
        return int(v) if v else None

    def banquet_set(self, g, me):
        avail = [{"dish": d, "base": g.c.dishes[d].base} for d, q in me.dishes.items() if q > 0]
        if not avail:
            return []
        v = self.ask(g, me, "banquet", dishes=avail, max=g.cfg["banquet"]["max_dishes"],
                     bonus=round(g.cfg["banquet"]["bonus"] * 100))
        return [d for d in (v or []) if me.dishes[d] > 0]

    def on_game_end(self, g, me):
        self.say(f"Ваш счёт: {me.coins} монет.")


def fmt(items: dict) -> str:
    return ", ".join(f"{k} {v}" for k, v in items.items()) or "ничего"


# ------------------------------------------------------------ партия и сервер

class Host:
    def __init__(self, cfg_path, overrides: list[str], role: str | None, seed: int | None):
        self.cfg_path, self.overrides = cfg_path, overrides
        self.defaults = {"role": role or "", "seed": seed}
        self.s = Session()
        self.lock = threading.Lock()

    def roles(self) -> list[str]:
        return list(config.load(self.cfg_path, self.overrides)["roles"])

    def new_game(self, seed: int | None, role: str | None, players: int | None, verbose: bool = True):
        with self.lock:
            old = self.s
            if old.thread and old.thread.is_alive():
                old.answers.put(Aborted)
                old.thread.join(5)
            s = Session()
            s.seed = seed if seed is not None else random.randrange(1_000_000)
            ov = list(self.overrides) + ([f"players={players}"] if players else [])
            cfg = config.load(self.cfg_path, ov)
            human = WebHuman(s)
            g = make_game(cfg, s.seed, WebLog(s), human=human, human_role=role or None)
            s.add("me", f"Партия #{s.seed}. Соперники: " + ", ".join(
                f"{p.label} [{p.agent.arch}]" for p in g.players if p.agent is not human))

            def run():
                try:
                    g.run()
                except Aborted:
                    return
                except Exception as e:
                    traceback.print_exc()
                    s.error = f"{type(e).__name__}: {e}"
                me = g.players[0]
                with s.cond:
                    s.snap = human.snapshot(g, me)
                    s.snap["final"] = sorted(
                        ({"label": p.label, "arch": p.agent.arch, "coins": p.coins, "me": p is me,
                          "income": {k: v for k, v in g.stats.income[p.idx].items() if v}}
                         for p in g.players), key=lambda r: -r["coins"])
                    s.prompt = None
                    s.over = True
                s.bump()

            s.thread = threading.Thread(target=run, daemon=True)
            self.s = s
            old.bump()   # долгие опросы старой партии отпускаем
            s.thread.start()


def make_handler(host: Host):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code: int, body: bytes, ctype: str):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code: int = 200):
            self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

        def do_GET(self):
            u = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            if u.path in ("/", "/index.html"):
                self._send(200, HTML.read_bytes(), "text/html; charset=utf-8")
            elif u.path == "/api/meta":
                self._json({"roles": host.roles(), **host.defaults})
            elif u.path == "/api/state":
                s = host.s
                same = q.get("seed") == ("" if s.seed is None else str(s.seed))
                if "version" in q and same and int(q["version"]) == s.version:
                    s.wait(int(q["version"]))
                s = host.s
                self._json(s.state(int(q.get("since", 0))))
            else:
                self._send(404, b"not found", "text/plain")

        def do_POST(self):
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                if self.path == "/api/new":
                    seed = body.get("seed")
                    host.new_game(int(seed) if seed not in (None, "") else None, body.get("role") or None,
                                  int(body["players"]) if body.get("players") else None)
                    self._json({"seed": host.s.seed})
                elif self.path == "/api/answer":
                    host.s.answers.put({"id": body.get("id"), "value": body.get("value")})
                    self._json({"ok": True})
                else:
                    self._send(404, b"not found", "text/plain")
            except Exception as e:
                traceback.print_exc()
                self._json({"errors": [f"{type(e).__name__}: {e}"]}, 500)

    return Handler


def serve(cfg_path, overrides: list[str], port: int = 8766, open_browser: bool = True,
          role: str | None = None, seed: int | None = None):
    host = Host(cfg_path, overrides, role, seed)
    srv = ThreadingHTTPServer(("127.0.0.1", port), make_handler(host))
    srv.daemon_threads = True
    url = f"http://127.0.0.1:{port}/"
    print(f"Плейтест ярмарки: {url}  (Ctrl+C — выход)")
    if open_browser:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
