@echo off
REM Signet: one-command start for Windows. Works from any directory; the path may contain spaces.
REM NOTE: written on macOS and not yet run on Windows.
setlocal
cd /d "%~dp0"

set "PY="
py -3.12 -c "" >nul 2>&1 && set "PY=py -3.12"
if not defined PY (py -3.11 -c "" >nul 2>&1 && set "PY=py -3.11")
if not defined PY (python -c "import sys; sys.exit(sys.version_info[:2] not in ((3, 11), (3, 12)))" >nul 2>&1 && set "PY=python")
if not defined PY (
  echo Error: Python 3.11 or 3.12 is required.
  exit /b 1
)
echo Using %PY%

if not exist ".venv\Scripts\python.exe" (
  echo Creating .venv...
  %PY% -m venv .venv || exit /b 1
)

REM Installs only once so the script also works with Wi-Fi off. Delete .venv\.installed to force a reinstall.
if not exist ".venv\.installed" (
  echo Installing requirements...
  ".venv\Scripts\python.exe" -m pip install -q -r requirements.txt || exit /b 1
  echo installed> ".venv\.installed"
)

".venv\Scripts\python.exe" scripts\setup.py || exit /b 1

".venv\Scripts\python.exe" -c "import joblib; m=joblib.load('models/change_clf.joblib'); assert m.get('training') == 'v2-issued-pages'" >nul 2>&1
if errorlevel 1 (
  echo Training classifier...
  ".venv\Scripts\python.exe" scripts\train_classifier.py || exit /b 1
)
".venv\Scripts\python.exe" -c "from core import data_dir; from pathlib import Path; assert Path('demo/.v2-built').read_text() == str(data_dir().resolve()) and Path('demo/expected.json').is_file() and (data_dir() / 'registry-v2.db').is_file()" >nul 2>&1
if errorlevel 1 (
  echo Creating demo set...
  ".venv\Scripts\python.exe" scripts\make_demo_set.py || exit /b 1
)

if not defined PORT set "PORT=8000"
echo.
echo Signet server starting on:
echo   http://localhost:%PORT%
".venv\Scripts\python.exe" -c "import socket;s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);s.connect(('10.255.255.255',1));print('  http://'+s.getsockname()[0]+':%PORT%')" 2>nul
echo.

".venv\Scripts\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port %PORT%
