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
    def __init__(self, root: Path):
        self.dir = root / "content"
        self._facts = YamlFile(self.dir / "facts.yaml", [])
        self._quiz = YamlFile(self.dir / "quiz.yaml", {})

    def facts(self) -> list[dict]:
        data = self._facts.get()
        if not isinstance(data, list):
            return []
        return [f for f in data if isinstance(f, dict) and f.get("id") and f.get("text")]

    def fact(self, fact_id: str) -> dict | None:
        return next((f for f in self.facts() if f["id"] == fact_id), None)

    def quiz(self) -> dict:
        data = self._quiz.get()
        return data if isinstance(data, dict) else {}
