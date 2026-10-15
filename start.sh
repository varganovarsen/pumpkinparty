#!/usr/bin/env bash
# Запуск на ноутбуке: сервер + Firefox в киоск-режиме на /tv.
#   ./start.sh                сервер и окно телевизора
#   ./start.sh --no-browser   только сервер (например, перезапуск по ssh)
set -u
cd "$(dirname "$0")"

NO_BROWSER=0
for a in "$@"; do [ "$a" = "--no-browser" ] && NO_BROWSER=1; done

# ---- Python и зависимости
PY=python3
if ! command -v "$PY" >/dev/null 2>&1; then
  echo "Не найден python3. Установите: sudo apt install python3 python3-venv"; exit 1
fi
if ! "$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
  echo "Нужен Python 3.11 или новее, сейчас: $("$PY" --version)"; exit 1
fi
if [ ! -x .venv/bin/python ]; then
  echo "Создаю окружение .venv…"
  "$PY" -m venv .venv || { echo "Не удалось создать venv: sudo apt install python3-venv"; exit 1; }
fi
VPY=.venv/bin/python
if ! "$VPY" -c 'import fastapi, multipart, uvicorn, yaml, PIL, pillow_heif, qrcode, cv2, numpy' 2>/dev/null; then
  echo "Устанавливаю зависимости (нужен интернет один раз)…"
  "$VPY" -m pip install -r requirements.txt || { echo "Зависимости не установились"; exit 1; }
fi

PORT=$("$VPY" -c 'from server.config import load_config; print(load_config()["port"])')
URL="http://localhost:$PORT"
mkdir -p data/logs

health() {
  "$VPY" - "$URL" <<'EOF' >/dev/null 2>&1
import sys, urllib.request
urllib.request.urlopen(sys.argv[1] + "/api/health", timeout=1)
EOF
}

# ---- сервер
SERVER_PID=""
if [ -f data/server.pid ] && kill -0 "$(cat data/server.pid)" 2>/dev/null && health; then
  echo "Сервер уже запущен (pid $(cat data/server.pid))."
else
  "$VPY" -m server >>data/logs/stdout.log 2>&1 &
  SERVER_PID=$!
  trap '[ -n "$SERVER_PID" ] && kill "$SERVER_PID" 2>/dev/null' INT TERM
  for _ in $(seq 1 60); do
    health && break
    if ! kill -0 "$SERVER_PID" 2>/dev/null; then
      echo "Сервер не запустился, см. data/logs/stdout.log"; tail -n 20 data/logs/stdout.log; exit 1
    fi
    sleep 0.5
  done
  health || { echo "Сервер не отвечает, см. data/logs/stdout.log"; exit 1; }
  echo "Сервер запущен: $URL (pid $SERVER_PID). Журнал: data/logs/server.log"
fi

# ---- Firefox в киоск-режиме
if [ "$NO_BROWSER" = 0 ]; then
  # запуск по ssh: подхватить графическую сессию пользователя
  if [ -z "${DISPLAY:-}" ] && [ -z "${WAYLAND_DISPLAY:-}" ]; then
    export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
    if [ -S "$XDG_RUNTIME_DIR/wayland-0" ]; then export WAYLAND_DISPLAY=wayland-0; fi
    export DISPLAY=:0
  fi
  # профиль «pumpkin» с разрешённым автовоспроизведением; snap-Firefox видит только ~/snap/firefox
  if [ -e /snap/bin/firefox ] || readlink -f "$(command -v firefox 2>/dev/null)" | grep -q snap; then
    PROFILE="$HOME/snap/firefox/common/pumpkin-profile"
  else
    PROFILE="$HOME/.local/share/pumpkin/firefox-profile"
  fi
  mkdir -p "$PROFILE"
  cat >"$PROFILE/user.js" <<'EOF'
user_pref("media.autoplay.default", 0);
user_pref("media.autoplay.blocking_policy", 0);
user_pref("browser.sessionstore.resume_from_crash", false);
user_pref("browser.shell.checkDefaultBrowser", false);
user_pref("browser.aboutwelcome.enabled", false);
user_pref("browser.startup.homepage_override.mstone", "ignore");
user_pref("datareporting.policy.dataSubmissionPolicyBypassNotification", true);
user_pref("toolkit.telemetry.reportingpolicy.firstRun", false);
user_pref("full-screen-api.warning.timeout", 0);
user_pref("app.update.auto", false);
EOF
  if command -v firefox >/dev/null 2>&1; then
    setsid nohup firefox --kiosk --no-remote --profile "$PROFILE" "$URL/tv" >data/logs/firefox.log 2>&1 &
    FF=$!
    sleep 4
    if kill -0 "$FF" 2>/dev/null; then
      echo "Firefox открыт на $URL/tv"
    else
      echo "Окно Firefox открыть не удалось (это не ошибка сервера)."
      echo "Откройте вручную на ноутбуке: firefox --kiosk --profile \"$PROFILE\" $URL/tv"
    fi
  else
    echo "Firefox не найден. Откройте $URL/tv в браузере на ноутбуке."
  fi
fi

if [ -n "$SERVER_PID" ]; then
  echo "Остановить: Ctrl+C"
  wait "$SERVER_PID"
fi
