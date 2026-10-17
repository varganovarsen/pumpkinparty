"""Сборка партии: боты по архетипам, место для человека, прогон многих партий."""
from __future__ import annotations

import copy
import itertools
import random

from . import config
from .bots import Bot, archetype_params
from .engine import Game, Log
from .stats import GameStats, Summary


def make_game(cfg: dict, seed: int, log: Log | None = None, human=None, human_role: str | None = None,
              human_name: str = "Вы") -> Game:
    rng = random.Random(seed)
    n = cfg["players"]
    mix = cfg["bots"]["mix"]
    agents, names = [], []
    bot_no = 0
    for i in range(n):
        if human is not None and i == 0:
            agents.append(human)
            names.append(human_name)
            continue
        arch = mix[bot_no % len(mix)]
        agents.append(Bot(arch, archetype_params(cfg, arch), random.Random(rng.random())))
        bot_no += 1
        names.append(f"Бот{bot_no}")
    g = Game(cfg, agents, rng, log, names)
    if human is not None and human_role:
        if human_role not in g.c.roles:
            raise KeyError(f"нет роли {human_role}; есть: {', '.join(g.c.roles)}")
        me = g.players[0]
        other = next((p for p in g.players if p.role == human_role), None)
        if other is not None:
            other.role, me.role = me.role, human_role
        else:
            me.role = human_role
        g.demand_weights = g._demand_weights()
    return g


def run_many(cfg: dict, n: int, seed: int = 1) -> list[GameStats]:
    return [make_game(cfg, seed * 100003 + i).run() for i in range(n)]


def sweep(cfg: dict, sweeps: dict[str, list], n: int, seed: int = 1):
    """Перебор всех сочетаний значений. Возвращает [(сочетание, Summary, games)]."""
    keys = list(sweeps)
    out = []
    for combo in itertools.product(*(sweeps[k] for k in keys)):
        c = copy.deepcopy(cfg)
        for k, v in zip(keys, combo):
            config.set_path(c, k, v)
        games = run_many(c, n, seed)
        out.append((dict(zip(keys, combo)), Summary(games, c), games))
    return out
