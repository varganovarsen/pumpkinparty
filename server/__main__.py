"""Запуск: python -m server [--port 8000] [--data data] [--speed 1] [--config config.yaml]."""
from __future__ import annotations

import argparse

import uvicorn

from .app import create_app
from .config import load_config


def main() -> None:
    ap = argparse.ArgumentParser(description="Тыквенный спас: сервер")
    ap.add_argument("--config", help="путь к config.yaml")
    ap.add_argument("--port", type=int)
    ap.add_argument("--bind", default="0.0.0.0", help="адрес прослушивания (по умолчанию все интерфейсы)")
    ap.add_argument("--data", dest="data_dir", help="папка данных (по умолчанию data/)")
    ap.add_argument("--speed", type=float, help="ускорение времени (симулятор)")
    args = ap.parse_args()
    cfg = load_config(args.config, port=args.port, data_dir=args.data_dir, speed=args.speed)
    app = create_app(cfg)
    uvicorn.run(app, host=args.bind, port=int(cfg["port"]), log_level="warning", ws_ping_interval=10)


if __name__ == "__main__":
    main()
