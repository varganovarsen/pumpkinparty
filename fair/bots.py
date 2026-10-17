"""Боты. Один класс, поведение задают параметры архетипа из config.yaml (bots.archetypes)."""
from __future__ import annotations

import math
from collections import Counter

from .engine import Agent


def lerp(rng: list, q: float) -> float:
    """Точка внутри диапазона правил: q=0 — нижняя граница, q=1 — верхняя (можно выходить за края)."""
    return rng[0] + (rng[1] - rng[0]) * q


def archetype_params(cfg: dict, name: str) -> dict:
    b = cfg["bots"]
    if name not in b["archetypes"]:
        raise KeyError(f"нет архетипа {name}; есть: {', '.join(b['archetypes'])}")
    return {**b["defaults"], **(b["archetypes"][name] or {})}


class Bot(Agent):
    def __init__(self, arch: str, params: dict, rng):
        self.arch, self.P, self.rng = arch, params, rng
        self.plan: Counter = Counter()     # блюда, которые ещё собирается приготовить
        self.orders_this_week = 0
        self.dirty = True
        self.taste: dict[str, float] = {}  # личные вкусы: игроки не ходят стадом за одним блюдом

    # ------------------------------------------------------------ план
    def on_week_start(self, g, me):
        self.orders_this_week = 0
        self.replan(g, me, g.A + g.actions_after_this_week())

    def replan(self, g, me, remaining: int):
        plan = Counter(g.order_deficit(me))
        have = sum(me.dishes.values())
        dishes = list(g.c.dishes)
        while sum(plan.values()) + have < self.P["target_dishes"]:
            self.rng.shuffle(dishes)
            d = max(dishes, key=lambda x: self.dish_score(g, me, x, plan))
            if self.dish_score(g, me, d, plan) <= 0:
                break
            plan[d] += 1
            if self.actions_needed(g, me, plan) > remaining:
                plan[d] -= 1
                break
        self.plan = +plan
        self.dirty = False

    def dish_score(self, g, me, d: str, plan: Counter) -> float:
        P = self.P
        dish = g.c.dishes[d]
        bonus = 0.0
        for e in g.rumors:
            cat = g.weather_category(e.kind)
            if cat == dish.category:
                bonus += g.cfg["events"]["weather_bonus"] * 0.4 * P["event_focus"]
            elif e.kind == "banquet" and plan[d] == 0 and me.dishes[d] == 0:
                bonus += g.cfg["banquet"]["bonus"] * 0.3 * P["event_focus"]
            elif e.kind == "tender" and g.cfg["tender"]["dish_in_rumor"] and d == g.tender_dish:
                bonus += 0.5 * P["event_focus"]
        price = dish.base * (1 + bonus)
        prof = g.profile(me)
        cost = sum(q * g.c.raws[r] * (P["profile_cost"] if r in prof else P["buy_cost"])
                   for r, q in dish.ingredients.items())
        cost += g.cook_cost(me, d) * P["action_value"]
        if d not in self.taste:
            self.taste[d] = self.rng.uniform(-1, 1) * P["taste_noise"]
        return price - cost - P["diversity"] * (plan[d] + me.dishes[d]) + self.taste[d]

    def raw_need(self, g, me) -> Counter:
        need = Counter()
        for d, q in self.plan.items():
            for r, k in g.c.dishes[d].ingredients.items():
                need[r] += k * q
        return need

    def actions_needed(self, g, me, plan: Counter) -> float:
        need, acts = Counter(), 0.0
        for d, q in plan.items():
            acts += g.cook_cost(me, d) * q
            for r, k in g.c.dishes[d].ingredients.items():
                need[r] += k * q
        for r, n in need.items():
            deficit = max(0, n - me.raws[r])
            if r in g.profile(me):
                acts += math.ceil(deficit / g.cfg["gather_profile"])
            else:
                acts += deficit * self.P["self_gather_share"]
        return acts

    # ------------------------------------------------------------ работа
    def next_action(self, g, me, left):
        P = self.P
        if self.dirty:
            self.replan(g, me, left + g.actions_after_this_week())
        remaining = left + g.actions_after_this_week()
        tight = self.actions_needed(g, me, self.plan) >= remaining - 1
        if g.week >= P["cook_from_week"] or tight:
            for d in self.cook_order(g, me):
                if g.can_cook(me, d) and g.cook_cost(me, d) <= left:
                    self.plan[d] -= 1
                    self.plan = +self.plan
                    return ("cook", d)
        if (len(me.open_orders) < P["max_orders"] and g.week <= P["order_until_week"]
                and self.orders_this_week < P["orders_per_week"] and g.order_deck
                and self.actions_needed(g, me, self.plan) <= remaining * P["order_load"]):
            self.orders_this_week += 1
            return ("order",)
        return ("gather", self.best_gather(g, me))

    def cook_order(self, g, me):
        deficit = g.order_deficit(me)
        return sorted(self.plan, key=lambda d: (d not in deficit, -g.c.dishes[d].base))

    def best_gather(self, g, me) -> str:
        P = self.P
        need = self.raw_need(g, me)
        prof = g.profile(me)
        urgency = g.week / g.cfg["weeks"]
        best, best_u = None, -1.0
        for r, base in g.c.raws.items():
            deficit = max(0, need[r] - me.raws[r])
            surplus = max(0, me.raws[r] - need[r])
            u = 0.0
            for k in range(g.gather_gain(me, r)):
                if k < deficit:
                    # недостающее сырьё блокирует блюдо: дороже к концу подготовки и если его мало на рынке
                    u += base * P["need_value"] + P["unlock_value"] * urgency * (1 + g.raw_demand.get(r, 1.0))
                elif r in prof:
                    u += base * P["surplus_value"] * g.raw_demand.get(r, 1.0) * P["surplus_decay"] ** surplus
                    surplus += 1
            u += self.rng.random() * 0.01
            if u > best_u:
                best, best_u = r, u
        return best

    def choose_order(self, g, me, cards):
        prof = g.profile(me)
        remaining = g.actions_after_this_week() + g.A // 2

        def score(o):
            s = 0.0
            plan = self.plan + Counter({d: max(0, q - me.dishes[d]) for d, q in o.items.items()})
            if self.actions_needed(g, me, plan) > remaining:
                s -= o.value * g.cfg["orders"]["penalty"]
            for d, q in o.items.items():
                dish = g.c.dishes[d]
                have = max(0, me.dishes[d] - g.order_need(me)[d])
                make = max(0, q - have)
                cost = sum(k * g.c.raws[r] * (self.P["profile_cost"] if r in prof else self.P["buy_cost"])
                           for r, k in dish.ingredients.items())
                s += dish.base * q - make * (cost + g.cook_cost(me, d) * self.P["action_value"])
            return s
        i = max(range(len(cards)), key=lambda i: score(cards[i]))
        self.dirty = True
        return i

    def auto_fulfill(self, g, me):
        return True

    # ------------------------------------------------------------ рынок
    def item_value(self, g, me, item: str, have_delta: int = 0) -> float:
        """Ценность одной (следующей) единицы для бота."""
        P = self.P
        if item in g.c.raws:
            if not g.can_cook_later:
                return 0.0
            base = g.c.raws[item]
            deficit = self.raw_need(g, me)[item] - (me.raws[item] + have_delta)
            return base * (P["raw_bid"] if deficit > 0 else P["raw_ask"] * 0.9)
        base = g.c.dishes[item].base
        deficit = g.order_need(me)[item] - (me.dishes[item] + have_delta)
        if deficit > 0:
            return base * (1 + g.cfg["orders"]["penalty"])
        return 0.0 if g.phase == "after" else base * P["dish_hold"]

    def market_orders(self, g, me):
        P = self.P
        out = []
        if g.can_cook_later:
            need = self.raw_need(g, me)
            urgency = g.week / g.cfg["weeks"]
            for r, base in g.c.raws.items():
                diff = need[r] - me.raws[r]
                if diff > 0:
                    out.append(("buy", r, diff, max(1, math.floor(base * (P["raw_bid"] + P["bid_urgency"] * urgency)))))
                elif diff < 0:
                    out.append(("sell", r, -diff, max(1, math.ceil(base * P["raw_ask"]))))
        need_d = g.order_need(me)
        for d, dish in g.c.dishes.items():
            diff = need_d[d] - me.dishes[d]
            if diff > 0:
                out.append(("buy", d, diff, max(1, math.floor(dish.base * P["order_dish_bid"]))))
            elif g.phase == "after" and me.dishes[d] > need_d[d]:
                out.append(("sell", d, me.dishes[d] - need_d[d], max(1, math.floor(dish.base * P["dump_ask"]))))
        # денег на все покупки может не хватить — сначала самое нужное
        budget = me.coins
        res = []
        for o in sorted(out, key=lambda o: (o[0] != "sell", -o[3])):
            if o[0] == "buy":
                q = min(o[2], budget // o[3])
                if q <= 0:
                    continue
                budget -= q * o[3]
                o = (o[0], o[1], q, o[3])
            res.append(o)
        return res

    def evaluate_deal(self, g, me, give, get):
        """give/get со стороны бота. Принимает, если получает не меньше, чем отдаёт (+ запас deal_margin)."""
        def total(items, sign):
            v = 0.0
            for k, q in items.items():
                if k == "монеты":
                    v += q
                    continue
                for i in range(q):
                    # отдаём — теряем ценность единиц, которые остаются последними, получаем — следующие
                    v += self.item_value(g, me, k, -i - 1 if sign < 0 else i)
            return v
        return total(get, 1) - total(give, -1) >= self.P["deal_margin"]

    # ------------------------------------------------------------ продавец
    def reserved(self, g, me, dish) -> int:
        return g.order_need(me)[dish]

    def seller_prices(self, g, me, card, stop_no):
        P = self.P
        out = {}
        for i, pos in enumerate(card.positions):
            if pos.qty <= 0 or me.dishes[pos.dish] - self.reserved(g, me, pos.dish) <= 0:
                continue
            dish = g.c.dishes[pos.dish]
            m = lerp(g.cfg["buyer"]["max_range"], P["ask_q"]) * self.rng.uniform(1 - P["ask_noise"], 1 + P["ask_noise"])
            if dish.category == g.weather_today:
                m *= 1 + g.cfg["events"]["weather_bonus"]
            out[i] = max(1, round(dish.base * m))
        return out

    def floor(self, g, me, dish) -> float:
        P = self.P
        days = g.cfg["fair_days"]
        late = (g.day - 1) / max(1, days - 1)
        f = dish.base * lerp(g.cfg["buyer"]["max_range"], P["floor_q"]) * (1 - P["late_discount"] * late)
        if dish.category == g.weather_today:
            f *= 1 + g.cfg["events"]["weather_bonus"]
        return f

    def seller_accept_counter(self, g, me, card, dish, price):
        d = g.c.dishes[dish]
        if dish not in {p.dish for p in card.positions}:   # встречная на втюхивание
            return price >= d.base * lerp(g.cfg["buyer"]["weakness_range"], self.P["push_floor_q"])
        return price >= self.floor(g, me, d)

    def seller_push(self, g, me, card):
        P = self.P
        if self.rng.random() >= P["push_prob"]:
            return None
        listed = {p.dish for p in card.positions}
        cands = [d for d, q in me.dishes.items()
                 if q - self.reserved(g, me, d) > 0 and d not in listed]
        if not cands:
            return None
        # слабость не видна; погодная категория дня выгоднее
        weights = [3.0 if g.c.dishes[d].category == g.weather_today else 1.0 for d in cands]
        d = self.rng.choices(cands, weights)[0]
        dish = g.c.dishes[d]
        m = lerp(g.cfg["buyer"]["weakness_range"], P["push_q"])
        if dish.category == g.weather_today:
            m *= 1 + g.cfg["events"]["weather_bonus"]
        return d, max(1, round(dish.base * m))

    # ------------------------------------------------------------ покупатель
    def buyer_respond(self, g, me, card, seller, offers, stop_no):
        P = self.P
        last = stop_no >= g.cfg["stops_per_buyer"] - 1
        accepted, refused = set(), []
        for i, price in offers.items():
            pos = card.positions[i]
            if price <= pos.max * (1.0 if last else P["buyer_accept"]):
                accepted.add(i)
            else:
                refused.append(i)
        counter = None
        if refused:
            i = max(refused, key=lambda i: card.positions[i].max * card.positions[i].qty)
            pos = card.positions[i]
            cp = math.floor(pos.max * (P["buyer_counter_last"] if last else P["buyer_counter"]))
            if 0 < cp < offers[i]:
                counter = (i, cp)
        return accepted, counter

    def buyer_push_counter(self, g, me, card, seller, dish, price, can_counter):
        if not can_counter:
            return None
        return math.floor(card.weak_max(g.c.dishes[dish]) * self.P["buyer_counter"])

    # ------------------------------------------------------------ события
    def tender_bid(self, g, me, dish, price, max_bid, first):
        floor = g.c.dishes[dish].base * self.P["tender_floor"]
        return max_bid if max_bid >= floor else None

    def banquet_set(self, g, me):
        avail = [d for d, q in me.dishes.items() if q - self.reserved(g, me, d) > 0]
        avail.sort(key=lambda d: -g.c.dishes[d].base)
        return avail[:g.cfg["banquet"]["max_dishes"]]
