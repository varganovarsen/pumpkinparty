"""Осенняя ярмарка — консольный прототип.

    python -m fair play  [--role Повар] [--seed 7] [--verbose]   играть самому против ботов
    python -m fair watch [--seed 7] [--brief]                     смотреть партию ботов
    python -m fair sim   [-n 300] [--sweep buyers_per_player=0.7,1.0] [--csv out.csv]
    python -m fair edit  [--port 8765]                            редактор конфига в браузере

Общие: --config путь, --set ключ=значение (сколько угодно), --players N, --mix balanced,late,...
"""
from __future__ import annotations

import argparse
import random
import sys

from . import config
from .engine import Log
from .runner import make_game, run_many, sweep
from .stats import Summary, write_csv


def main(argv=None):
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:
            pass
    ap = argparse.ArgumentParser(prog="python -m fair", description="Осенняя ярмарка — консольный прототип")
    ap.add_argument("mode", choices=["play", "watch", "sim", "edit"])
    ap.add_argument("--config")
    ap.add_argument("--set", action="append", default=[], metavar="КЛЮЧ=ЗНАЧЕНИЕ")
    ap.add_argument("--players", type=int)
    ap.add_argument("--mix", help="архетипы ботов через запятую")
    ap.add_argument("--seed", type=int)
    ap.add_argument("--role", help="play: своя роль")
    ap.add_argument("--verbose", action="store_true", help="play: показывать сделки ботов между собой")
    ap.add_argument("--brief", action="store_true", help="watch: только события, без сделок ботов")
    ap.add_argument("-n", type=int, default=200, help="sim: партий на каждое сочетание")
    ap.add_argument("--sweep", action="append", default=[], metavar="КЛЮЧ=v1,v2")
    ap.add_argument("--csv", help="sim: дописать построчно игроков всех партий в CSV")
    ap.add_argument("--report", action="store_true", help="sim со --sweep: полная сводка по каждому сочетанию")
    ap.add_argument("--port", type=int, default=8765, help="edit: порт")
    ap.add_argument("--no-browser", action="store_true", help="edit: не открывать браузер")
    a = ap.parse_args(argv)

    if a.mode == "edit":
        from .editor import serve
        serve(a.config, a.port, not a.no_browser)
        return

    overrides = list(a.set)
    if a.players:
        overrides.append(f"players={a.players}")
    if a.mix:
        overrides.append(f"bots.mix=[{a.mix}]")
    cfg = config.load(a.config, overrides)
    seed = a.seed if a.seed is not None else random.randrange(1_000_000)

    if a.mode == "play":
        from .human import Human
        g = make_game(cfg, seed, Log(info=True, detail=a.verbose), human=Human(), human_role=a.role)
        print(f"Партия #{seed} (повторить: --seed {seed})")
        g.run()
    elif a.mode == "watch":
        g = make_game(cfg, seed, Log(info=True, detail=not a.brief))
        print(f"Партия #{seed} (повторить: --seed {seed})")
        for p in g.players:
            print(f"  {p.label:<24} [{p.agent.arch}]")
        g.run()
    else:
        if not a.sweep:
            games = run_many(cfg, a.n, seed)
            if a.csv:
                write_csv(a.csv, games)
            print(Summary(games, cfg).report())
            return
        sweeps = {}
        for s in a.sweep:
            k, _, v = s.partition("=")
            sweeps[k.strip()] = config.split_values(v)
        results = sweep(cfg, sweeps, a.n, seed)
        table = []
        for combo, summ, games in results:
            if a.csv:
                write_csv(a.csv, games, {k: str(v) for k, v in combo.items()})
            row = {k: str(v) for k, v in combo.items()} | summ.sweep_row()
            table.append(row)
            if a.report:
                print(f"\n════ {combo} ════")
                print(summ.report())
        print_table(table)


def print_table(rows: list[dict]):
    cols = list(rows[0])
    w = {c: max(len(c), *(len(r[c]) for r in rows)) for c in cols}
    print()
    print("  ".join(c.ljust(w[c]) for c in cols))
    print("  ".join("-" * w[c] for c in cols))
    for r in rows:
        print("  ".join(r[c].ljust(w[c]) for c in cols))


if __name__ == "__main__":
    main()
