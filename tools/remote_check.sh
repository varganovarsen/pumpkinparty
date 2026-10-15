#!/usr/bin/env bash
# Проверки /check на ноутбуке по ssh, без браузера (с пробным снимком вебки).
#   tools/remote_check.sh <ssh-хост>      (папка проекта: PUMPKIN_DIR, по умолчанию ~/pumpkin)
set -eu
HOST="${1:?Укажите ssh-хост}"
DEST="${PUMPKIN_DIR:-pumpkin}"
ssh "$HOST" "cd '$DEST' && if [ -x .venv/bin/python ]; then PY=.venv/bin/python; else PY=python3; fi; \$PY tools/check_env.py --webcam"
