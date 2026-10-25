@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" goto install
py -3.12 -m venv .venv
if errorlevel 1 goto fail
:install
".venv\Scripts\python.exe" -m pip --version >nul 2>&1
if not errorlevel 1 goto dependencies
echo Repairing missing pip in the local environment...
".venv\Scripts\python.exe" -m ensurepip --upgrade
if errorlevel 1 goto fail
:dependencies
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto fail
echo Browser opens when the service is ready. Keep this window open. Ctrl+C to stop.
".venv\Scripts\python.exe" launch.py
if errorlevel 1 goto fail
exit /b 0
:fail
echo Startup failed. Install Python 3.12 with pip and Python launcher.
echo If .venv was created incompletely, rename it and try again.
echo Check network and port 8000. Do not close this window before reading errors.
pause
exit /b 1
