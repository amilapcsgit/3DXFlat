@echo off
setlocal EnableExtensions EnableDelayedExpansion

cd /d "%~dp0"

set "VENV_DIR=.venv"
set "VENV_PY=%VENV_DIR%\Scripts\python.exe"
set "BASE_PY="
set "BASE_PY_ARGS="

echo === 3DXFlat bootstrap ===

if not exist "%VENV_PY%" (
  echo [1/4] Locating Python...
  where py >nul 2>&1
  if not errorlevel 1 (
    set "BASE_PY=py"
    set "BASE_PY_ARGS=-3"
  ) else (
    where python >nul 2>&1
    if not errorlevel 1 set "BASE_PY=python"
  )

  if not defined BASE_PY (
    echo Python 3.10+ was not found.
    echo Install Python and enable "Add python.exe to PATH", then run this file again.
    echo Download: https://www.python.org/downloads/windows/
    pause
    exit /b 1
  )

  echo [2/4] Creating virtual environment...
  "!BASE_PY!" !BASE_PY_ARGS! -m venv "%VENV_DIR%"
  if errorlevel 1 (
    echo Failed to create virtual environment.
    pause
    exit /b 1
  )
) else (
  echo [1/4] Using existing virtual environment...
)

echo [3/4] Installing/updating dependencies...
"%VENV_PY%" -m pip install --upgrade pip setuptools wheel
if errorlevel 1 (
  echo Failed to upgrade pip tooling.
  pause
  exit /b 1
)

"%VENV_PY%" -m pip install -r requirements.txt
if errorlevel 1 (
  echo Failed to install requirements.
  pause
  exit /b 1
)

echo [4/4] Launching 3DXFlat (Qt/OpenGL)...
set "THREEDXFLAT_FORCE_QT=1"
"%VENV_PY%" main.py
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
  echo.
  echo 3DXFlat exited with code %EXIT_CODE%.
  echo Qt/OpenGL launch was forced and Tk fallback was disabled.
  echo Check GPU driver/OpenGL support and the error details above.
  pause
)

exit /b %EXIT_CODE%
