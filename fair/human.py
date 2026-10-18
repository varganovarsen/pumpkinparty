"""Человек за консолью. Реализует тот же интерфейс, что и боты; правила проверяет движок."""
from __future__ import annotations

from .engine import Agent, MarketOrder


def ask(prompt: str) -> str:
    try:
        return input(prompt).strip()
    except EOFError:
        raise SystemExit("\nВвод закрыт — выходим.")


def ask_int(prompt: str, lo: int | None = None, hi: int | None = None, allow_empty=True) -> int | None:
    while True:
        s = ask(prompt)
        if not s and allow_empty:
            return None
        try:
            v = int(s)
        except ValueError:
            print("  нужно число")
            continue
        if (lo is not None and v < lo) or (hi is not None and v > hi):
            print(f"  от {lo} до {hi}")
            continue
        return v


def yes(prompt: str) -> bool:
    return ask(prompt + " (д/н) ").lower() in ("д", "y", "да", "yes", "l")


def choose(options: list[str], prompt="Выбор (Enter — назад): ") -> int | None:
    for i, o in enumerate(options, 1):
        print(f"  {i:>2}) {o}")
    v = ask_int(prompt, 1, len(options))
    return None if v is None else v - 1


def fmt(counter) -> str:
    items = [f"{k} {v}" for k, v in sorted(counter.items()) if v > 0]
    return ", ".join(items) or "—"


