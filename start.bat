@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" goto install
py -3.12 -m venv .venv
if errorlevel 1 goto fail
:install
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto fail
echo Open http://127.0.0.1:8000 in your browser. Ctrl+C to stop.
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
if errorlevel 1 goto fail
exit /b 0
:fail
echo Startup failed. Install Python 3.12 with the Python launcher, check network and port 8000.
pause
exit /b 1
