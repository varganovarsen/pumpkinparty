"""Чтение контента из content/ (facts.yaml, quiz.yaml) с перечитыванием по mtime."""
from __future__ import annotations

from pathlib import Path

import yaml


class YamlFile:
    """Файл YAML, перечитываемый при изменении. Ошибка чтения не роняет сервер."""

    def __init__(self, path: Path, default):
        self.path = path
        self.default = default
        self._mtime: float | None = None
        self._data = default
        self.error: str | None = None

    def get(self):
        try:
            mtime = self.path.stat().st_mtime
        except FileNotFoundError:
            self._mtime, self._data, self.error = None, self.default, "файл не найден"
            return self._data
        if mtime != self._mtime:
            self._mtime = mtime
            try:
                with self.path.open(encoding="utf-8") as f:
                    self._data = yaml.safe_load(f) or self.default
                self.error = None
            except Exception as e:  # noqa: BLE001 — любой сбой контента не должен ронять вечер
                self._data, self.error = self.default, f"ошибка чтения: {e}"
        return self._data


class Content:
    def __init__(self, content_dir: Path):
        self.dir = content_dir
        self._facts = YamlFile(self.dir / "facts.yaml", [])
        self._quiz = YamlFile(self.dir / "quiz.yaml", {})
        self._seeds = YamlFile(self.dir / "seeds.yaml", [])

    def facts(self) -> list[dict]:
        data = self._facts.get()
        if not isinstance(data, list):
            return []
        # id всегда строка: в YAML «id: 001» превращается в число 1
        return [{**f, "id": str(f["id"])} for f in data if isinstance(f, dict) and f.get("id") is not None and f.get("text")]

    def fact(self, fact_id: str) -> dict | None:
        return next((f for f in self.facts() if f["id"] == fact_id), None)

    def quiz(self) -> dict:
        data = self._quiz.get()
        return data if isinstance(data, dict) else {}

    def seeds(self) -> list[dict]:
        """Семечки для охоты: [{code, kind, place}]; код — строка цифр, kind — regular|golden|rainbow."""
        data = self._seeds.get()
        if not isinstance(data, list):
            return []
        out, seen = [], set()
        for s in data:
            if not isinstance(s, dict):
                continue
            code = "".join(ch for ch in str(s.get("code", "")) if ch.isdigit())
            kind = s.get("kind", "regular")
            if not code or code in seen or kind not in ("regular", "golden", "rainbow"):
                continue
            seen.add(code)
            out.append({"code": code, "kind": kind, "place": str(s.get("place") or "")})
        return out
