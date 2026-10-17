"""Метрики партии, сводка по многим партиям и флаги «экономика рушится»."""
from __future__ import annotations

import csv
import os
import statistics as st
from collections import Counter, defaultdict

SOURCES = ["fair", "push", "buyer", "orders", "tender", "banquet", "market_in", "market_out", "penalty"]
SOURCE_NAMES = {
    "fair": "продажи по списку", "push": "втюхивание", "buyer": "роль покупателя", "orders": "заказы",
    "tender": "тендер", "banquet": "банкет", "market": "рынок (сальдо)", "penalty": "штрафы",
}


class GameStats:
    def __init__(self, g):
        self.g = g
        n = len(g.players)
        self.income = {i: Counter() for i in range(n)}
        self.produced, self.consumed = Counter(), Counter()
        self.cooked, self.cooked_dish = Counter(), Counter()
        self.orders_taken, self.orders_done, self.orders_failed = Counter(), Counter(), Counter()
        self.orders_value = 0
        self.dishes_before_fair: dict[int, int] = {}
        self.raws_left_prep = 0
        self.stock_by_day: list[int] = []
        self.sold_by_day = [0] * g.cfg["fair_days"]
        self.demand_units = self.sold_units = 0
        self.sold_price_ratio: list[float] = []
        self.push_tries = self.push_ok = 0
        self.counters = self.counters_ok = 0
        self.stops = 0
        self.tenders = self.tender_parts = self.tender_empty = 0
        self.tender_ratio: list[float] = []
        self.banquets = 0
        self.banquet_size: list[int] = []
        self.trades = self.trade_volume = 0
        self.trade_prices = defaultdict(list)
        self.dishes_left = 0
        self.players: list[dict] = []

    def add(self, p, source: str, amount: int):
        self.income[p.idx][source] += amount

    def finish(self):
        g = self.g
        top = max(p.coins for p in g.players)
        winners = [p for p in g.players if p.coins == top]
        for p in g.players:
            self.players.append({
                "idx": p.idx, "name": p.name, "role": p.role, "arch": p.agent.arch, "coins": p.coins,
                "win": (1 / len(winners)) if p in winners else 0.0,
                "dishes_before_fair": self.dishes_before_fair.get(p.idx, 0),
                **{s: self.income[p.idx][s] for s in SOURCES},
                "orders_taken": self.orders_taken[p.idx], "orders_failed": self.orders_failed[p.idx],
            })


def _mean(xs, default=0.0):
    xs = list(xs)
    return st.fmean(xs) if xs else default


