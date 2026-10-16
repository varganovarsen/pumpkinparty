"""Лист для печати семечек (/seeds/print): вырезать по пунктиру и спрятать. Вторая страница — шпаргалка ведущему."""
from __future__ import annotations

from html import escape

KIND_TITLES = {"regular": "обычная", "golden": "золотая", "rainbow": "радужная мегасемка"}

CSS = """
@page { size: A4; margin: 10mm; }
* { box-sizing: border-box; }
body { font-family: system-ui, sans-serif; margin: 16px; color: #222; background: #fff; }
.note { max-width: 720px; margin-bottom: 16px; padding: 10px 14px; background: #fff4e0; border-radius: 8px; }
.note button { font-size: 16px; padding: 6px 14px; margin-top: 6px; }
.sheet { display: flex; flex-wrap: wrap; gap: 0; }
.card { width: 45mm; height: 30mm; border: 1px dashed #bbb; display: flex; align-items: center;
        justify-content: center; page-break-inside: avoid; break-inside: avoid; }
.seed { width: 36mm; height: 22mm; border-radius: 62% 38% 38% 62% / 50% 50% 50% 50%;
        display: flex; align-items: center; justify-content: center; border: 0.6mm solid #a88a4c;
        background: radial-gradient(ellipse at 35% 40%, #fffaf0, #efdcae 70%, #d9bf82);
        -webkit-print-color-adjust: exact; print-color-adjust: exact; }
.seed b { font: 700 19pt/1 ui-monospace, Consolas, monospace; letter-spacing: 1.5pt; color: #3b2a10; }
.golden .seed { border-color: #a27a00; background: radial-gradient(ellipse at 35% 40%, #fff7c2, #f5cd2e 65%, #c99400); }
.rainbow { width: 90mm; height: 60mm; }
.rainbow .seed { width: 78mm; height: 46mm; border: 0.8mm solid #333;
        background: linear-gradient(115deg, #ff4d4d, #ffa64d, #ffe14d, #5ce65c, #4dc3ff, #6b6bff, #c44dff); }
.rainbow .seed b { font-size: 34pt; color: #fff; text-shadow: 0 0 2px #000, 0 0 4px #000; }
.cheat { page-break-before: always; break-before: page; }
table { border-collapse: collapse; width: 100%; font-size: 12pt; }
td, th { border: 1px solid #ccc; padding: 4px 8px; text-align: left; }
td.code { font-family: ui-monospace, Consolas, monospace; font-weight: 700; }
@media print { .note { display: none; } body { margin: 0; } }
"""


def render(seeds: list[dict], points: dict) -> str:
    cards = []
    # радужную в конец: она крупная и не ломает сетку маленьких
    for s in sorted(seeds, key=lambda s: s["kind"] == "rainbow"):
        cards.append(f'<div class="card {s["kind"]}"><div class="seed"><b>{escape(s["code"])}</b></div></div>')
    rows = "".join(
        f'<tr><td class="code">{escape(s["code"])}</td><td>{KIND_TITLES[s["kind"]]} (+{int(points.get(s["kind"], 0))})</td>'
        f'<td>{escape(s.get("place") or "")}</td><td style="width:30mm"></td></tr>'
        for s in seeds
    )
    counts = {k: sum(1 for s in seeds if s["kind"] == k) for k in KIND_TITLES}
    summary = ", ".join(f"{KIND_TITLES[k]}: {n}" for k, n in counts.items() if n)
    body = (
        '<div class="note"><b>Семечки для охоты.</b> Распечатайте в цвете на A4, вырежьте по пунктиру и спрячьте. '
        f'Всего {len(seeds)} ({summary}). Вторая страница — шпаргалка ведущему с кодами; гостям её не показывать. '
        'Коды меняются в content/seeds.yaml.<br><button onclick="print()">Печать</button></div>'
        f'<div class="sheet">{"".join(cards)}</div>'
        '<div class="cheat"><h2>Шпаргалка ведущему</h2>'
        '<table><tr><th>Код</th><th>Какая</th><th>Где спрятана</th><th>Отметка</th></tr>'
        f'{rows}</table></div>'
    )
    if not seeds:
        body = '<p>Нет семечек: создайте content/seeds.yaml командой <code>python tools/make_seeds.py</code>.</p>'
    return (f'<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>Семечки для печати</title>'
            f'<style>{CSS}</style></head><body>{body}</body></html>')
