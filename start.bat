@echo off
rem Запуск сервера на Windows (разработка). Окно ТВ: http://localhost:8000/tv
chcp 65001 >nul
setlocal
cd /d "%~dp0"

set "PY=python"
where py >nul 2>nul
if %errorlevel%==0 set "PY=py -3"

%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)"
if errorlevel 1 (
  echo Нужен Python 3.11 или новее: https://www.python.org/downloads/
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo Создаю окружение .venv...
  %PY% -m venv .venv
)

".venv\Scripts\python.exe" -c "import fastapi, multipart, uvicorn, yaml, PIL, pillow_heif, qrcode, cv2, numpy" 2>nul
if errorlevel 1 (
  echo Устанавливаю зависимости...
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 (
    echo Зависимости не установились
    pause
    exit /b 1
  )
)

".venv\Scripts\python.exe" -m server %*
