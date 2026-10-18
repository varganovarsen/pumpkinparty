"""Движок «Осенней ярмарки»: правила, ход партии, деньги. Решения принимают агенты (боты или человек).

Ход: раздача ролей → 4 недели (работа, рынок; слухи в начале недель 2-4) → 5 дней ярмарки
(события утром, половины продают по очереди, рынок между днями) → послеярмарочный рынок → подсчёт.
"""
from __future__ import annotations

import math
import random
from collections import Counter
from dataclasses import dataclass, field

from .config import Content
from .stats import GameStats


# ---------------------------------------------------------------- модель

@dataclass
class Order:
    id: int
    items: dict[str, int]
    value: int
    done: bool = False

    def text(self) -> str:
        return ", ".join(f"{d} ×{q}" for d, q in self.items.items()) + f" — {self.value} мон."


@dataclass
class Position:
    dish: str
    qty: int
    max: int


@dataclass
class BuyerCard:
    id: int
    player: "Player"
    positions: list[Position]
    weakness: str
    weak_mult: float
    boost: str | None          # категория погоды этого дня
    boost_mult: float
    visited: set = field(default_factory=set)
    stops: int = 0

    @property
    def done(self) -> bool:
        return all(p.qty == 0 for p in self.positions)

    def weak_max(self, dish) -> int:
        m = dish.base * self.weak_mult
        if dish.category == self.boost:
            m *= self.boost_mult
        return round(m)


@dataclass
class Event:
    kind: str
    day: int
    window: str


@dataclass
class MarketOrder:
    player: "Player"
    side: str       # buy | sell
    item: str
    qty: int
    price: int


class Player:
    def __init__(self, idx: int, name: str, role: str, agent, coins: int):
        self.idx, self.name, self.role, self.agent = idx, name, role, agent
        self.coins = coins
        self.raws: Counter = Counter()
        self.dishes: Counter = Counter()
        self.orders: list[Order] = []

    @property
    def open_orders(self) -> list[Order]:
        return [o for o in self.orders if not o.done]

    @property
    def label(self) -> str:
        return f"{self.name} ({self.role})"

    def __repr__(self):
        return self.label


class Agent:
    """Интерфейс решений. Человек и боты реализуют одни и те же методы."""
    human = False
    arch = "?"

    def on_week_start(self, g, me): ...
    def next_action(self, g, me, left): ...            # ('gather', raw) | ('cook', dish) | ('order',) | None
    def choose_order(self, g, me, cards): ...          # индекс карточки
    def market_orders(self, g, me): return []          # заявки ботов
    def market_turn(self, g, me, market): return True  # человек; True — готов
    def evaluate_deal(self, g, me, give, get): return False  # give/get: {item|'монеты': qty} со стороны me
    def auto_fulfill(self, g, me): return False
    def seller_prices(self, g, me, card, stop_no): ...       # {idx позиции: цена}
    def seller_accept_counter(self, g, me, card, dish, price): ...
    def seller_push(self, g, me, card): ...                  # (dish, price) | None
    def buyer_respond(self, g, me, card, seller, offers, stop_no): ...  # (set принятых idx, (idx, цена) | None)
    def buyer_push_counter(self, g, me, card, seller, dish, price, can_counter): ...  # цена | None
    def tender_bid(self, g, me, dish, price, max_bid, first): ...  # цена | None
    def banquet_set(self, g, me): ...                        # список блюд
    def on_game_end(self, g, me): ...


class Log:
    """info — события партии, detail — сделки ботов между собой."""

    def __init__(self, info=False, detail=False):
        self.show_info, self.show_detail = info, detail

    def info(self, msg=""):
        if self.show_info:
            print(msg)

    def detail(self, msg):
        if self.show_detail:
            print("   · " + msg)


# ---------------------------------------------------------------- игра

