"""Песочница для телефона: один html без сервера.

    python tools/make_sandbox.py player|quiz|bomb [--out data/sandbox/<имя>.html]

player — всё приложение игрока (web/play) целиком: вход, вкладки, все сцены. Настоящий код
работает как есть, подменены только WebSocket и fetch: они говорят с «сервером» внутри страницы
(tools/sandbox/server.js) по тому же протоколу (docs/PROTOCOL.md). Сцены переключает пульт ведущего.
quiz, bomb — один экран модуля с подробным пультом; у bomb есть и вид ТВ (<iframe>).

Модули склеиваются мини-сборщиком: каждый файл в своей области видимости, import/export
переписываются на общий реестр. Контент — из content/ (PUMPKIN_CONTENT меняет папку).
Файл открывается в браузере как есть или публикуется ссылкой, чтобы смотреть с телефона.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
SANDBOX = Path(__file__).resolve().parent / "sandbox"
ROUND4_TITLE = "Факты"  # как в server/quiz.py
sys.path.insert(0, str(ROOT))  # server.config, server.game

IMPORT_RE = re.compile(r"^import\s*\{([^}]*)\}\s*from\s*'([^']+)';[ \t]*\n", re.M)
EXPORT_RE = re.compile(r"^export\s+(?:async\s+)?(?:function\*?|class|const|let)\s+([A-Za-z_$][\w$]*)", re.M)


def web(rel: str) -> tuple[str, Path]:
    return f"/web/{rel}", WEB / rel


def sb(rel: str) -> tuple[str, Path]:
    return f"/sandbox/{rel}", SANDBOX / rel


def wrap_module(key: str, src: str) -> str:
    """ES-модуль → функция в реестре __m: import {a, b as c} → const {a, b: c} = __m[...]."""
    def imp(m: re.Match) -> str:
        names = ", ".join(n.strip().replace(" as ", ": ") for n in m.group(1).split(",") if n.strip())
        return f"const {{ {names} }} = __m[{json.dumps(m.group(2))}];\n"
    src = IMPORT_RE.sub(imp, src)
    if re.search(r"^import\s", src, re.M):
        raise SystemExit(f"{key}: сборщик понимает только import {{…}} from '…';")
    names = EXPORT_RE.findall(src)
    src = re.sub(r"^export\s+", "", src, flags=re.M)
    return f"__m[{json.dumps(key)}] = (() => {{\n{src}\nreturn {{ {', '.join(names)} }};\n}})();\n"


def bundle(files: list[tuple[str, Path]], rewrites: dict[str, list[tuple[str, str]]] | None = None) -> str:
    """Модули по порядку: каждый видит только то, что объявлено до него."""
    parts = ["const __m = {};"]
    for key, path in files:
        src = path.read_text(encoding="utf-8")
        for old, new in (rewrites or {}).get(key, []):
            if old not in src:
                raise SystemExit(f"{key}: не найдено место для подмены: {old}")
            src = src.replace(old, new)
        parts.append(wrap_module(key, src))
    return "\n".join(parts).replace("</script", "<\\/script")


def data_uri(path: Path) -> str:
    mime = {".png": "image/png", ".jpg": "image/jpeg", ".svg": "image/svg+xml"}[path.suffix]
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"


def config() -> dict:
    from server.config import load_config
    return load_config(ROOT / "config.yaml")


# ---------------------------------------------------------------------- данные песочниц
def quiz_rounds(content: Path) -> list[dict]:
    quiz = yaml.safe_load((content / "quiz.yaml").read_text(encoding="utf-8"))
    rounds = [{"title": r["title"], "kind": "choice",
               "questions": [{k: q[k] for k in ("id", "text", "options", "correct")} for q in r["questions"]]}
              for r in quiz["rounds"]]
    facts = yaml.safe_load((content / "facts.yaml").read_text(encoding="utf-8")) or []
    r4 = [{"id": f"r4q{i + 1}", "text": f["quiz"]["question"], "answer": f["quiz"]["answer"]}
          for i, f in enumerate(f for f in facts if f.get("quiz"))][:5]
    if r4:
        rounds.append({"title": ROUND4_TITLE, "kind": "text", "questions": r4})
    return rounds


def bomb_settings(content: Path) -> dict:
    topics = yaml.safe_load((content / "bomb.yaml").read_text(encoding="utf-8")) or []
    cfg = config()["bomb"]
    return {"topics": [str(t) for t in topics if str(t or "").strip()], "rounds": cfg["rounds"], "points": cfg["points"],
            "timing": {k: cfg[k] for k in ("start_seconds", "step_seconds", "min_seconds")}}


def avatars() -> list[str]:
    return [data_uri(ROOT / "assets" / "avatars" / f"pumpkin-{i}.png") for i in range(1, 9)]


def quiz_data(content: Path) -> dict:
    return {"rounds": quiz_rounds(content), "avatar": avatars()[0]}


def bomb_data(content: Path) -> dict:
    return {**bomb_settings(content), "avatars": avatars()[:5]}


def player_data(content: Path) -> dict:
    from server.game import generate
    cfg = config()
    facts = yaml.safe_load((content / "facts.yaml").read_text(encoding="utf-8")) or []
    seeds = yaml.safe_load((content / "seeds.yaml").read_text(encoding="utf-8")) if (content / "seeds.yaml").exists() else []
    stickers = sorted((ROOT / "assets" / "stickers").glob("*.png"))
    game = cfg["game"]
    return {
        "avatars": avatars(),
        "stickers": [data_uri(p) for p in stickers],
        "game_sprites": {n: data_uri(ROOT / "assets" / "game" / f"{n}.png") for n in ("pumpkin", "golden", "rotten", "basket")},
        "facts": [f["text"] for f in facts if isinstance(f, dict) and f.get("text")],
        "quiz": quiz_rounds(content),
        "bomb": bomb_settings(content),
        "game": {
            "points": game["points"],
            "practice": {"seconds": game["practice_seconds"], "items": generate(7, "practice", game["practice_seconds"])},
            "scored": {"seconds": game["scored_seconds"], "items": generate(7, "scored", game["scored_seconds"])},
        },
        "seeds": {"codes": [{"code": str(s["code"]), "kind": s.get("kind", "regular")} for s in seeds or []],
                  "minutes": cfg["seeds"]["minutes"], "points": cfg["seeds"]["points"],
                  "wrong_limit": cfg["seeds"]["wrong_limit"], "cooldown_seconds": cfg["seeds"]["cooldown_seconds"]},
    }


PLAY = ["quiz.js", "game.js", "seeds.js", "bomb.js", "vote.js", "editor.js", "album.js", "avatar_picker.js"]

MODULES = {
    "player": {
        "title": "Тыквенный спас: игрок",
        "files": [web("shared/util.js"), web("shared/ws.js"), sb("engine_quiz.js"), sb("engine_bomb.js"), sb("server.js"),
                  *(web(f"play/{f}") for f in PLAY), web("play/play.js"), sb("player.js")],
        "data": player_data,
        "scripts": [WEB / "vendor" / "konva" / "konva.min.js"],
        # картинки игры грузятся по путям сервера: в песочнице — из встроенных data:
        "rewrites": {"/web/play/game.js": [("img[s].src = `/assets/game/${s}.png`;",
                                            "img[s].src = window.SANDBOX.game_sprites[s];")]},
    },
    "quiz": {"title": "Квиз на телефоне", "data": quiz_data,
             "files": [web("shared/util.js"), web("play/quiz.js"), sb("engine_quiz.js"), sb("quiz.js")]},
    "bomb": {"title": "Песочница «Бомбы»", "data": bomb_data, "tv": WEB / "tv" / "scenes" / "bomb.js",
             "files": [web("shared/util.js"), web("play/bomb.js"), sb("engine_bomb.js"), sb("bomb.js")]},
}


def tv_document(scene: Path) -> str:
    """Отдельная страница ТВ для <iframe>: стили ТВ и модуль сцены, mount() — в window.__mount."""
    css = "\n".join(p.read_text(encoding="utf-8") for p in (WEB / "shared" / "ui.css", WEB / "tv" / "tv.css"))
    js = bundle([web("shared/util.js"), ("/tv/scene.js", scene)]) + "\nwindow.__mount = __m['/tv/scene.js'].mount;\n"
    return ('<!doctype html><html lang="ru"><head><meta charset="utf-8">'
            f"<style>{css}\nhtml, body {{ cursor: default; }}</style></head>"
            f'<body><div id="stage"><div class="scene-root" id="root"></div></div>'
            f'<script type="module">{js}</script></body></html>')


def build(name: str) -> str:
    spec = MODULES[name]
    content = Path(os.environ.get("PUMPKIN_CONTENT") or ROOT / "content")
    css = "\n".join(p.read_text(encoding="utf-8")
                    for p in (WEB / "shared" / "ui.css", WEB / "play" / "play.css", SANDBOX / "sandbox.css"))
    js = bundle(spec["files"], spec.get("rewrites"))
    data = spec["data"](content)
    if spec.get("tv"):
        data["tvHtml"] = tv_document(spec["tv"])
    data = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    scripts = "".join("<script>" + p.read_text(encoding="utf-8").replace("</script", "<\\/script") + "</script>\n"
                      for p in spec.get("scripts", []))
    return (f'<title>{spec["title"]}</title>\n'
            '<meta name="claude:viewport-fit-sides" content="cover">\n'
            '<meta name="theme-color" content="#17110d">\n'
            f"<style>\n{css}\n</style>\n"
            '<div id="app"></div>\n'
            f"<script>window.SANDBOX = {data};</script>\n"
            f"{scripts}"
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
