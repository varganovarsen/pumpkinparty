"""Проверка контента (CONTENT-FORMAT.md). CLI: tools/check_content.py, вызывается и из /check."""
from __future__ import annotations

import re
from pathlib import Path

import yaml

BUBBLE_MAX = 220
ID_RE = re.compile(r"^[a-z0-9_]+$")
MIN_QUIZ_FACTS = 12
FILE_RE = re.compile(r"^[a-z0-9_./-]+$")


def file_problem(base: Path, rel: str) -> str | None:
    """Ошибка имени файла: регистр и пробелы (на Linux регистр важен), точное совпадение с диском."""
    if not FILE_RE.match(rel):
        return "имя файла: только латиница в нижнем регистре, цифры, _ - . / (без пробелов)"
    cur = base
    for part in Path(rel).parts:
        try:
            names = {p.name for p in cur.iterdir()}
        except OSError:
            return "нет файла"
        if part not in names:
            return "нет файла (проверьте регистр букв)" if part.lower() in {n.lower() for n in names} else "нет файла"
        cur = cur / part
    return None


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
            if not FILE_RE.match(str(audio)):
                errors.append(f"{where}: audio — латиница в нижнем регистре без пробелов")
            elif file_problem(content_dir / "audio", str(audio)) == "нет файла (проверьте регистр букв)":
                errors.append(f"{where}: audio/{audio} — регистр букв не совпадает с файлом")
            elif not ap.exists():
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
                problem = file_problem(content_dir / "images", str(img))
                if problem:
                    errors.append(f"{qw}: images/{img}: {problem}")
            elif ri == 2:
                errors.append(f"{qw}: в раунде 2 у вопроса должна быть image")
        if ri == 2 and len(set(images)) != len(images):
            errors.append(f"{rw}: картинки сортов повторяются")


SEED_KINDS = ("regular", "golden", "rainbow")


def check_seeds(content_dir: Path, errors: list[str], warnings: list[str]) -> None:
    path = content_dir / "seeds.yaml"
    if not path.exists():
        warnings.append("seeds.yaml: нет файла, охота за семечками недоступна (python tools/make_seeds.py)")
        return
    data = _load(path, errors)
    if data is None:
        return
    if not isinstance(data, list):
        errors.append("seeds.yaml: ожидается список семечек")
        return
    seen: set[str] = set()
    kinds = {k: 0 for k in SEED_KINDS}
    lengths: set[int] = set()
    for i, s in enumerate(data, 1):
        where = f"seeds.yaml, семечка {i}"
        if not isinstance(s, dict):
            errors.append(f"{where}: ожидается словарь")
            continue
        code = s.get("code")
        if not isinstance(code, str) or not re.fullmatch(r"\d{3,8}", code):
            errors.append(f"{where}: code — строка из 3-8 цифр в кавычках, например \"0481\"")
            continue
        if code in seen:
            errors.append(f"{where}: повтор кода {code}")
        seen.add(code)
        lengths.add(len(code))
        kind = s.get("kind", "regular")
        if kind not in SEED_KINDS:
            errors.append(f"{where}: kind — regular, golden или rainbow")
        else:
            kinds[kind] += 1
    if len(lengths) > 1:
        warnings.append("seeds.yaml: коды разной длины, телефон не сможет отправлять код сам по последней цифре")
    if kinds["rainbow"] != 1:
        warnings.append(f"seeds.yaml: радужных семечек {kinds['rainbow']}, задумана одна")
    if not data:
        warnings.append("seeds.yaml: список пуст")


def check_bomb(content_dir: Path, errors: list[str], warnings: list[str], rounds: int = 3) -> None:
    path = content_dir / "bomb.yaml"
    if not path.exists():
        warnings.append("bomb.yaml: нет файла, «Бомба» недоступна")
        return
    data = _load(path, errors)
    if data is None:
        return
    if not isinstance(data, list):
        errors.append("bomb.yaml: ожидается список тем")
        return
    seen: set[str] = set()
    for i, t in enumerate(data, 1):
        if not isinstance(t, str) or not t.strip():
            errors.append(f"bomb.yaml, тема {i}: ожидается непустая строка")
            continue
        key = t.strip().casefold()
        if key in seen:
            warnings.append(f"bomb.yaml: тема «{t.strip()}» повторяется")
        seen.add(key)
        if len(t) > 60:
            warnings.append(f"bomb.yaml, тема {i}: длиннее 60 символов, на ТВ будет мелко")
    if len(seen) < rounds:
        warnings.append(f"bomb.yaml: тем {len(seen)}, на {rounds} раунда без повторов нужно больше")


def check(content_dir: Path) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    check_facts(content_dir, errors, warnings)
    check_quiz(content_dir, errors, warnings)
    check_seeds(content_dir, errors, warnings)
    check_bomb(content_dir, errors, warnings)
    return errors, warnings
