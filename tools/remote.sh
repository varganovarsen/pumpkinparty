#!/usr/bin/env bash
# Удалённые команды на ноутбуке по ssh.
#   tools/remote.sh <ssh-хост> status    отвечает ли сервер
#   tools/remote.sh <ssh-хост> log       журнал сервера (Ctrl+C для выхода)
#   tools/remote.sh <ssh-хост> restart   перезапустить сервер (окно Firefox само переподключится)
#   tools/remote.sh <ssh-хост> stop      остановить сервер насовсем
#   tools/remote.sh <ssh-хост> browser   открыть окно ТВ (может не получиться по ssh, см. CHECKLIST)
# Папка проекта на ноутбуке: переменная PUMPKIN_DIR (по умолчанию ~/pumpkin).
# start.sh держит супервизор: упавший или убитый сервер поднимается сам через 2 с.
set -eu
HOST="${1:?Укажите ssh-хост}"
CMD="${2:-status}"
DEST="${PUMPKIN_DIR:-pumpkin}"
KILL_SERVER="if [ -f data/server.pid ]; then kill \$(cat data/server.pid) 2>/dev/null || true; for i in \$(seq 1 20); do kill -0 \$(cat data/server.pid) 2>/dev/null || break; sleep 0.5; done; fi"
SUPERVISED="[ -f data/supervisor.pid ] && kill -0 \$(cat data/supervisor.pid) 2>/dev/null"
case "$CMD" in
  status)  ssh "$HOST" "cd '$DEST' && .venv/bin/python -c \"import urllib.request,json;print(urllib.request.urlopen('http://localhost:8000/api/health',timeout=2).read().decode())\" || echo 'Сервер не отвечает'" ;;
  log)     ssh -t "$HOST" "tail -n 200 -F '$DEST/data/logs/server.log'" ;;
  stop)    ssh "$HOST" "cd '$DEST' && touch data/.stop && $KILL_SERVER; if $SUPERVISED; then kill \$(cat data/supervisor.pid); fi; rm -f data/supervisor.pid; echo остановлен" ;;
  restart) ssh "$HOST" "cd '$DEST' && if $SUPERVISED; then $KILL_SERVER; echo 'перезапуск супервизором…'; else (setsid nohup ./start.sh --no-browser >data/logs/start.log 2>&1 &); fi; sleep 4; .venv/bin/python -c \"import urllib.request;print(urllib.request.urlopen('http://localhost:8000/api/health',timeout=3).read().decode())\" || echo 'Сервер пока не отвечает'" ;;
  browser) ssh "$HOST" "cd '$DEST' && ./start.sh" ;;
  *) echo "Неизвестная команда: $CMD"; exit 1 ;;
esac
