"""Сгенерировать коды семечек для охоты: content/seeds.yaml.

    python tools/make_seeds.py                         20 обычных, 5 золотых, 1 радужная
    python tools/make_seeds.py --regular 15 --golden 4 --force

Коды из 4 цифр, случайные и непохожие друг на друга (отличаются минимум двумя цифрами,
без простых вроде 1111 и 1234). Существующий файл не перезаписывается без --force:
если семечки уже распечатаны, новые коды с ними не совпадут.
Потом: распечатать лист на /seeds/print (ссылка в /host, сцена «Охота за семечками»).
"""
from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

HEADER = """\
# Семечки для охоты (модуль 09). Сгенерировано tools/make_seeds.py, можно править руками.
# code  — цифры в кавычках (уникальные, одной длины); kind — regular | golden | rainbow (одна);
# place — где спрятана: видно только ведущему (/host и шпаргалка при печати).
# Очки за виды — в config.yaml, раздел seeds.
"""


def boring(code: str) -> bool:
    digits = [int(c) for c in code]
    steps = {b - a for a, b in zip(digits, digits[1:])}
    return len(set(code)) <= 2 or steps in ({1}, {-1}) or code[:2] == code[2:]


def make_codes(n: int, rnd: random.Random) -> list[str]:
    codes: list[str] = []
    tries = 0
    while len(codes) < n:
        tries += 1
        if tries > 100000:
            sys.exit("Не удалось подобрать столько непохожих кодов")
        c = f"{rnd.randrange(10000):04d}"
        if boring(c) or any(sum(a != b for a, b in zip(c, o)) < 2 for o in codes):
            continue
        codes.append(c)
    return codes


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--regular", type=int, default=20)
    ap.add_argument("--golden", type=int, default=5)
    ap.add_argument("--rainbow", type=int, default=1)
    ap.add_argument("--out", type=Path, default=ROOT / "content" / "seeds.yaml")
    ap.add_argument("--seed", type=int, help="для воспроизводимости (тесты)")
    ap.add_argument("--force", action="store_true", help="перезаписать существующий файл")
    a = ap.parse_args()
    if a.out.exists() and not a.force:
        sys.exit(f"{a.out} уже есть. Если семечки ещё не распечатаны: --force")
    rnd = random.Random(a.seed)
    kinds = ["regular"] * a.regular + ["golden"] * a.golden + ["rainbow"] * a.rainbow
    codes = make_codes(len(kinds), rnd)
    lines = [HEADER]
    for code, kind in zip(codes, kinds):
        lines.append(f'- {{code: "{code}", kind: {kind}, place: ""}}\n')
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text("".join(lines), encoding="utf-8")
    print(f"Записано {len(codes)} семечек в {a.out}")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
