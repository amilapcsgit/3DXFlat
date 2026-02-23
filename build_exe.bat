@echo off
setlocal EnableExtensions EnableDelayedExpansion

cd /d "%~dp0"
set "REPO_PATH=%CD%"
set "BUILD_LOG=%REPO_PATH%\build_exe.log"
>"%BUILD_LOG%" echo === 3DXFlat standalone build log ===

set "BASE_PY="
set "PY_VER="
set "CLEAN_BUILD=0"
if /I "%~1"=="--clean" set "CLEAN_BUILD=1"

echo === 3DXFlat standalone builder ===
echo [1/5] Locating Python...
call :find_python

if not defined BASE_PY (
  call :log "ERROR: Python 3.10+ not found in PATH."
  echo Python 3.10+ was not found.
  echo Install Python and enable "Add python.exe to PATH", then run again.
  echo Download: https://www.python.org/downloads/windows/
  echo See build log: %BUILD_LOG%
  exit /b 1
)

echo     Found Python %PY_VER% at %BASE_PY%

set "VENV_DIR=%REPO_PATH%\.venv-build"
set "VENV_PY=%VENV_DIR%\Scripts\python.exe"

if "%CLEAN_BUILD%"=="1" (
  if exist "%VENV_DIR%" (
    echo     Removing existing build virtual environment...
    rmdir /s /q "%VENV_DIR%"
  )
)

if not exist "%VENV_PY%" (
  echo [2/5] Creating build virtual environment...
  call :log "CMD START: \"%BASE_PY%\" -m venv \"%VENV_DIR%\""
  "%BASE_PY%" -m venv "%VENV_DIR%" >>"%BUILD_LOG%" 2>&1
  set "RC=!ERRORLEVEL!"
  call :log "CMD END rc=!RC!"
  if not "!RC!"=="0" (
    call :log "ERROR: Failed to create build virtual environment."
    echo Failed to create build virtual environment.
    echo See build log: %BUILD_LOG%
    exit /b 1
  )
) else (
  echo [2/5] Using existing build virtual environment...
)

if not exist "%VENV_PY%" (
  call :log "ERROR: Build venv python missing: %VENV_PY%"
  echo Build virtual environment python executable not found: %VENV_PY%
  echo See build log: %BUILD_LOG%
  exit /b 1
)

echo [3/5] Installing build dependencies...
call :log "CMD START: \"%VENV_PY%\" -m pip install --upgrade pip setuptools wheel"
"%VENV_PY%" -m pip install --upgrade pip setuptools wheel >>"%BUILD_LOG%" 2>&1
set "RC=!ERRORLEVEL!"
call :log "CMD END rc=!RC!"
if not "!RC!"=="0" (
  call :log "ERROR: Failed to upgrade pip tooling."
  echo Failed to upgrade pip tooling.
  echo See build log: %BUILD_LOG%
  exit /b 1
)

call :log "CMD START: \"%VENV_PY%\" -m pip install -r requirements.txt -r requirements-build.txt"
"%VENV_PY%" -m pip install -r requirements.txt -r requirements-build.txt >>"%BUILD_LOG%" 2>&1
set "RC=!ERRORLEVEL!"
call :log "CMD END rc=!RC!"
if not "!RC!"=="0" (
  call :log "ERROR: Failed to install build dependencies."
  echo Failed to install build dependencies.
  echo See build log: %BUILD_LOG%
  exit /b 1
)

echo [4/5] Building standalone executable...
if exist "%REPO_PATH%\build" rmdir /s /q "%REPO_PATH%\build"
if exist "%REPO_PATH%\dist\3DXFlat" rmdir /s /q "%REPO_PATH%\dist\3DXFlat"

call :log "CMD START: PyInstaller build"
"%VENV_PY%" -m PyInstaller ^
  --noconfirm ^
  --clean ^
  --windowed ^
  --onedir ^
  --name 3DXFlat ^
  --icon "ui\assets\brand\app_icon.ico" ^
  --collect-data customtkinter ^
  --collect-data matplotlib ^
  --collect-binaries gmsh ^
  --collect-binaries igl ^
  --collect-data qt_material ^
  --collect-data ui ^
  --hidden-import darkdetect ^
  --hidden-import matplotlib.backends.backend_qtagg ^
  --hidden-import matplotlib.backends.backend_tkagg ^
  --hidden-import pyqtgraph.opengl ^
  --hidden-import OpenGL.GL ^
  --hidden-import OpenGL.arrays.vbo ^
  --hidden-import PySide6.QtSvg ^
  --hidden-import PySide6.QtOpenGLWidgets ^
  --hidden-import ui.resources_rc ^
  main.py >>"%BUILD_LOG%" 2>&1
set "RC=!ERRORLEVEL!"
call :log "CMD END rc=!RC!"
if not "!RC!"=="0" (
  call :log "ERROR: PyInstaller build failed."
  echo PyInstaller build failed.
  echo See build log: %BUILD_LOG%
  exit /b 1
)

echo [5/5] Verifying output...
if not exist "%REPO_PATH%\dist\3DXFlat\3DXFlat.exe" (
  call :log "ERROR: Missing dist\3DXFlat\3DXFlat.exe"
  echo Build finished but dist\3DXFlat\3DXFlat.exe was not found.
  echo See build log: %BUILD_LOG%
  exit /b 1
)

echo.
echo Build complete: dist\3DXFlat\3DXFlat.exe
echo Deploy by copying the entire dist\3DXFlat folder to the target PC.
echo Build log: %BUILD_LOG%
exit /b 0

:find_python
set "BASE_PY="
set "PY_VER="

where.exe py >nul 2>&1
if not errorlevel 1 (
  set "CAND_EXE="
  for /f "usebackq delims=" %%P in (`py -3.13 -c "import sys; print(sys.executable)" 2^>nul`) do if not defined CAND_EXE set "CAND_EXE=%%P"
  if defined CAND_EXE call :accept_python "!CAND_EXE!"
  if not defined BASE_PY (
    set "CAND_EXE="
    for /f "usebackq delims=" %%P in (`py -3 -c "import sys; print(sys.executable)" 2^>nul`) do if not defined CAND_EXE set "CAND_EXE=%%P"
    if defined CAND_EXE call :accept_python "!CAND_EXE!"
  )
)

if not defined BASE_PY (
  where.exe python >nul 2>&1
  if not errorlevel 1 (
    for /f "usebackq delims=" %%P in (`where.exe python 2^>nul`) do (
      if not defined BASE_PY call :accept_python "%%P"
    )
  )
)
goto :eof

:accept_python
set "CAND_EXE=%~1"
if not defined CAND_EXE goto :eof
if not exist "%CAND_EXE%" goto :eof
"%CAND_EXE%" -c "import sys; raise SystemExit(0 if sys.version_info>=(3,10) else 1)" >nul 2>&1
if errorlevel 1 goto :eof
for /f "tokens=2 delims= " %%V in ('"%CAND_EXE%" -V 2^>^&1') do set "CAND_VER=%%V"
set "BASE_PY=%CAND_EXE%"
set "PY_VER=%CAND_VER%"
goto :eof

:log
>>"%BUILD_LOG%" echo [%DATE% %TIME%] %*
goto :eof