class Summary:
    def __init__(self, games: list[GameStats], cfg: dict):
        self.games, self.cfg = games, cfg
        self.rows = [r for g in games for r in g.players]
        n = len(games)
        rows = self.rows
        self.n_games = n
        self.mean_coins = _mean(r["coins"] for r in rows)
        self.by_role = self._group("role")
        self.by_arch = self._group("arch")
        inc = Counter()
        for r in rows:
            for s in SOURCES:
                inc[s] += r[s]
        inc["market"] = inc["market_in"] - inc["market_out"]
        self.income_total = inc
        gross = sum(inc[s] for s in ["fair", "push", "buyer", "orders", "tender", "banquet"]) or 1
        self.income_share = {s: inc[s] / gross for s in ["fair", "push", "buyer", "orders", "tender", "banquet"]}
        self.penalty_share = inc["penalty"] / gross
        self.dishes_before = _mean(r["dishes_before_fair"] for r in rows)
        lo, hi = cfg["flags"]["dishes_before_fair"]
        self.dishes_in_range = _mean(lo <= r["dishes_before_fair"] <= hi for r in rows)
        dem = sum(g.demand_units for g in games) or 1
        self.sellthrough = sum(g.sold_units for g in games) / dem
        days = cfg["fair_days"]
        self.stock_by_day = [_mean(g.stock_by_day[d] for g in games if len(g.stock_by_day) > d) for d in range(days)]
        self.sold_by_day = [_mean(g.sold_by_day[d] for g in games) for d in range(days)]
        self.price_ratio = _mean(x for g in games for x in g.sold_price_ratio)
        pt = sum(g.push_tries for g in games)
        self.push_rate = sum(g.push_ok for g in games) / pt if pt else 0.0
        self.push_tries = pt / n if n else 0
        seller = inc["fair"] + inc["push"] or 1
        self.push_share = inc["push"] / seller
        ct = sum(g.counters for g in games)
        self.counter_rate = sum(g.counters_ok for g in games) / ct if ct else 0.0
        taken = sum(r["orders_taken"] for r in rows)
        self.orders_per_player = taken / len(rows) if rows else 0
        self.order_fail_rate = sum(r["orders_failed"] for r in rows) / taken if taken else 0.0
        tn = sum(g.tenders for g in games)
        self.tender_empty_rate = sum(g.tender_empty for g in games) / tn if tn else 0.0
        self.tender_parts = sum(g.tender_parts for g in games) / tn if tn else 0.0
        self.tender_ratio = _mean(x for g in games for x in g.tender_ratio)
        self.banquet_size = _mean(x for g in games for x in g.banquet_size)
        self.negative_rate = _mean(r["coins"] < 0 for r in rows)
        self.trades = _mean(g.trades for g in games)
        self.dishes_left = _mean(g.dishes_left for g in games)
        self.raws_left = _mean(g.raws_left_prep for g in games)
        prod, cons = Counter(), Counter()
        for g in games:
            prod.update(g.produced)
            cons.update(g.consumed)
        self.raw_use = {r: (prod[r] / n, cons[r] / n) for r in sorted(set(prod) | set(cons))}
        cooked = Counter()
        for g in games:
            cooked.update(g.cooked_dish)
        self.cooked_dish = {d: cooked[d] / n for d in cooked}
        spreads = []
        for g in games:
            cs = [r["coins"] for r in g.players]
            spreads.append(max(cs) - min(cs))
        self.spread = _mean(spreads)
        self.winner_coins = _mean(max(r["coins"] for r in g.players) for g in games)
        self.flags = self._flags()

    def _group(self, key):
        groups = defaultdict(list)
        for r in self.rows:
            groups[r[key]].append(r)
        out = {}
        total_players = len(self.rows) / max(1, self.n_games)
        for k, rs in groups.items():
            share_players = len(rs) / max(1, len(self.rows))
            win = sum(r["win"] for r in rs) / max(1, self.n_games)
            out[k] = {
                "n": len(rs) / max(1, self.n_games),
                "coins": _mean(r["coins"] for r in rs),
                "win": win,
                "fair_win": share_players,       # доля побед при равных шансах
                "dishes": _mean(r["dishes_before_fair"] for r in rs),
                **{s: _mean(r[s] for r in rs) for s in SOURCES},
            }
        return dict(sorted(out.items(), key=lambda kv: -kv[1]["coins"]))

    def _flags(self) -> list[str]:
        f = self.cfg["flags"]
        out = []
        for title, groups in (("Архетип", self.by_arch), ("Роль", self.by_role)):
            for k, v in groups.items():
                if v["fair_win"] and v["win"] > v["fair_win"] * f["dominant_win_ratio"]:
                    out.append(f"{title} «{k}» доминирует: побед {v['win']:.0%} при честных {v['fair_win']:.0%}")
                if v["coins"] < self.mean_coins * f["weak_coins_ratio"]:
                    out.append(f"{title} «{k}» слабый: {v['coins']:.0f} мон. при среднем {self.mean_coins:.0f}")
                if v["coins"] > self.mean_coins * f["strong_coins_ratio"]:
                    out.append(f"{title} «{k}» сильный: {v['coins']:.0f} мон. при среднем {self.mean_coins:.0f}")
        lo, hi = f["dishes_before_fair"]
        if not lo <= self.dishes_before <= hi:
            out.append(f"Блюд к ярмарке {self.dishes_before:.1f} на игрока (цель {lo}-{hi})")
        if self.sellthrough > f["sellthrough_high"]:
            out.append(f"Спрос закрыт на {self.sellthrough:.0%} — товара мало")
        if self.sellthrough < f["sellthrough_low"]:
            out.append(f"Спрос закрыт только на {self.sellthrough:.0%} — у продавцов не те блюда")
        if self.stock_by_day and self.stock_by_day[0] and \
                self.stock_by_day[-1] / self.stock_by_day[0] < f["stock_empty_day5"]:
            out.append(f"К последнему дню склады почти пусты: {self.stock_by_day[-1]:.1f} "
                       f"из {self.stock_by_day[0]:.1f} блюд")
        if self.stock_by_day and self.stock_by_day[0] and self.dishes_left / self.stock_by_day[0] > f["unsold_high"]:
            out.append(f"Не продано {self.dishes_left / self.stock_by_day[0]:.0%} блюд — пропадают в конце")
        if self.income_share["orders"] > f["orders_income_share"]:
            out.append(f"Заказы дают {self.income_share['orders']:.0%} дохода — похоже на безопасный выигрыш")
        if self.income_share["buyer"] > f["buyer_bonus_share"]:
            out.append(f"Роль покупателя даёт {self.income_share['buyer']:.0%} дохода")
        if self.push_share > f["push_share"]:
            out.append(f"Втюхивание даёт {self.push_share:.0%} выручки продавцов")
        if self.tender_empty_rate > f["tender_empty_rate"]:
            out.append(f"Тендер без участников в {self.tender_empty_rate:.0%} случаев")
        if self.order_fail_rate > f["order_fail_rate"]:
            out.append(f"Не выполнено {self.order_fail_rate:.0%} заказов")
        if self.negative_rate > f["negative_rate"]:
            out.append(f"В минусе заканчивают {self.negative_rate:.0%} игроков")
        return out

    # --- вывод
    def report(self) -> str:
        L = []
        L.append(f"Партий: {self.n_games}. Средние монеты {self.mean_coins:.1f}, у победителя "
                 f"{self.winner_coins:.1f}, разброс в партии {self.spread:.1f}")
        for title, groups in (("Роли", self.by_role), ("Архетипы ботов", self.by_arch)):
            L.append(f"\n{title}:")
            L.append(f"  {'':<14}{'кол':>5}{'монеты':>8}{'победы':>8}{'честно':>8}{'блюд':>6}"
                     f"{'список':>8}{'втюх':>6}{'покуп':>7}{'заказ':>7}{'тенд':>6}{'банк':>6}{'рынок':>7}{'штраф':>7}")
            for k, v in groups.items():
                L.append(f"  {k:<14}{v['n']:>5.1f}{v['coins']:>8.1f}{v['win']:>8.0%}{v['fair_win']:>8.0%}"
                         f"{v['dishes']:>6.1f}{v['fair']:>8.1f}{v['push']:>6.1f}{v['buyer']:>7.1f}"
                         f"{v['orders']:>7.1f}{v['tender']:>6.1f}{v['banquet']:>6.1f}"
                         f"{v['market_in'] - v['market_out']:>7.1f}{-v['penalty']:>7.1f}")
        L.append("\nИсточники дохода (доля от валового): " + ", ".join(
            f"{SOURCE_NAMES[s]} {v:.0%}" for s, v in self.income_share.items()) + f"; штрафы −{self.penalty_share:.0%}")
        L.append(f"\nПодготовка: блюд к ярмарке {self.dishes_before:.1f} на игрока "
                 f"(в цели {self.cfg['flags']['dishes_before_fair']} — {self.dishes_in_range:.0%} игроков), "
                 f"сырья не пущено в дело {self.raws_left:.0f} ед., сделок на рынках {self.trades:.0f} за партию")
        L.append("  Сырьё (собрано → потрачено за партию):")
        L.append("    " + "; ".join(f"{r} {p:.0f}→{c:.0f}" for r, (p, c) in self.raw_use.items()))
        L.append("  Приготовлено блюд за партию:")
        L.append("    " + "; ".join(f"{d} {q:.1f}" for d, q in sorted(self.cooked_dish.items(), key=lambda x: -x[1])))
        L.append(f"\nЯрмарка: спрос закрыт на {self.sellthrough:.0%}, цена сделки {self.price_ratio:.2f}× базы, "
                 f"встречные приняты {self.counter_rate:.0%}")
        L.append("  Блюд на складах в начале дня: " + " → ".join(f"{x:.1f}" for x in self.stock_by_day)
                 + f" → в конце {self.dishes_left:.1f}")
        L.append("  Продано порций по дням: " + ", ".join(f"{x:.1f}" for x in self.sold_by_day))
        L.append(f"  Втюхивание: попыток {self.push_tries:.1f} за партию, успешных {self.push_rate:.0%}, "
                 f"{self.push_share:.0%} выручки продавцов")
        L.append(f"  Заказы: {self.orders_per_player:.2f} на игрока, не выполнено {self.order_fail_rate:.0%}")
        L.append(f"  Тендер: участников {self.tender_parts:.1f}, пустых {self.tender_empty_rate:.0%}, "
                 f"итоговая цена {self.tender_ratio:.2f}× базы")
        L.append(f"  Банкет: в наборе победителя {self.banquet_size:.1f} блюд")
        L.append(f"  В минусе: {self.negative_rate:.0%} игроков")
        L.append("\nФлаги:" if self.flags else "\nФлагов нет.")
        L.extend(f"  ⚠ {x}" for x in self.flags)
        return "\n".join(L)

    def sweep_row(self) -> dict:
        best_arch = max(self.by_arch.items(), key=lambda kv: kv[1]["win"] - kv[1]["fair_win"])
        worst_role = min(self.by_role.items(), key=lambda kv: kv[1]["coins"])
        return {
            "монеты": f"{self.mean_coins:.1f}",
            "блюд": f"{self.dishes_before:.1f}",
            "спрос%": f"{self.sellthrough:.0%}",
            "цена×": f"{self.price_ratio:.2f}",
            "склад д5": f"{self.stock_by_day[-1]:.0f}" if self.stock_by_day else "-",
            "заказы%": f"{self.income_share['orders']:.0%}",
            "покуп%": f"{self.income_share['buyer']:.0%}",
            "втюх%": f"{self.push_share:.0%}",
            "лучший арх": f"{best_arch[0]} {best_arch[1]['win']:.0%}",
            "слабая роль": f"{worst_role[0]} {worst_role[1]['coins']:.0f}",
            "флагов": str(len(self.flags)),
        }


def write_csv(path: str, games: list[GameStats], extra: dict | None = None):
    rows = []
    for gi, g in enumerate(games):
        for r in g.players:
            rows.append({"game": gi, **(extra or {}), **r})
    if not rows:
        return
    new = not os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        if new:
            w.writeheader()
        w.writerows(rows)
