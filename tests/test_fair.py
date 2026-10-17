"""Осенняя ярмарка: прогоны ботов, сходимость денег, консольный игрок со скриптовым вводом."""
from __future__ import annotations

import pytest

from fair import config, human
from fair.engine import Game
from fair.runner import make_game, run_many, sweep
from fair.stats import Summary

BANK = ("fair", "push", "buyer", "orders", "tender", "banquet")


@pytest.fixture
def cfg():
    return config.load()


def test_runs_are_deterministic(cfg):
    a = [r["coins"] for g in run_many(cfg, 3, seed=7) for r in g.players]
    b = [r["coins"] for g in run_many(cfg, 3, seed=7) for r in g.players]
    assert a == b


@pytest.mark.parametrize("players", [6, 7, 10, 13])
def test_money_adds_up(cfg, players):
    cfg["players"] = players
    for st in run_many(cfg, 5, seed=players):
        for r in st.players:
            expected = (cfg["start_coins"] + sum(r[s] for s in BANK) + r["market_in"]
                        - r["market_out"] - r["penalty"])
            assert r["coins"] == expected, r


def test_buyer_never_pays_above_max(cfg, monkeypatch):
    seen = []
    orig = Game.sell

    def sell(self, seller, card, dish, qty, price, maxp, kind):
        assert price <= maxp
        seen.append(price)
        return orig(self, seller, card, dish, qty, price, maxp, kind)

    monkeypatch.setattr(Game, "sell", sell)
    run_many(cfg, 3, seed=3)
    assert seen


def test_every_archetype_and_flag_report(cfg):
    games = run_many(cfg, 10, seed=1)
    s = Summary(games, cfg)
    assert set(s.by_arch) == set(cfg["bots"]["mix"])
    assert len(s.by_role) == len(cfg["roles"])
    assert "Флаг" in s.report()


def test_sweep_and_overrides(cfg):
    cfg["bots"]["mix"] = ["balanced"]
    res = sweep(cfg, {"buyers_per_player": [0.5, 1.0], "bots.defaults.push_prob": [0.0]}, n=3)
    assert len(res) == 2
    assert all(s.push_tries == 0 for _, s, _ in res)
    c = config.load(overrides=["banquet.bonus=0.2", "buyer.max_range=[0.8,1.2]"])
    assert c["banquet"]["bonus"] == 0.2 and c["buyer"]["max_range"] == [0.8, 1.2]
    with pytest.raises(KeyError):
        config.load(overrides=["nope.x=1"])
    assert config.split_values("0.7,1,[1,2]") == [0.7, 1, [1, 2]]


def test_human_plays_full_game(cfg, monkeypatch):
    """Скриптовый игрок проходит все экраны: работа, рынок, продажа, покупка, втюхивание, события."""
    cfg["players"] = 6
    lines: list[str] = []

    def fake_print(*a, **k):
        lines.append(" ".join(str(x) for x in a))

    def answer(prompt: str) -> str:
        recent = "\n".join(lines[-15:])
        lines.append(prompt)
        if prompt == "Действие: ":
            return "9" if "Готов (закончить рынок)" in recent else "1"
        if prompt.startswith("Выбор") or prompt == "Берёте: ":
            return "1"
        if "Enter — не продавать" in prompt:
            return "20"
        if "не втюхивать" in prompt:
            return "1"
        if prompt.strip() == "Цена:":
            return "25"
        if "(д/н)" in prompt:
            return "д"
        return ""

    monkeypatch.setattr(human, "print", fake_print, raising=False)
    monkeypatch.setattr(human, "ask", answer)
    g = make_game(cfg, 11, human=human.Human(), human_role="Грибник")
    first_day = g._fair_day

    def fair_day():
        # скрипт только собирает сырьё — к ярмарке выдаём блюда, чтобы пройти экраны продавца
        if g.day == 1:
            g.players[0].dishes.update({d: 2 for d in g.c.dishes})
        first_day()

    g._fair_day = fair_day
    g.run()
    me = g.players[0]
    assert me.role == "Грибник"
    assert g.stats.produced["грибы"] >= 3 * cfg["weeks"]
    assert any("у вашего стенда" in x for x in lines)
    assert any("Вы покупатель" in x for x in lines)
    assert g.stats.income[0]["fair"] > 0


def test_bad_qty_weights_rejected(cfg):
    # YAML читает {1:1.0} без пробела как число 61.0 — конфиг должен сказать об этом внятно
    with pytest.raises(ValueError, match="qty_weights"):
        make_game(config.load(overrides=["buyer.qty_weights={1:1.0}"]), 1)


def _through_browser(cfg: dict) -> dict:
    """Как конфиг приходит из редактора: через JSON."""
    import json
    from fair import editor
    return editor.from_json(json.loads(json.dumps(cfg)))


def test_editor_save_unchanged_keeps_file(tmp_path):
    pytest.importorskip("ruamel.yaml")
    from fair import editor
    src = config.DEFAULT_PATH.read_text(encoding="utf-8")
    p = tmp_path / "c.yaml"
    p.write_text(src, encoding="utf-8")
    editor.save(p, _through_browser(config.load(p)))
    # всё, кроме выравнивания архетипов ботов, остаётся байт в байт — комментарии на месте
    norm = lambda s: [" ".join(x.split()) for x in s.splitlines()]
    assert norm(p.read_text(encoding="utf-8")) == norm(src)
    assert (tmp_path / "c.yaml.bak").exists()


def test_editor_save_rename_and_add(tmp_path):
    pytest.importorskip("ruamel.yaml")
    from fair import editor
    p = tmp_path / "c.yaml"
    p.write_text(config.DEFAULT_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    cfg = config.load(p)
    cfg["raws"] = {("батат" if k == "картофель" else k): v for k, v in cfg["raws"].items()}
    cfg["roles"]["Огородник"] = ["батат", "капуста"]
    for d in cfg["dishes"].values():
        d["ingredients"] = {("батат" if k == "картофель" else k): v for k, v in d["ingredients"].items()}
    cfg["dishes"]["Тыквенный суп"] = {"ingredients": {"батат": 2, "соль": 1}, "category": "горячее", "base": 12}
    cfg["buyers_per_player"] = 1
    cfg = _through_browser(cfg)
    assert editor.validate(cfg) == []
    editor.save(p, cfg)
    text = p.read_text(encoding="utf-8")
    assert "Огородник: [батат, капуста]" in text and "картофель:" not in text
    assert "Тыквенный суп:" in text and "# Спрос следует за ролями" in text
    back = config.load(p)
    assert back["buyers_per_player"] == 1.0 and back["buyer"]["qty_weights"] == {1: 1.0}
    assert list(back["dishes"]["Грибной суп"]["ingredients"]) == ["грибы", "батат", "соль"]


def test_editor_validate_and_sim(cfg):
    from fair import editor
    bad = _through_browser(cfg)
    bad["roles"]["Огородник"] = ["тыква"]
    assert "тыква" in editor.validate(bad)[0]
    out = editor.simulate(_through_browser(cfg), 5, 1)
    assert out["n"] == 5 and set(out["by_role"]) == set(cfg["roles"]) and "Партий: 5" in out["report"]
