"""Песочница модуля для телефона: один html без сервера.

    python tools/make_sandbox.py quiz [--out data/sandbox/quiz.html]

Склеивает настоящие стили и код экрана игрока (web/shared, web/play) с подставным сервером
из tools/sandbox/<модуль>.js. Вопросы — из content/ (PUMPKIN_CONTENT меняет папку).
Файл открывается в браузере как есть или публикуется ссылкой, чтобы смотреть с телефона.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
SANDBOX = Path(__file__).resolve().parent / "sandbox"
ROUND4_TITLE = "Факты"  # как в server/quiz.py


def module_source(path: Path) -> str:
    """Код ES-модуля без import (всё склеивается в один <script type="module">)."""
    text = path.read_text(encoding="utf-8")
    return re.sub(r"^import .*?;\n", "", text, flags=re.M | re.S)


def data_uri(path: Path) -> str:
    mime = {".png": "image/png", ".jpg": "image/jpeg", ".svg": "image/svg+xml"}[path.suffix]
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"


def quiz_data(content: Path) -> dict:
    quiz = yaml.safe_load((content / "quiz.yaml").read_text(encoding="utf-8"))
    rounds = [{"title": r["title"], "kind": "choice",
               "questions": [{k: q[k] for k in ("id", "text", "options", "correct")} for q in r["questions"]]}
              for r in quiz["rounds"]]
    facts = yaml.safe_load((content / "facts.yaml").read_text(encoding="utf-8")) or []
    r4 = [{"id": f"r4q{i + 1}", "text": f["quiz"]["question"], "answer": f["quiz"]["answer"]}
          for i, f in enumerate(f for f in facts if f.get("quiz"))][:5]
    if r4:
        rounds.append({"title": ROUND4_TITLE, "kind": "text", "questions": r4})
    return {"rounds": rounds, "avatar": data_uri(ROOT / "assets" / "avatars" / "pumpkin-1.png")}


MODULES = {
    "quiz": {"title": "Квиз на телефоне", "code": [WEB / "play" / "quiz.js"], "data": quiz_data},
}


def build(name: str) -> str:
    spec = MODULES[name]
    content = Path(os.environ.get("PUMPKIN_CONTENT") or ROOT / "content")
    css = "\n".join(p.read_text(encoding="utf-8")
                    for p in (WEB / "shared" / "ui.css", WEB / "play" / "play.css", SANDBOX / "sandbox.css"))
    js = "\n".join(module_source(p) for p in [WEB / "shared" / "util.js", *spec["code"], SANDBOX / f"{name}.js"])
    data = json.dumps(spec["data"](content), ensure_ascii=False).replace("</", "<\\/")
    js = js.replace("</script", "<\\/script")
    return (f'<title>{spec["title"]}</title>\n'
            '<meta name="claude:viewport-fit-sides" content="cover">\n'
            '<meta name="theme-color" content="#17110d">\n'
            f"<style>\n{css}\n</style>\n"
            '<div id="app"></div>\n'
            f"<script>window.SANDBOX = {data};</script>\n"
            f'<script type="module">\n{js}\n</script>\n')


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("module", choices=sorted(MODULES))
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    out = a.out or ROOT / "data" / "sandbox" / f"{a.module}.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build(a.module), encoding="utf-8")
    print(f"Готово: {out}")


if __name__ == "__main__":
    main()
