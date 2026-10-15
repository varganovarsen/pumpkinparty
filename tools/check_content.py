"""Проверка контента (CONTENT-FORMAT.md): python tools/check_content.py [папка content]

Код выхода 1, если есть ошибки (предупреждения не считаются).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server.content_check import check  # noqa: E402


def main() -> int:
    content = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "content"
    errors, warnings = check(content)
    for e in errors:
        print(f"ОШИБКА: {e}")
    for w in warnings:
        print(f"внимание: {w}")
    print(f"Итого: ошибок {len(errors)}, предупреждений {len(warnings)}")
    return 1 if errors else 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
