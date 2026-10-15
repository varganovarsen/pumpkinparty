#!/usr/bin/env bash
# Перенос проекта с ПК на ноутбук по ssh (data/, .git и .venv не трогаются).
#   tools/deploy.sh <ssh-хост> [папка на ноутбуке, по умолчанию ~/pumpkin]
set -eu
HOST="${1:?Укажите ssh-хост: tools/deploy.sh laptop}"
DEST="${2:-pumpkin}"
cd "$(dirname "$0")/.."
ssh "$HOST" "mkdir -p '$DEST'"
if command -v rsync >/dev/null 2>&1; then
  rsync -az --delete --exclude data/ --exclude .git/ --exclude .venv/ --exclude __pycache__/ --exclude .pytest_cache/ ./ "$HOST:$DEST/"
else
  tar -czf - --exclude ./data --exclude ./.git --exclude ./.venv --exclude __pycache__ --exclude .pytest_cache . \
    | ssh "$HOST" "tar -xzf - -C '$DEST'"
fi
ssh "$HOST" "chmod +x '$DEST/start.sh' '$DEST'/tools/*.sh"
echo "Готово: $HOST:$DEST. Перезапуск сервера: tools/remote.sh $HOST restart"