class Game:
    def __init__(self, cfg: dict, agents: list, rng: random.Random, log: Log | None = None,
                 names: list[str] | None = None):
        self.cfg, self.rng = cfg, rng
        self.c = Content(cfg)
        self.log = log or Log()
        n = len(agents)
        if n < 2:
            raise ValueError("нужно хотя бы 2 игрока")
        roles = list(self.c.roles)
        # полные круги ролей, остаток — разные роли по жребию (иначе при 10 игроках четверо всегда у первой роли)
        deck = roles * (n // len(roles)) + rng.sample(roles, n % len(roles))
        rng.shuffle(deck)
        names = names or [f"Бот{i + 1}" for i in range(n)]
        self.players = [Player(i, names[i], deck[i], agents[i], cfg["start_coins"]) for i in range(n)]
        self.stats = GameStats(self)
        self.week = 0
        self.day = 0
        self.phase = "prep"     # prep | fair | after
        self.events: list[Event] = []
        self.rumors: list[Event] = []
        self.tender_dish: str | None = None
        self.order_deck: list[Order] = []
        self.next_card_id = 0
        self.raw_demand: dict[str, float] = {}
        self.market: Market | None = None
        self.weather_today: str | None = None
        self.can_cook_later = True     # будут ещё работы (сырьё на рынке чего-то стоит)
        self.demand_weights = self._demand_weights()

    # --- справки для агентов
    @property
    def A(self) -> int:
        return self.cfg["actions_per_week"]

    def profile(self, p: Player) -> tuple[str, ...]:
        return self.c.roles[p.role]

    def rule(self, p: Player, key: str):
        """Число правил с поправкой на роль (role_rules), иначе общее."""
        return (self.cfg.get("role_rules") or {}).get(p.role, {}).get(key, self.cfg[key])

    def gather_gain(self, p: Player, raw: str) -> int:
        return self.rule(p, "gather_profile") if raw in self.profile(p) else self.rule(p, "gather_other")

    def cook_cost(self, p: Player, dish: str) -> int:
        return self.cfg["cook_actions_cheap"] if self.c.dishes[dish].cheap == p.role else self.rule(p, "cook_actions")

    def can_cook(self, p: Player, dish: str) -> bool:
        return all(p.raws[r] >= q for r, q in self.c.dishes[dish].ingredients.items())

    def order_need(self, p: Player) -> Counter:
        need = Counter()
        for o in p.open_orders:
            need.update(o.items)
        return need

    def order_deficit(self, p: Player) -> Counter:
        need = self.order_need(p)
        return Counter({d: q - p.dishes[d] for d, q in need.items() if q > p.dishes[d]})

    def actions_after_this_week(self) -> int:
        return max(0, self.cfg["weeks"] - self.week) * self.A

    def weather_category(self, kind: str) -> str | None:
        return self.cfg["events"]["weather"].get(kind)

    def human(self) -> Player | None:
        return next((p for p in self.players if p.agent.human), None)

    # --- партия
    def run(self) -> GameStats:
        self._setup_events()
        self._setup_orders()
        for w in range(1, self.cfg["weeks"] + 1):
            self.week = w
            self._week()
        self.phase = "fair"
        self.stats.dishes_before_fair = {p.idx: sum(p.dishes.values()) for p in self.players}
        self.stats.raws_left_prep = sum(sum(p.raws.values()) for p in self.players)
        for d in range(1, self.cfg["fair_days"] + 1):
            self.day = d
            self._fair_day()
            if d < self.cfg["fair_days"]:
                self._market(f"Торг после дня {d}")
        self.phase = "after"
        self._market("Послеярмарочный рынок")
        self._score()
        return self.stats

    # --- подготовка
    def _setup_events(self):
        ev = self.cfg["events"]
        windows = ev["windows"]
        day_window = {d: w for w, ds in windows.items() for d in ds}
        for _ in range(1000):
            kinds = self.rng.sample(ev["pool"], ev["count"])
            if not any(all(k in kinds for k in ex) for ex in ev["exclusive"]):
                break
        days = self.rng.sample(range(1, self.cfg["fair_days"] + 1), ev["count"])
        self.events = sorted((Event(k, d, day_window.get(d, f"в день {d}")) for k, d in zip(kinds, days)),
                             key=lambda e: e.day)
        if any(e.kind == "tender" for e in self.events):
            self.tender_dish = self.rng.choice(list(self.c.dishes))
        self.rumor_queue = self.events[:]
        self.rng.shuffle(self.rumor_queue)

    def event_name(self, e: Event) -> str:
        t = self.cfg["tender"]
        names = {
            "tender": "приедет ресторатор с большим заказом (тендер)"
                      + (f" на «{self.tender_dish}»" if t["dish_in_rumor"] and self.tender_dish else ""),
            "banquet": "будет банкет — гость ценит разнообразие",
            "cold": "обещают холодный день (горячее дороже)",
            "hot": "обещают жаркий день (холодное дороже)",
            "sweet": "придут сладкоежки (сладкое дороже)",
            "salty": "придут любители солёного (солёное дороже)",
        }
        return names[e.kind]

    def _setup_orders(self):
        o = self.cfg["orders"]
        dishes = list(self.c.dishes)
        for i in range(o["deck_size"]):
            k = self.rng.randint(*o["dishes"])
            items = {d: self.rng.randint(*o["qty"]) for d in self.rng.sample(dishes, k)}
            value = sum(self.c.dishes[d].base * q for d, q in items.items())
            self.order_deck.append(Order(i + 1, items, value))
        self.rng.shuffle(self.order_deck)

    def _week(self):
        self.log.info(f"\n══════ Неделя {self.week} ══════")
        if self.week in self.cfg["rumor_weeks"] and self.rumor_queue:
            e = self.rumor_queue.pop()
            self.rumors.append(e)
            self.log.info(f"Слух: говорят, {self.event_name(e)} — {e.window}.")
        for p in self.players:
            p.agent.on_week_start(self, p)
        self._update_raw_demand()
        order = self.players[:]
        self.rng.shuffle(order)
        if not self.cfg["market"].get("during_work"):
            for p in order:
                left = self.A
                while left > 0:
                    act = p.agent.next_action(self, p, left)
                    if act is None:
                        break
                    left -= self.do_action(p, act)
                self._auto_fulfill(p)
            self.can_cook_later = self.week < self.cfg["weeks"]
            self._market(f"Рынок недели {self.week}")
            self._spoil()
            return
        # работа и торговля вместе: шаг — каждый делает одно действие (бесплатные — сколько хочет), затем раунд рынка
        self.log.info(f"\n— Работа и рынок недели {self.week} —")
        self.market = Market(self)
        left = {p.idx: self.A for p in self.players}
        human = self.human()
        for step in range(self.A):
            for p in order:
                while left[p.idx] > 0:
                    act = p.agent.next_action(self, p, left[p.idx])
                    if act is None:
                        left[p.idx] = 0
                        break
                    cost = self.do_action(p, act)
                    left[p.idx] -= cost
                    if cost:
                        break
                self._auto_fulfill(p)
            if step == self.A - 1:
                self.can_cook_later = self.week < self.cfg["weeks"]
            self._update_raw_demand()
            for _ in range(self.cfg["market"]["rounds_during_work"]):
                self.market.bot_round()
                for p in self.players:
                    self._auto_fulfill(p)
            if human is not None:
                human.agent.market_turn(self, human, self.market)
        self.market = None
        self._spoil()

    def _spoil(self):
        """Конец недели: часть каждого запаса сырья портится (накопительство не бесплатно)."""
        share = self.cfg.get("spoil", 0)
        if not share or self.week >= self.cfg["weeks"]:
            return
        for p in self.players:
            for r, q in p.raws.items():
                lost = math.floor(q * share)
                if lost:
                    p.raws[r] -= lost
                    self.stats.spoiled += lost
                    if p.agent.human:
                        self.log.info(f"Испортилось: {r} −{lost}")

    def _update_raw_demand(self):
        """Грубая оценка спроса на сырьё (заменяет разговоры на рынке): дефицит / излишек по всем ботам."""
        deficit, surplus = Counter(), Counter()
        for p in self.players:
            need = getattr(p.agent, "raw_need", None)
            if not need:
                continue
            n = need(self, p)
            for r in self.c.raws:
                if n[r] > p.raws[r]:
                    deficit[r] += n[r] - p.raws[r]
                else:
                    surplus[r] += p.raws[r] - n[r]
        self.raw_demand = {r: max(0.2, min(2.0, deficit[r] / max(3, surplus[r]))) for r in self.c.raws}

    def do_action(self, p: Player, act) -> int:
        """Выполнить действие, вернуть сколько действий оно стоило."""
        kind = act[0]
        if kind == "gather":
            raw = act[1]
            gain = self.gather_gain(p, raw)
            p.raws[raw] += gain
            self.stats.produced[raw] += gain
            self.log.detail(f"{p.label} собирает {raw} +{gain}")
            return 1
        if kind == "cook":
            dish = act[1]
            if not self.can_cook(p, dish):
                raise ValueError(f"{p.label}: не хватает сырья на {dish}")
            for r, q in self.c.dishes[dish].ingredients.items():
                p.raws[r] -= q
                self.stats.consumed[r] += q
            p.dishes[dish] += 1
            self.stats.cooked[p.idx] += 1
            self.stats.cooked_dish[dish] += 1
            self.log.detail(f"{p.label} готовит {dish}")
            return self.cook_cost(p, dish)
        if kind == "order":
            k = min(self.cfg["orders"]["choices"], len(self.order_deck))
            if k == 0:
                raise ValueError("колода заказов пуста")
            cards = [self.order_deck.pop() for _ in range(k)]
            i = p.agent.choose_order(self, p, cards)
            chosen = cards.pop(i)
            p.orders.append(chosen)
            self.order_deck.extend(cards)
            self.rng.shuffle(self.order_deck)
            self.stats.orders_taken[p.idx] += 1
            self.stats.orders_value += chosen.value
            self.log.detail(f"{p.label} берёт заказ: {chosen.text()}")
            return 1
        raise ValueError(f"неизвестное действие {act}")

    # --- заказы
    def can_fulfill(self, p: Player, o: Order) -> bool:
        return not o.done and all(p.dishes[d] >= q for d, q in o.items.items())

    def fulfill(self, p: Player, o: Order):
        if not self.can_fulfill(p, o):
            raise ValueError("не хватает блюд для заказа")
        for d, q in o.items.items():
            p.dishes[d] -= q
        o.done = True
        p.coins += o.value
        self.stats.add(p, "orders", o.value)
        self.log.info(f"{p.label} выполняет заказ: {o.text()}")

    def _auto_fulfill(self, p: Player):
        if p.agent.auto_fulfill(self, p):
            for o in p.open_orders:
                if self.can_fulfill(p, o):
                    self.fulfill(p, o)

    # --- рынок
    def _market(self, title: str):
        self.log.info(f"\n— {title} —")
        self.market = Market(self)
        human = self.human()
        rounds = self.cfg["market"]["rounds"]
        ready = human is None
        for r in range(rounds):
            self.market.bot_round()
            for p in self.players:
                self._auto_fulfill(p)
            if not ready:
                ready = human.agent.market_turn(self, human, self.market)
        if not ready:
            human.agent.market_turn(self, human, self.market)
        self.market = None

    def transfer(self, seller: Player, buyer: Player, item: str, qty: int, price: int) -> bool:
        """Сделка на рынке: seller отдаёт qty item, buyer платит price за штуку. Проверяет запасы."""
        stock = seller.raws if item in self.c.raws else seller.dishes
        mine = buyer.raws if item in self.c.raws else buyer.dishes
        qty = min(qty, stock[item], buyer.coins // price if price > 0 else qty)
        if qty <= 0:
            return False
        stock[item] -= qty
        mine[item] += qty
        buyer.coins -= qty * price
        seller.coins += qty * price
        self.stats.add(seller, "market_in", qty * price)
        self.stats.add(buyer, "market_out", qty * price)
        self.stats.trades += 1
        self.stats.trade_volume += qty * price
        if self.market:
            self.market.history.append((item, qty, price))
        self.stats.trade_prices[item].append(price)
        msg = f"сделка: {seller.label} → {buyer.label}: {item} ×{qty} по {price}"
        if seller.agent.human or buyer.agent.human:
            self.log.info(msg)
        else:
            self.log.detail(msg)
        return True

    def barter(self, a: Player, b: Player, give: dict, get: dict) -> bool:
        """Обмен: a отдаёт give, получает get (ключ 'монеты' — деньги)."""
        def has(p, items):
            for k, q in items.items():
                if k == "монеты":
                    if p.coins < q:
                        return False
                elif (p.raws if k in self.c.raws else p.dishes)[k] < q:
                    return False
            return True

        def move(src, dst, items):
            for k, q in items.items():
                if k == "монеты":
                    src.coins -= q
                    dst.coins += q
                    self.stats.add(src, "market_out", q)
                    self.stats.add(dst, "market_in", q)
                else:
                    (src.raws if k in self.c.raws else src.dishes)[k] -= q
                    (dst.raws if k in self.c.raws else dst.dishes)[k] += q

        if not (has(a, give) and has(b, get)):
            return False
        move(a, b, give)
        move(b, a, get)
        self.stats.trades += 1
        return True

    # --- ярмарка
    def _demand_weights(self) -> dict[str, float]:
        d = self.cfg["demand"]
        w = {}
        for name, dish in self.c.dishes.items():
            v = d["base_weight"]
            for p in self.players:
                if dish.main in self.profile(p):
                    v += d["main_ingredient_weight"]
                if dish.cheap == p.role:
                    v += d["cheap_cook_weight"]
            w[name] = v
        return w

    def make_card(self, player: Player, sellers: list[Player] | None = None) -> BuyerCard:
        b = self.cfg["buyer"]
        names = list(self.demand_weights)
        # покупатели идут на то, что лежит на прилавках: + за каждую порцию у продающих, на продавца
        k = self.cfg["demand"].get("stock_weight", 0) / max(1, len(sellers or ()))
        weights = [self.demand_weights[n] + k * sum(s.dishes[n] for s in sellers or ()) for n in names]
        k = self.rng.randint(*b["positions"])
        chosen = []
        while len(chosen) < min(k, len(names)):
            d = self.rng.choices(names, weights)[0]
            if d not in chosen:
                chosen.append(d)
        qtys, qw = zip(*((int(q), w) for q, w in b["qty_weights"].items()))
        boost_mult = 1 + self.cfg["events"]["weather_bonus"]
        positions = []
        for d in chosen:
            dish = self.c.dishes[d]
            m = dish.base * self.rng.uniform(*b["max_range"])
            if dish.category == self.weather_today:
                m *= boost_mult
            positions.append(Position(d, self.rng.choices(qtys, qw)[0], max(1, round(m))))
        self.next_card_id += 1
        return BuyerCard(self.next_card_id, player, positions, self.rng.choice(self.c.categories),
                         self.rng.uniform(*b["weakness_range"]), self.weather_today, boost_mult)

    def _fair_day(self):
        d = self.day
        todays = [e for e in self.events if e.day == d]
        self.weather_today = next((self.weather_category(e.kind) for e in todays if self.weather_category(e.kind)), None)
        self.log.info(f"\n══════ Ярмарка, день {d} ══════")
        if self.weather_today:
            self.log.info(f"Погода и настроение: {self.weather_today} сегодня дороже на "
                          f"{round(self.cfg['events']['weather_bonus'] * 100)}%.")
        self.stats.stock_by_day.append(sum(sum(p.dishes.values()) for p in self.players))
        order = self.players[:]
        self.rng.shuffle(order)
        half = (len(order) + 1) // 2
        a, b = order[:half], order[half:]
        for e in todays:
            if e.kind == "tender":
                self._tender()
            elif e.kind == "banquet":
                self._banquet()
        self._half(a, b, "утро")
        self._half(b, a, "вечер")

    def _half(self, sellers: list[Player], buyers: list[Player], label: str):
        self.log.info(f"\n{label.capitalize()}: продают {', '.join(p.name for p in sellers)}")
        base = len(buyers)
        if self.cfg["fill_idle_stands"]:
            base = max(base, len(sellers))
        n_cards = round(base * self.cfg["buyers_per_player"])
        players_cycle = buyers[:]
        self.rng.shuffle(players_cycle)
        cards = [self.make_card(players_cycle[i % len(players_cycle)], sellers) for i in range(n_cards)]
        half_demand = sum(p.qty for c in cards for p in c.positions)
        self.stats.demand_units += half_demand
        sold_before = self.stats.sold_units
        for slot in range(self.cfg["stops_per_buyer"]):
            active = [c for c in cards if not c.done]
            self.rng.shuffle(active)
            free = sellers[:]
            for c in active:
                options = [s for s in free if s.idx not in c.visited and s is not c.player]
                if not options:
                    continue
                s = self.rng.choice(options)
                free.remove(s)
                c.visited.add(s.idx)
                self._stop(c, s, slot)
        self.stats.sold_by_day[self.day - 1] += self.stats.sold_units - sold_before
        self.log.info(f"{label.capitalize()}: покупателей {len(cards)}, продано порций "
                      f"{self.stats.sold_units - sold_before} из {half_demand} в списках")

    def sell(self, seller: Player, card: BuyerCard, dish: str, qty: int, price: int, maxp: int, kind: str):
        seller.dishes[dish] -= qty
        seller.coins += price * qty
        self.stats.add(seller, "push" if kind == "push" else "fair", price * qty)
        self.stats.sold_units += qty
        self.stats.sold_price_ratio.append(price / self.c.dishes[dish].base)
        if self.cfg["buyer"]["pays_bonus"]:
            bonus = (maxp - price) * qty
            card.player.coins += bonus
            self.stats.add(card.player, "buyer", bonus)
        if kind == "push":
            self.stats.push_ok += 1
        msg = (f"{seller.name} продаёт {dish} ×{qty} по {price} (макс {maxp}"
               f"{', втюхивание' if kind == 'push' else ''}) покупателю {card.player.name}")
        if seller.agent.human or card.player.agent.human:
            self.log.info("  ✓ " + msg)
        else:
            self.log.detail(msg)

    def _stop(self, card: BuyerCard, seller: Player, slot: int):
        buyer = card.player
        card.stops += 1
        self.stats.stops += 1
        counter_used = False
        open_idx = [i for i, p in enumerate(card.positions) if p.qty > 0]
        prices = {}
        if any(seller.dishes[card.positions[i].dish] > 0 for i in open_idx):
            prices = seller.agent.seller_prices(self, seller, card, slot) or {}
            prices = {i: int(pr) for i, pr in prices.items()
                      if i in open_idx and pr and pr > 0 and seller.dishes[card.positions[i].dish] > 0}
        if prices:
            accepted, counter = buyer.agent.buyer_respond(self, buyer, card, seller, dict(prices), slot)
            for i in accepted:
                pos = card.positions[i]
                if prices[i] <= pos.max:   # программа не даёт принять цену выше максимума
                    q = min(pos.qty, seller.dishes[pos.dish])
                    if q > 0:
                        self.sell(seller, card, pos.dish, q, prices[i], pos.max, "list")
                        pos.qty -= q
            if counter:
                i, cp = counter
                counter_used = True
                if i in prices and i not in accepted and card.positions[i].qty > 0:
                    pos = card.positions[i]
                    cp = min(int(cp), pos.max)
                    if cp > 0 and seller.dishes[pos.dish] > 0:
                        ok = seller.agent.seller_accept_counter(self, seller, card, pos.dish, cp)
                        self.stats.counters += 1
                        if ok:
                            self.stats.counters_ok += 1
                            q = min(pos.qty, seller.dishes[pos.dish])
                            self.sell(seller, card, pos.dish, q, cp, pos.max, "list")
                            pos.qty -= q
                        elif seller.agent.human or buyer.agent.human:
                            self.log.info(f"  ✗ {seller.name} не принял встречную {cp} за {pos.dish}")
        # втюхивание: список закрыт или нужных блюд у продавца нет
        rest = [p for p in card.positions if p.qty > 0]
        listed = {p.dish for p in card.positions}
        if all(seller.dishes[p.dish] == 0 for p in rest) and any(
                q > 0 and d not in listed for d, q in seller.dishes.items()):
            offer = seller.agent.seller_push(self, seller, card)
            if offer:
                dish, price = offer
                if dish in listed or seller.dishes[dish] <= 0:
                    return
                self.stats.push_tries += 1
                dobj = self.c.dishes[dish]
                wmax = card.weak_max(dobj)
                if dobj.category != card.weakness:
                    if seller.agent.human or buyer.agent.human:
                        self.log.info(f"  ✗ втюхивание: {dish} за {price} — не слабость покупателя, отказ")
                    return
                if price <= wmax:
                    self.sell(seller, card, dish, 1, price, wmax, "push")
                    return
                cp = buyer.agent.buyer_push_counter(self, buyer, card, seller, dish, price, not counter_used)
                if cp and not counter_used:
                    cp = min(int(cp), wmax)
                    if seller.agent.seller_accept_counter(self, seller, card, dish, cp):
                        self.sell(seller, card, dish, 1, cp, wmax, "push")
                        return
                if seller.agent.human or buyer.agent.human:
                    self.log.info(f"  ✗ втюхивание {dish}: цена выше максимума, не сошлись")

    # --- события
    def _tender(self):
        t = self.cfg["tender"]
        dish = self.tender_dish
        base = self.c.dishes[dish].base
        n = t["count"]
        parts = [p for p in self.players if p.dishes[dish] >= n]
        price = round(base * t["start"])
        self.log.info(f"\nТЕНДЕР: {n} × «{dish}», старт {price} за штуку. Участники: "
                      f"{', '.join(p.name for p in parts) or 'никого'}")
        self.stats.tenders += 1
        self.stats.tender_parts += len(parts)
        if not parts:
            self.stats.tender_empty += 1
            return
        leader = None
        while True:
            moved = False
            order = parts[:]
            self.rng.shuffle(order)
            for p in order:
                if p is leader:
                    continue
                first = leader is None
                max_bid = price if first else min(price - 1, math.floor(price * (1 - t["step"])))
                if max_bid <= 0:
                    continue
                b = p.agent.tender_bid(self, p, dish, price, max_bid, first)
                if b is not None and 0 < int(b) <= max_bid:
                    price, leader, moved = int(b), p, True
                    self.log.info(f"  {p.name}: {price}")
            if not moved:
                break
        if leader is None:
            return
        leader.dishes[dish] -= n
        leader.coins += price * n
        self.stats.add(leader, "tender", price * n)
        self.stats.tender_ratio.append(price / base)
        self.log.info(f"  Тендер выигрывает {leader.label}: {n} × {price} = {price * n}")

    def _banquet(self):
        b = self.cfg["banquet"]
        subs = {}
        for p in self.players:
            s = p.agent.banquet_set(self, p) or []
            s = list(dict.fromkeys(d for d in s if p.dishes[d] > 0))[:b["max_dishes"]]
            if s:
                subs[p.idx] = s
        self.stats.banquets += 1
        self.log.info("\nБАНКЕТ: наборы — " + ("; ".join(
            f"{self.players[i].name}: {len(s)} блюд" for i, s in subs.items()) or "никто не подал"))
        if not subs:
            return
        best = max(subs, key=lambda i: (len(subs[i]), sum(self.c.dishes[d].base for d in subs[i]), self.rng.random()))
        p = self.players[best]
        s = subs[best]
        total = round(sum(self.c.dishes[d].base for d in s) * (1 + b["bonus"]))
        for d in s:
            p.dishes[d] -= 1
        p.coins += total
        self.stats.add(p, "banquet", total)
        self.stats.banquet_size.append(len(s))
        self.log.info(f"  Банкет выигрывает {p.label}: {len(s)} блюд за {total}")

    # --- подсчёт
    def _score(self):
        pen = self.cfg["orders"]["penalty"]
        for p in self.players:
            for o in p.open_orders:
                fine = round(o.value * pen)
                p.coins -= fine
                self.stats.add(p, "penalty", fine)
                self.stats.orders_failed[p.idx] += 1
            self.stats.orders_done[p.idx] = sum(1 for o in p.orders if o.done)
            self.stats.dishes_left += sum(p.dishes.values())
            p.agent.on_game_end(self, p)
        self.stats.finish()
        self.log.info("\n══════ Итог ══════")
        for p in sorted(self.players, key=lambda p: -p.coins):
            inc = self.stats.income[p.idx]
            self.log.info(f"{p.coins:>5}  {p.label:<24} [{p.agent.arch}]  " + ", ".join(
                f"{k} {v:+}" if k not in ("penalty", "market_out") else f"{k} −{v}"
                for k, v in inc.items() if v))


class Market:
    """Стакан заявок одного рынка. Боты переставляют заявки каждый раунд, заявки человека живут до конца рынка."""

    def __init__(self, g: Game):
        self.g = g
        self.orders: list[MarketOrder] = []
        self.history: list[tuple[str, int, int]] = []

    def bot_round(self):
        g = self.g
        self.orders = [o for o in self.orders if o.player.agent.human]
        for p in g.players:
            if not p.agent.human:
                for side, item, qty, price in p.agent.market_orders(g, p):
                    if qty > 0 and price > 0:
                        self.orders.append(MarketOrder(p, side, item, qty, price))
        self.match()

    def match(self):
        g = self.g
        for item in {o.item for o in self.orders}:
            while True:
                bids = sorted((o for o in self.orders if o.item == item and o.side == "buy" and o.qty > 0),
                              key=lambda o: (-o.price, g.rng.random()))
                asks = sorted((o for o in self.orders if o.item == item and o.side == "sell" and o.qty > 0),
                              key=lambda o: (o.price, g.rng.random()))
                pair = next(((b, a) for b in bids for a in asks
                             if b.price >= a.price and b.player is not a.player), None)
                if not pair:
                    break
                b, a = pair
                price = (b.price + a.price) // 2
                before = b.player.coins
                stock = (a.player.raws if item in g.c.raws else a.player.dishes)[item]
                q = min(b.qty, a.qty, stock, before // price if price else b.qty)
                if q <= 0 or not g.transfer(a.player, b.player, item, q, price):
                    # заявку исполнить нельзя (нет денег или товара) — снимаем
                    (b if before < price else a).qty = 0
                    continue
                b.qty -= q
                a.qty -= q
        self.orders = [o for o in self.orders if o.qty > 0]

    def hit(self, me: Player, order: MarketOrder, qty: int) -> bool:
        """Человек исполняет чужую заявку по её цене."""
        qty = min(qty, order.qty)
        ok = (self.g.transfer(order.player, me, order.item, qty, order.price) if order.side == "sell"
              else self.g.transfer(me, order.player, order.item, qty, order.price))
        if ok:
            order.qty -= qty
            self.orders = [o for o in self.orders if o.qty > 0]
        return ok

    def avg_prices(self) -> dict[str, float]:
        tot, cnt = Counter(), Counter()
        for item, q, p in self.history:
            tot[item] += q * p
            cnt[item] += q
        return {i: tot[i] / cnt[i] for i in cnt}
