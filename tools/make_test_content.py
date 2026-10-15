"""Сгенерировать тестовый контент для автотестов и симулятора: tests/fixtures/content/.

3 раунда по 10 вопросов (правильный ответ всегда имеет текст «верно …»), 15 фактов,
у 12 из них есть блок quiz. Картинки раунда 2 — маленькие PNG-заглушки.

    python tools/make_test_content.py
"""
from __future__ import annotations

from pathlib import Path

import yaml
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "tests" / "fixtures" / "content"


def main() -> None:
    (OUT / "images" / "sorts").mkdir(parents=True, exist_ok=True)
    (OUT / "audio").mkdir(parents=True, exist_ok=True)
    rounds = []
    for r in (1, 2, 3):
        qs = []
        for i in range(1, 11):
            correct = (r + i) % 4
            opts = [f"вариант {k}" for k in range(4)]
            opts[correct] = f"верно {r}.{i}"
            q = {"id": f"r{r}q{i:02d}", "text": f"Тестовый вопрос {i} раунда {r}?", "options": opts, "correct": correct}
            if r == 2:
                q["image"] = f"sorts/sort{i:02d}.png"
                Image.new("RGB", (64, 48), (20 * i, 120, 60)).save(OUT / "images" / "sorts" / f"sort{i:02d}.png")
            if i == 1:
                q["explain"] = "Пояснение к тестовому вопросу."
            qs.append(q)
        rounds.append({"id": f"r{r}", "title": f"Тестовый раунд {r}", "questions": qs})
    facts = []
    for i in range(1, 16):
        f = {"id": f"t{i:03d}", "text": f"Тестовый факт номер {i}."}
        if i <= 12:
            f["quiz"] = {"question": f"Какой номер у тестового факта {i}?", "answer": str(i)}
        facts.append(f)
    dump = {"allow_unicode": True, "sort_keys": False}
    (OUT / "quiz.yaml").write_text("# Сгенерировано tools/make_test_content.py\n" + yaml.safe_dump({"rounds": rounds}, **dump),
                                   encoding="utf-8", newline="\n")
    (OUT / "facts.yaml").write_text("# Сгенерировано tools/make_test_content.py\n" + yaml.safe_dump(facts, **dump),
                                    encoding="utf-8", newline="\n")
    print(f"Тестовый контент: {OUT}")


if __name__ == "__main__":
    main()
