"""Проверка контента (CONTENT-FORMAT.md). CLI: tools/check_content.py, вызывается и из /check."""
from __future__ import annotations

import re
from pathlib import Path

import yaml

BUBBLE_MAX = 220
ID_RE = re.compile(r"^[a-z0-9_]+$")
MIN_QUIZ_FACTS = 12


def _load(path: Path, errors: list[str]):
    if not path.exists():
        errors.append(f"{path.name}: файл не найден")
        return None
    try:
        with path.open(encoding="utf-8") as f:
            return yaml.safe_load(f)
    except Exception as e:  # noqa: BLE001
        errors.append(f"{path.name}: ошибка YAML: {e}")
        return None


def check_facts(content_dir: Path, errors: list[str], warnings: list[str]) -> None:
    data = _load(content_dir / "facts.yaml", errors)
    if data is None:
        return
    if not isinstance(data, list):
        errors.append("facts.yaml: ожидается список фактов")
        return
    seen: set[str] = set()
    with_quiz = 0
    for i, f in enumerate(data, 1):
        where = f"facts.yaml, факт {i}"
        if not isinstance(f, dict):
            errors.append(f"{where}: ожидается словарь")
            continue
        fid = str(f.get("id", ""))
        where = f"facts.yaml, {fid or f'факт {i}'}"
        if not fid or not ID_RE.match(fid):
            errors.append(f"{where}: id обязателен, нижний регистр, без пробелов")
        elif fid in seen:
            errors.append(f"{where}: повтор id")
        seen.add(fid)
        text = f.get("text")
        if not isinstance(text, str) or not text.strip():
            errors.append(f"{where}: нет текста")
        elif len(text) > BUBBLE_MAX:
            errors.append(f"{where}: текст {len(text)} символов, лимит пузыря {BUBBLE_MAX}")
        audio = f.get("audio")
        if audio:
            ap = content_dir / "audio" / str(audio)
            if not str(audio).endswith(".mp3"):
                errors.append(f"{where}: озвучка только mp3")
            if not ap.exists():
                warnings.append(f"{where}: нет файла audio/{audio} (голова будет молчать)")
            elif not ap.with_suffix(".lipsync.json").exists():
                warnings.append(f"{where}: нет audio/{ap.stem}.lipsync.json (запустить tools/make_lipsync.py)")
        q = f.get("quiz")
        if q is not None:
            if not isinstance(q, dict) or not q.get("question") or not q.get("answer"):
                errors.append(f"{where}: блок quiz требует question и answer")
            else:
                with_quiz += 1
    if not 35 <= len(data) <= 40:
        warnings.append(f"facts.yaml: фактов {len(data)}, ожидается 35-40")
    if with_quiz < MIN_QUIZ_FACTS:
        warnings.append(f"facts.yaml: фактов с блоком quiz {with_quiz}, нужно минимум {MIN_QUIZ_FACTS}")


def check_quiz(content_dir: Path, errors: list[str], warnings: list[str]) -> None:
    data = _load(content_dir / "quiz.yaml", errors)
    if data is None:
        return
    rounds = data.get("rounds") if isinstance(data, dict) else None
    if not isinstance(rounds, list):
        errors.append("quiz.yaml: нет списка rounds")
        return
    if len(rounds) != 3:
        errors.append(f"quiz.yaml: раундов {len(rounds)}, нужно 3 (раунд 4 собирается из фактов)")
    seen: set[str] = set()
    for ri, r in enumerate(rounds, 1):
        if not isinstance(r, dict):
            errors.append(f"quiz.yaml, раунд {ri}: ожидается словарь")
            continue
        rid = str(r.get("id", ""))
        rw = f"quiz.yaml, {rid or f'раунд {ri}'}"
        if not rid or not ID_RE.match(rid):
            errors.append(f"{rw}: id обязателен, нижний регистр, без пробелов")
        elif rid in seen:
            errors.append(f"{rw}: повтор id")
        seen.add(rid)
        if not r.get("title"):
            errors.append(f"{rw}: нет title")
        qs = r.get("questions")
        if not isinstance(qs, list):
            errors.append(f"{rw}: нет списка questions")
            continue
        if len(qs) != 10:
            errors.append(f"{rw}: вопросов {len(qs)}, нужно 10")
        images: list[str] = []
        for qi, q in enumerate(qs, 1):
            if not isinstance(q, dict):
                errors.append(f"{rw}, вопрос {qi}: ожидается словарь")
                continue
            qid = str(q.get("id", ""))
            qw = f"quiz.yaml, {qid or f'{rid} вопрос {qi}'}"
            if not qid or not ID_RE.match(qid):
                errors.append(f"{qw}: id обязателен, нижний регистр, без пробелов")
            elif qid in seen:
                errors.append(f"{qw}: повтор id")
            seen.add(qid)
            if not q.get("text"):
                errors.append(f"{qw}: нет text")
            opts = q.get("options")
            if not isinstance(opts, list) or len(opts) != 4:
                errors.append(f"{qw}: нужно ровно 4 варианта")
            c = q.get("correct")
            if not isinstance(c, int) or isinstance(c, bool) or not 0 <= c <= 3:
                errors.append(f"{qw}: correct должен быть индексом 0-3")
            img = q.get("image")
            if img:
                images.append(str(img))
                if not (content_dir / "images" / str(img)).exists():
                    errors.append(f"{qw}: нет файла images/{img}")
            elif ri == 2:
                errors.append(f"{qw}: в раунде 2 у вопроса должна быть image")
        if ri == 2 and len(set(images)) != len(images):
            errors.append(f"{rw}: картинки сортов повторяются")


def check(content_dir: Path) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    check_facts(content_dir, errors, warnings)
    check_quiz(content_dir, errors, warnings)
    return errors, warnings
