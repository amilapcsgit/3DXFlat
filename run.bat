@echo off
setlocal

cd /d "%~dp0"

echo [1/2] Installing dependencies from requirements.txt...
python -m pip install -r requirements.txt
if errorlevel 1 (
  echo Failed to install dependencies.
  exit /b 1
)

echo [2/2] Launching 3DXFlat GUI...
python gui.py
set EXIT_CODE=%ERRORLEVEL%

if not "%EXIT_CODE%"=="0" (
  echo GUI exited with error code %EXIT_CODE%.
)

exit /b %EXIT_CODE%