class Human(Agent):
    human = True
    arch = "человек"

    # ------------------------------------------------------------ показ
    def show_me(self, g, me):
        print(f"  Монеты: {me.coins}")
        print(f"  Сырьё: {fmt(me.raws)}")
        print(f"  Блюда: {fmt(me.dishes)}")
        for o in me.open_orders:
            print(f"  Заказ: {o.text()}{'  ← можно выполнить' if g.can_fulfill(me, o) else ''}")

    def show_economy(self, g, me):
        print(f"\n  {'игрок':<24}{'бот':<10}{'монеты':>7}{'сырьё':>7}{'блюда':>7}{'заказы':>8}")
        for p in g.players:
            print(f"  {p.label:<24}{p.agent.arch:<10}{p.coins:>7}{sum(p.raws.values()):>7}"
                  f"{sum(p.dishes.values()):>7}{len(p.open_orders):>8}")
        if g.rumors:
            print("  Слухи: " + "; ".join(f"{g.event_name(e)} — {e.window}" for e in g.rumors))
        if g.market and g.market.history:
            print("  Цены этого рынка: " + ", ".join(f"{i} {p:.1f}" for i, p in g.market.avg_prices().items()))
        tp = {i: sum(v) / len(v) for i, v in g.stats.trade_prices.items() if v}
        if tp:
            print("  Средние цены за партию: " + ", ".join(f"{i} {p:.1f}" for i, p in sorted(tp.items())))
        s = g.stats
        if g.phase != "prep":
            print(f"  Ярмарка: продано {s.sold_units} порций из {s.demand_units} в списках, "
                  f"втюхиваний {s.push_ok}/{s.push_tries}, остаток на складах "
                  f"{sum(sum(p.dishes.values()) for p in g.players)}")
        print(f"  Колода заказов: {len(g.order_deck)} карт")

    def show_recipes(self, g, me):
        for d in g.c.dishes.values():
            mark = "✓" if g.can_cook(me, d.name) else " "
            ingr = ", ".join(f"{r} {q}" for r, q in d.ingredients.items())
            print(f"  {mark} {d.name:<24} {d.category:<9} база {d.base:>2}, действий {g.cook_cost(me, d.name)}  [{ingr}]")

    def fulfill_menu(self, g, me):
        ready = [o for o in me.open_orders if g.can_fulfill(me, o)]
        if not ready:
            print("  Нечего выполнить.")
            return
        i = choose([o.text() for o in ready])
        if i is not None:
            g.fulfill(me, ready[i])

    # ------------------------------------------------------------ подготовка
    def on_week_start(self, g, me):
        if g.week == 1:
            cheap = [d.name for d in g.c.dishes.values() if d.cheap == me.role]
            print(f"\nВы — {me.role}. Профильное сырьё: {', '.join(g.profile(me))} "
                  f"(+{g.rule(me, 'gather_profile')} за действие, остальное +{g.rule(me, 'gather_other')}).")
            if cheap:
                print(f"Готовите за {g.cfg['cook_actions_cheap']} действие: {', '.join(cheap)}.")
            if g.rule(me, "cook_actions") != g.cfg["cook_actions"]:
                print(f"Любое блюдо готовите за {g.rule(me, 'cook_actions')} действий.")
            if g.cfg["market"].get("during_work"):
                print("Рынок открыт всю подготовку: после каждого действия — раунд торга.")
            print("Соперники: " + ", ".join(f"{p.label}" for p in g.players if p is not me))

    def next_action(self, g, me, left):
        while True:
            print(f"\n[Неделя {g.week}/{g.cfg['weeks']} · работа · действий {left}]")
            self.show_me(g, me)
            i = choose(["Собрать", "Приготовить", "Взять заказ", "Выполнить заказ", "Экономика", "Рецепты",
                        "Закончить неделю (остаток сгорит)"], "Действие: ")
            if i == 0:
                opts = list(g.c.raws)
                j = choose([f"{r} +{g.gather_gain(me, r)} (база {g.c.raws[r]})" for r in opts])
                if j is not None:
                    return ("gather", opts[j])
            elif i == 1:
                opts = list(g.c.dishes)
                self.show_recipes(g, me)
                j = ask_int("Номер блюда (Enter — назад): ", 1, len(opts))
                if j is None:
                    continue
                d = opts[j - 1]
                if not g.can_cook(me, d):
                    print("  Не хватает сырья.")
                elif g.cook_cost(me, d) > left:
                    print("  Не хватает действий.")
                else:
                    return ("cook", d)
            elif i == 2:
                if not g.order_deck:
                    print("  Колода заказов пуста.")
                else:
                    return ("order",)
            elif i == 3:
                self.fulfill_menu(g, me)
            elif i == 4:
                self.show_economy(g, me)
            elif i == 5:
                self.show_recipes(g, me)
            elif i == 6:
                if left == 0 or yes(f"Сжечь {left} действий?"):
                    return None

    def choose_order(self, g, me, cards):
        print("\nКарточки заказов (штраф за невыполнение "
              f"{round(g.cfg['orders']['penalty'] * 100)}% стоимости):")
        while True:
            i = choose([c.text() for c in cards], "Берёте: ")
            if i is not None:
                return i

    # ------------------------------------------------------------ рынок
    def parse_items(self, g, s: str) -> dict | None:
        """'мёд 2, монеты 5, грибной суп' -> {'мёд': 2, 'монеты': 5, 'Грибной суп': 1}"""
        names = list(g.c.raws) + list(g.c.dishes) + ["монеты"]
        out = {}
        for part in filter(None, (x.strip() for x in s.split(","))):
            words = part.split()
            qty = 1
            if len(words) > 1 and words[-1].isdigit():
                qty = int(words[-1])
                words = words[:-1]
            key = " ".join(words).lower()
            match = [n for n in names if n.lower() == key] or [n for n in names if n.lower().startswith(key)]
            if len(match) != 1:
                print(f"  не понял «{part}»" + (f": {', '.join(match)}?" if match else ""))
                return None
            out[match[0]] = out.get(match[0], 0) + qty
        return out

    def market_turn(self, g, me, market):
        while True:
            print(f"\n[{'Подготовка, неделя ' + str(g.week) if g.phase == 'prep' else 'Ярмарка' if g.phase == 'fair' else 'После ярмарки'} · рынок]"
                  + ("" if g.can_cook_later or g.phase != "prep" else "  (готовить больше нельзя — сырьё обесценится)"))
            self.show_me(g, me)
            i = choose(["Стакан заявок", "Купить/продать по заявке", "Предложить сделку боту", "Выставить заявку",
                        "Снять мои заявки", "Выполнить заказ", "Экономика",
                        "Подождать раунд (боты переставят заявки)", "Готов (закончить рынок)"], "Действие: ")
            if i == 0:
                self.show_book(g, me, market)
            elif i == 1:
                others = [o for o in market.orders if o.player is not me]
                if not others:
                    print("  Чужих заявок нет.")
                    continue
                j = choose([self.order_text(o) for o in others])
                if j is None:
                    continue
                o = others[j]
                q = ask_int(f"Сколько (до {o.qty}): ", 1, o.qty) or 0
                if q and not market.hit(me, o, q):
                    print("  Не вышло: не хватает денег или товара.")
            elif i == 2:
                self.propose(g, me)
            elif i == 3:
                side = choose(["Куплю", "Продам"])
                if side is None:
                    continue
                items = self.parse_items(g, ask("Товар и количество (напр. «мёд 3»): "))
                if not items or len(items) != 1 or "монеты" in items:
                    continue
                (item, qty), = items.items()
                price = ask_int("Цена за штуку: ", 1)
                if price:
                    market.orders.append(MarketOrder(me, "buy" if side == 0 else "sell", item, qty, price))
                    market.match()
            elif i == 4:
                market.orders = [o for o in market.orders if o.player is not me]
            elif i == 5:
                self.fulfill_menu(g, me)
            elif i == 6:
                self.show_economy(g, me)
            elif i == 7:
                return False
            elif i == 8:
                return True

    def order_text(self, o) -> str:
        return f"{o.player.name} {'покупает' if o.side == 'buy' else 'продаёт'} {o.item} ×{o.qty} по {o.price}"

    def show_book(self, g, me, market):
        if not market.orders:
            print("  Заявок нет.")
        for o in sorted(market.orders, key=lambda o: (o.item, o.side, o.price)):
            print(("  * " if o.player is me else "    ") + self.order_text(o))

    def propose(self, g, me):
        bots = [p for p in g.players if p is not me]
        j = choose([f"{p.label} — монеты {p.coins}" for p in bots], "Кому (Enter — назад): ")
        if j is None:
            return
        bot = bots[j]
        print(f"  У {bot.name}: сырьё {fmt(bot.raws)}; блюда {fmt(bot.dishes)}")
        give = self.parse_items(g, ask("Вы отдаёте (напр. «грибы 3, монеты 2»): "))
        get = self.parse_items(g, ask("Вы получаете: "))
        if give is None or get is None or not (give or get):
            return
        if not bot.agent.evaluate_deal(g, bot, give=get, get=give):
            print(f"  {bot.name}: «Нет, мне невыгодно».")
        elif not g.barter(me, bot, give, get):
            print("  Сделка не прошла: у кого-то не хватает товара или денег.")
        else:
            print(f"  {bot.name}: «По рукам!»")

    # ------------------------------------------------------------ продавец
    def seller_prices(self, g, me, card, stop_no):
        print(f"\n— Покупатель (играет {card.player.name}) у вашего стенда, "
              f"остановка {stop_no + 1}/{g.cfg['stops_per_buyer']}"
              + (f". Сегодня дороже: {g.weather_today}" if g.weather_today else ""))
        print(f"  Ваши блюда: {fmt(me.dishes)}")
        prices = {}
        for i, pos in enumerate(card.positions):
            if pos.qty <= 0:
                continue
            have = me.dishes[pos.dish]
            dish = g.c.dishes[pos.dish]
            line = f"  {pos.dish} ×{pos.qty} ({dish.category}, база {dish.base}, у вас {have})"
            if not have:
                print(line + " — нет")
                continue
            p = ask_int(line + " — цена (Enter — не продавать): ", 1)
            if p:
                prices[i] = p
        return prices

    def seller_accept_counter(self, g, me, card, dish, price):
        return yes(f"  {card.player.name} предлагает {price} за {dish} (база {g.c.dishes[dish].base}). Принять?")

    def seller_push(self, g, me, card):
        listed = {p.dish for p in card.positions}
        cands = [d for d, q in me.dishes.items() if q > 0 and d not in listed]
        if not cands:
            return None
        print("  Можно втюхать одно блюдо не из списка (слабость покупателя тайная):")
        j = choose([f"{d} ({g.c.dishes[d].category}, база {g.c.dishes[d].base})" for d in cands],
                   "Что (Enter — не втюхивать): ")
        if j is None:
            return None
        p = ask_int("  Цена: ", 1)
        return (cands[j], p) if p else None

    # ------------------------------------------------------------ покупатель
    def show_card(self, g, card):
        print(f"  Карточка: слабость — {card.weakness} (до ×{card.weak_mult:.2f} базы"
              + (f", сегодня {card.boost} ещё +{round((card.boost_mult - 1) * 100)}%" if card.boost else "") + ")")
        for i, pos in enumerate(card.positions):
            if pos.qty > 0:
                print(f"    {pos.dish} ×{pos.qty}: максимум {pos.max} (база {g.c.dishes[pos.dish].base})")

    def buyer_respond(self, g, me, card, seller, offers, stop_no):
        print(f"\n— Вы покупатель у стенда {seller.label}, остановка {stop_no + 1}/{g.cfg['stops_per_buyer']}")
        self.show_card(g, card)
        accepted, refused = set(), []
        for i, price in offers.items():
            pos = card.positions[i]
            if price > pos.max:
                print(f"  {pos.dish}: {price} — выше вашего максимума {pos.max}, отказ")
                refused.append(i)
            elif yes(f"  {pos.dish}: {price} (вам останется {pos.max - price} с порции). Купить?"):
                accepted.add(i)
            else:
                refused.append(i)
        counter = None
        if refused:
            opts = [f"{card.positions[i].dish} (предложено {offers[i]}, ваш макс {card.positions[i].max})" for i in refused]
            print("  Встречная цена (одна за остановку):")
            j = choose(opts, "По какой позиции (Enter — не надо): ")
            if j is not None:
                i = refused[j]
                p = ask_int("  Ваша цена: ", 1, card.positions[i].max)
                if p:
                    counter = (i, p)
        return accepted, counter

    def buyer_push_counter(self, g, me, card, seller, dish, price, can_counter):
        wmax = card.weak_max(g.c.dishes[dish])
        print(f"  {seller.name} втюхивает {dish} за {price} — это ваша слабость, но выше максимума {wmax}.")
        if not can_counter:
            print("  Встречную вы уже называли.")
            return None
        return ask_int(f"  Встречная цена (до {wmax}, Enter — отказ): ", 1, wmax)

    # ------------------------------------------------------------ события
    def tender_bid(self, g, me, dish, price, max_bid, first):
        return ask_int(f"  Тендер «{dish}»: текущая {price}. Ваша ставка за штуку "
                       f"(≤ {max_bid}, Enter — пас): ", 1, max_bid)

    def banquet_set(self, g, me):
        avail = [d for d, q in me.dishes.items() if q > 0]
        if not avail:
            return []
        mx = g.cfg["banquet"]["max_dishes"]
        print(f"\nБанкет: соберите набор разных блюд (до {mx}). Победитель продаёт его по базе "
              f"+{round(g.cfg['banquet']['bonus'] * 100)}%, остальным блюда возвращаются.")
        for i, d in enumerate(avail, 1):
            print(f"  {i:>2}) {d} (база {g.c.dishes[d].base})")
        s = ask("Номера через запятую, Enter — все самые дорогие, 0 — не участвовать: ")
        if s == "0":
            return []
        if not s:
            return sorted(avail, key=lambda d: -g.c.dishes[d].base)[:mx]
        try:
            return [avail[int(x) - 1] for x in s.split(",") if x.strip()][:mx]
        except (ValueError, IndexError):
            print("  Не понял — подаю самые дорогие.")
            return sorted(avail, key=lambda d: -g.c.dishes[d].base)[:mx]

    def on_game_end(self, g, me):
        print(f"\nВаш счёт: {me.coins} монет.")
