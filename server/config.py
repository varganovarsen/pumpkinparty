"""Загрузка config.yaml с умолчаниями и переопределениями из окружения."""
from __future__ import annotations

import copy
import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent

DEFAULTS: dict = {
    "port": 8000,
    "public_host": "",
    "tv_localhost_only": True,
    "webcam_device": 0,
    "quiz": {
        "answer_seconds": 60,
        "warn_seconds": 10,
        "auto_close_delay_seconds": 2,
        "points_correct": 200,
        "bonus": [50, 25, 10],
        "hide_total_after_round3": True,
    },
    "game": {
        "practice_seconds": 15,
        "scored_seconds": 45,
        "points": {"regular": 10, "golden": 50, "rotten": -30},
        "max_points": 500,
    },
    "carve": {"bonus": [500, 300, 100], "fps_fallback_threshold": 24},
    "head": {
        "mode": "quiet",
        "interval_minutes": 6,
        "interval_jitter_minutes": 1,
        "min_gap_after_scene_minutes": 3,
    },
    "random_shots": {"interval_minutes": [8, 15], "allowed_scenes": ["ambient", "timer"]},
    "ambient": {"light_mode": False, "new_photo_card": True, "new_photo_card_seconds": 7},
    "slideshow": {"seconds_per_photo": 6},
    "host_in_scoring": False,
    "backup_interval_minutes": 5,
    # служебные ключи, в config.yaml обычно не пишутся
    "data_dir": "data",
    "content_dir": "content",
    "speed": 1.0,
}


def _merge(base: dict, extra: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (extra or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


class Config(dict):
    """Словарь настроек с удобными путями."""

    @property
    def data_dir(self) -> Path:
        p = Path(self["data_dir"])
        return p if p.is_absolute() else ROOT / p

    @property
    def content_dir(self) -> Path:
        p = Path(self["content_dir"])
        return p if p.is_absolute() else ROOT / p

    @property
    def root(self) -> Path:
        return ROOT


def load_config(path: str | os.PathLike | None = None, **overrides) -> Config:
    path = Path(path or os.environ.get("PUMPKIN_CONFIG") or ROOT / "config.yaml")
    data: dict = {}
    if path.exists():
        with path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    cfg = _merge(DEFAULTS, data)
    env = {
        "data_dir": os.environ.get("PUMPKIN_DATA"),
        "content_dir": os.environ.get("PUMPKIN_CONTENT"),
        "port": os.environ.get("PUMPKIN_PORT"),
        "speed": os.environ.get("PUMPKIN_SPEED"),
    }
    for k, v in env.items():
        if v:
            cfg[k] = v if k.endswith("_dir") else type(DEFAULTS[k])(v)
    for k, v in overrides.items():
        if v is not None:
            cfg[k] = v
    return Config(cfg)
