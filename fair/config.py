"""Конфиг и контент: config.yaml, переопределения из CLI (--set a.b=1), справочники сырья, блюд, ролей."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

DEFAULT_PATH = Path(__file__).with_name("config.yaml")


def load(path: str | Path | None = None, overrides: list[str] = ()) -> dict:
    with open(path or DEFAULT_PATH, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    for ov in overrides:
        set_path(cfg, *parse_override(ov))
    return cfg


def parse_override(s: str) -> tuple[str, object]:
    key, eq, raw = s.partition("=")
    if not eq:
        raise ValueError(f"ожидалось ключ=значение: {s}")
    return key.strip(), yaml.safe_load(raw)


def set_path(cfg: dict, key: str, value) -> None:
    node = cfg
    parts = key.split(".")
    for part in parts[:-1]:
        if not isinstance(node, dict) or part not in node:
            raise KeyError(f"нет параметра {key}")
        node = node[part]
    # новые ключи разрешены только в архетипах ботов (там пустые словари)
    if parts[-1] not in node and "archetypes" not in parts:
        raise KeyError(f"нет параметра {key}")
    node[parts[-1]] = value


def split_values(s: str) -> list:
    """'0.7,1.0,[1,2]' -> [0.7, 1.0, [1, 2]] — запятые внутри скобок не делят."""
    out, depth, cur = [], 0, ""
    for ch in s:
        if ch in "[{":
            depth += 1
        elif ch in "]}":
            depth -= 1
        if ch == "," and depth == 0:
            out.append(cur)
            cur = ""
        else:
            cur += ch
    out.append(cur)
    return [yaml.safe_load(v) for v in out if v.strip()]


@dataclass(frozen=True)
class Dish:
    name: str
    ingredients: dict[str, int]
    category: str
    cheap: str | None
    base: int

    @property
    def main(self) -> str:
        return next(iter(self.ingredients))


class Content:
    def __init__(self, cfg: dict):
        self.raws: dict[str, int] = {k: int(v) for k, v in cfg["raws"].items()}
        self.roles: dict[str, tuple[str, ...]] = {k: tuple(v) for k, v in cfg["roles"].items()}
        self.dishes: dict[str, Dish] = {
            name: Dish(name, dict(d["ingredients"]), d["category"], d.get("cheap"), int(d["base"]))
            for name, d in cfg["dishes"].items()
        }
        self.categories = sorted({d.category for d in self.dishes.values()})
        for d in self.dishes.values():
            for r in d.ingredients:
                if r not in self.raws:
                    raise ValueError(f"{d.name}: сырья «{r}» нет в списке raws")
            if d.cheap and d.cheap not in self.roles:
                raise ValueError(f"{d.name}: роли «{d.cheap}» нет")
        for role, prof in self.roles.items():
            for r in prof:
                if r not in self.raws:
                    raise ValueError(f"{role}: сырья «{r}» нет в списке raws")
        for k, w in cfg["buyer"]["qty_weights"].items():
            if not isinstance(w, (int, float)) or not str(k).isdigit():
                raise ValueError(f"buyer.qty_weights: «{k}: {w}» — нужно {{штук: вес}}, в YAML с пробелом после двоеточия")
        for cat in cfg["events"]["weather"].values():
            if cat not in self.categories:
                raise ValueError(f"категории «{cat}» нет ни у одного блюда")

    def raw_cost(self, dish: str) -> int:
        return sum(self.raws[r] * q for r, q in self.dishes[dish].ingredients.items())
