"""Проверки /check без браузера (для tools/remote_check.sh по ssh).

    python tools/check_env.py [--webcam] [--port 8000]

Печатает отчёт и возвращает 1, если есть красные пункты.
"""
from __future__ import annotations

import argparse
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

MARK = {"ok": "[ OK ]", "warn": "[ !! ]", "fail": "[FAIL]", "info": "[info]"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--webcam", action="store_true", help="сделать пробный снимок с вебки")
    ap.add_argument("--port", type=int)
    args = ap.parse_args()

    try:
        from server.checks import FAIL, OK, static_checks
        from server.config import load_config
        from server.qr import base_url
    except Exception as e:  # noqa: BLE001
        print(f"{MARK['fail']} Сервер не импортируется (зависимости?): {e}")
        return 1

    cfg = load_config()
    port = args.port or int(cfg["port"])
    items = static_checks(cfg)
    items.insert(0, {"title": "Адрес для гостей", "status": "info", "detail": base_url(cfg["public_host"], port), "items": []})

    with socket.socket() as s:
        s.settimeout(1)
        listening = s.connect_ex(("127.0.0.1", port)) == 0
    items.append({"title": f"Сервер слушает порт {port}", "status": OK if listening else "warn",
                  "detail": "да" if listening else "нет (сервер не запущен?)", "items": []})

    if args.webcam:
        from server.webcam import WebcamError, snapshot
        try:
            jpg = snapshot(int(cfg["webcam_device"]))
            out = cfg.data_dir / "webcam_test.jpg"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(jpg)
            items.append({"title": "Снимок с вебки", "status": OK, "detail": f"{len(jpg) // 1024} КБ → {out}", "items": []})
        except WebcamError as e:
            items.append({"title": "Снимок с вебки", "status": FAIL, "detail": str(e), "items": []})

    for it in items:
        print(f"{MARK.get(it['status'], '[ ?? ]')} {it['title']}: {it['detail']}")
        for x in it.get("items", []):
            print(f"         - {x}")
    fails = sum(it["status"] == FAIL for it in items)
    print(f"\nКрасных пунктов: {fails}")
    return 1 if fails else 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
